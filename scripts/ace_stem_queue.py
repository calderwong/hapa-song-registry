#!/usr/bin/env python3
"""ACE Studio / ACE Step stem-split queue controller for Hapa Song Registry.

This is the safe control-plane for the workflow: it identifies songs that do not
have a basic two-stem split, creates a queue, serves a small local dashboard,
opens the active song in ACE Studio, and watches for exported `vocals` + `music`
stems beside the original song.

The actual ACE GUI export sequence is deliberately isolated behind the
`open_current_in_ace` action until the UI is calibrated on the local machine.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import pathlib
import re
import shutil
import subprocess
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
REGISTRY_PATH = DATA_DIR / "registry.json"
QUEUE_DIR = DATA_DIR / "ace-stem-queue"
STATE_PATH = QUEUE_DIR / "state.json"
EXPORT_ROOT = DATA_DIR / "ace-stems"
EVENTS_PATH = DATA_DIR / "history_events.json"
ACE_APP_NAME = "ACE Studio"
PORT = 8797

BASIC_VOCAL_TYPES = {"vocals", "vocal", "voice", "lead vocals", "ace vocals", "ace vocal"}
BASIC_MUSIC_TYPES = {"music", "instrumental", "accompaniment", "karaoke", "backing track", "ace music"}
AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".aiff", ".flac"}


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def read_json(path: pathlib.Path, fallback):
    try:
        if not path.exists():
            return fallback
        return json.loads(path.read_text())
    except Exception:
        return fallback


def write_json(path: pathlib.Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def append_history(event: dict) -> dict:
    events = read_json(EVENTS_PATH, [])
    record = {"id": event.get("id") or str(uuid.uuid4()), "at": now_iso(), **event}
    events.append(record)
    write_json(EVENTS_PATH, events)
    return record


def safe_file_part(value: str, limit: int = 90) -> str:
    value = re.sub(r"[\\/:*?\"<>|]", "_", str(value or "song"))
    value = re.sub(r"\s+", " ", value).strip()
    return (value[:limit] or "song").strip(" .")


def load_registry() -> dict:
    return read_json(REGISTRY_PATH, {"songs": [], "stems": [], "counts": {}})


def stem_type(stem: dict) -> str:
    return str(stem.get("stemType") or stem.get("type") or stem.get("title") or "").strip().lower()


def song_has_basic_split(song: dict, stems_by_parent: dict[str, list[dict]]) -> bool:
    song_id = song.get("id")
    stems = stems_by_parent.get(song_id, [])
    types = {stem_type(s) for s in stems}
    has_vocal = any(t in BASIC_VOCAL_TYPES or "vocal" in t or "voice" in t for t in types)
    has_music = any(t in BASIC_MUSIC_TYPES or "instrumental" in t or "music" in t or "accompaniment" in t for t in types)
    export_dir = EXPORT_ROOT / str(song_id)
    if export_dir.exists():
        names = [p.name.lower() for p in export_dir.iterdir() if p.suffix.lower() in AUDIO_EXTS]
        has_vocal = has_vocal or any("vocal" in n or "voice" in n for n in names)
        has_music = has_music or any("music" in n or "instrumental" in n or "accompaniment" in n for n in names)
    return has_vocal and has_music


def discover_missing(limit: int | None = None) -> list[dict]:
    registry = load_registry()
    stems_by_parent: dict[str, list[dict]] = {}
    for stem in registry.get("stems", []):
        parent = stem.get("parentId") or stem.get("songId") or stem.get("parentSongId")
        if parent:
            stems_by_parent.setdefault(parent, []).append(stem)
    jobs = []
    for song in registry.get("songs", []):
        path = song.get("localPath") or song.get("path") or song.get("audioPath")
        if not path or not pathlib.Path(path).exists():
            continue
        if song_has_basic_split(song, stems_by_parent):
            continue
        jobs.append({
            "id": str(uuid.uuid4()),
            "songId": song.get("id"),
            "title": song.get("title") or pathlib.Path(path).stem,
            "sourcePath": path,
            "exportDir": str(EXPORT_ROOT / str(song.get("id"))),
            "status": "queued",
            "attempts": 0,
            "createdAt": now_iso(),
            "updatedAt": now_iso(),
        })
        if limit and len(jobs) >= limit:
            break
    return jobs


def default_state() -> dict:
    return {
        "schemaVersion": 1,
        "mode": "stopped",
        "activeJobId": None,
        "createdAt": now_iso(),
        "updatedAt": now_iso(),
        "queue": [],
        "telemetry": {"opened": 0, "completed": 0, "failed": 0, "skipped": 0},
        "notes": ["ACE GUI export automation requires local UI calibration; dashboard currently opens jobs and watches for saved stems."],
    }


def load_state() -> dict:
    state = read_json(STATE_PATH, None)
    if not state:
        state = default_state()
        write_json(STATE_PATH, state)
    return state


def save_state(state: dict) -> dict:
    state["updatedAt"] = now_iso()
    write_json(STATE_PATH, state)
    return state


def create_queue(limit: int | None = None, replace: bool = False) -> dict:
    state = load_state()
    new_jobs = discover_missing(limit=limit)
    if replace:
        state["queue"] = new_jobs
    else:
        existing = {j.get("songId") for j in state.get("queue", []) if j.get("status") not in {"completed", "failed", "skipped"}}
        state["queue"].extend([j for j in new_jobs if j.get("songId") not in existing])
    append_history({"type": "aceStemQueue.created", "jobsAdded": len(new_jobs), "replace": replace})
    return save_state(state)


def next_job(state: dict) -> dict | None:
    active_id = state.get("activeJobId")
    for job in state.get("queue", []):
        if job.get("id") == active_id and job.get("status") in {"opening", "waiting_for_export", "export_detected"}:
            return job
    for job in state.get("queue", []):
        if job.get("status") == "queued":
            return job
    return None


def open_in_ace(job: dict) -> None:
    pathlib.Path(job["exportDir"]).mkdir(parents=True, exist_ok=True)
    subprocess.run(["open", "-a", ACE_APP_NAME, job["sourcePath"]], check=False)


def start_queue() -> dict:
    state = load_state()
    state["mode"] = "running"
    job = next_job(state)
    if job:
        job["status"] = "opening"
        job["attempts"] = int(job.get("attempts", 0)) + 1
        job["updatedAt"] = now_iso()
        state["activeJobId"] = job["id"]
        open_in_ace(job)
        job["status"] = "waiting_for_export"
        state["telemetry"]["opened"] = int(state["telemetry"].get("opened", 0)) + 1
        append_history({"type": "aceStemQueue.job.opened", "songId": job.get("songId"), "title": job.get("title"), "sourcePath": job.get("sourcePath"), "exportDir": job.get("exportDir")})
    return save_state(state)


def pause_queue() -> dict:
    state = load_state()
    state["mode"] = "paused"
    append_history({"type": "aceStemQueue.paused"})
    return save_state(state)


def stop_queue() -> dict:
    state = load_state()
    state["mode"] = "stopped"
    append_history({"type": "aceStemQueue.stopped"})
    return save_state(state)


def find_exported_pair(job: dict) -> tuple[pathlib.Path | None, pathlib.Path | None]:
    export_dir = pathlib.Path(job["exportDir"])
    if not export_dir.exists():
        return None, None
    audio = [p for p in export_dir.iterdir() if p.suffix.lower() in AUDIO_EXTS]
    vocal = next((p for p in audio if "vocal" in p.name.lower() or "voice" in p.name.lower()), None)
    music = next((p for p in audio if "music" in p.name.lower() or "instrumental" in p.name.lower() or "accompaniment" in p.name.lower()), None)
    return vocal, music


def mark_complete(job_id: str | None = None) -> dict:
    state = load_state()
    target = None
    for job in state.get("queue", []):
        if (job_id and job.get("id") == job_id) or (not job_id and job.get("id") == state.get("activeJobId")):
            target = job
            break
    if not target:
        return state
    vocal, music = find_exported_pair(target)
    target["status"] = "completed"
    target["completedAt"] = now_iso()
    target["vocalStemPath"] = str(vocal) if vocal else None
    target["musicStemPath"] = str(music) if music else None
    target["updatedAt"] = now_iso()
    state["telemetry"]["completed"] = int(state["telemetry"].get("completed", 0)) + 1
    state["activeJobId"] = None
    append_history({"type": "aceStemQueue.job.completed", "songId": target.get("songId"), "title": target.get("title"), "vocalStemPath": target.get("vocalStemPath"), "musicStemPath": target.get("musicStemPath")})
    if state.get("mode") == "running":
        save_state(state)
        return start_queue()
    return save_state(state)


def monitor_once() -> dict:
    state = load_state()
    changed = False
    for job in state.get("queue", []):
        if job.get("status") == "waiting_for_export":
            vocal, music = find_exported_pair(job)
            if vocal and music:
                job["status"] = "export_detected"
                job["vocalStemPath"] = str(vocal)
                job["musicStemPath"] = str(music)
                job["updatedAt"] = now_iso()
                changed = True
                append_history({"type": "aceStemQueue.job.exportDetected", "songId": job.get("songId"), "vocalStemPath": str(vocal), "musicStemPath": str(music)})
    if changed:
        save_state(state)
    return state


def monitor_loop(stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        monitor_once()
        time.sleep(3)


def render_html(state: dict) -> str:
    counts = {k: 0 for k in ["queued", "waiting_for_export", "export_detected", "completed", "failed", "skipped"]}
    for job in state.get("queue", []):
        counts[job.get("status", "queued")] = counts.get(job.get("status", "queued"), 0) + 1
    rows = []
    for job in state.get("queue", [])[:200]:
        rows.append(f"<tr><td>{html.escape(job.get('status',''))}</td><td>{html.escape(job.get('title',''))}</td><td><code>{html.escape(job.get('songId',''))}</code></td><td><code>{html.escape(job.get('exportDir',''))}</code></td></tr>")
    return f"""<!doctype html><html><head><meta charset='utf-8'><title>Hapa ACE Stem Queue</title>
<style>body{{font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#080912;color:#f4f0ff;margin:32px}}button{{margin:4px;padding:10px 14px;border-radius:10px;border:1px solid #6d5df5;background:#151735;color:#fff}}.card{{background:#101323;border:1px solid #262a4a;border-radius:16px;padding:18px;margin:14px 0}}code{{color:#9be7ff}}table{{width:100%;border-collapse:collapse}}td,th{{border-bottom:1px solid #252946;padding:8px;text-align:left}}</style>
</head><body><h1>Hapa ACE Stem Queue</h1>
<div class='card'><b>Mode:</b> {html.escape(state.get('mode',''))} <b>Active:</b> <code>{html.escape(str(state.get('activeJobId')))}</code><br><b>Counts:</b> {html.escape(json.dumps(counts))}<br><b>Telemetry:</b> {html.escape(json.dumps(state.get('telemetry',{})))}</div>
<form method='post' action='/action'><button name='action' value='create'>Create/append missing-stem queue</button><button name='action' value='replace'>Replace queue</button><button name='action' value='start'>Start/open next in ACE</button><button name='action' value='pause'>Pause</button><button name='action' value='stop'>Stop</button><button name='action' value='monitor'>Scan exports</button><button name='action' value='complete'>Mark active complete</button></form>
<div class='card'><p>Export current ACE job into: <code>data/ace-stems/&lt;songId&gt;/</code> using filenames that include <code>vocals</code> and <code>music</code> or <code>instrumental</code>. The monitor will detect the pair and advance the queue.</p></div>
<table><thead><tr><th>Status</th><th>Title</th><th>Song ID</th><th>Export Dir</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, body: bytes, content_type="text/html", code=200):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/state.json":
            self._send(json.dumps(load_state(), indent=2).encode(), "application/json")
            return
        self._send(render_html(load_state()).encode())

    def do_POST(self):
        length = int(self.headers.get("content-length", "0") or "0")
        body = self.rfile.read(length).decode()
        action = parse_qs(body).get("action", [""])[0]
        if action == "create":
            create_queue(replace=False)
        elif action == "replace":
            create_queue(replace=True)
        elif action == "start":
            start_queue()
        elif action == "pause":
            pause_queue()
        elif action == "stop":
            stop_queue()
        elif action == "monitor":
            monitor_once()
        elif action == "complete":
            mark_complete()
        self.send_response(303)
        self.send_header("Location", "/")
        self.end_headers()


def serve(port: int = PORT, open_browser: bool = False):
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    EXPORT_ROOT.mkdir(parents=True, exist_ok=True)
    load_state()
    stop_event = threading.Event()
    watcher = threading.Thread(target=monitor_loop, args=(stop_event,), daemon=True)
    watcher.start()
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}"
    print(f"Hapa ACE Stem Queue running at {url}")
    if open_browser:
        subprocess.run(["open", url], check=False)
    try:
        server.serve_forever()
    finally:
        stop_event.set()


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("queue")
    q.add_argument("--limit", type=int)
    q.add_argument("--replace", action="store_true")
    sub.add_parser("start")
    sub.add_parser("pause")
    sub.add_parser("stop")
    sub.add_parser("monitor")
    sub.add_parser("state")
    s = sub.add_parser("serve")
    s.add_argument("--port", type=int, default=PORT)
    s.add_argument("--open", action="store_true")
    args = parser.parse_args()
    if args.cmd == "queue":
        print(json.dumps(create_queue(limit=args.limit, replace=args.replace), indent=2))
    elif args.cmd == "start":
        print(json.dumps(start_queue(), indent=2))
    elif args.cmd == "pause":
        print(json.dumps(pause_queue(), indent=2))
    elif args.cmd == "stop":
        print(json.dumps(stop_queue(), indent=2))
    elif args.cmd == "monitor":
        print(json.dumps(monitor_once(), indent=2))
    elif args.cmd == "state":
        print(json.dumps(load_state(), indent=2))
    elif args.cmd == "serve":
        serve(port=args.port, open_browser=args.open)


if __name__ == "__main__":
    main()
