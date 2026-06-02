#!/usr/bin/env python3
"""Export the current ACE stem queue with Demucs as a calibrated local fallback.

Reads data/ace-stem-queue/state.json, runs two-stem vocal separation for the
first N queued jobs, and writes the queue's expected files:
  data/ace-stems/<songId>/vocals.wav
  data/ace-stems/<songId>/music.wav

This keeps the queue's success condition identical: verified files on disk.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "data" / "ace-stem-queue" / "state.json"
TMP_ROOT = ROOT / "data" / "ace-stem-queue" / "demucs-work"
HISTORY_PATH = ROOT / "data" / "history_events.json"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_state() -> dict:
    return json.loads(STATE_PATH.read_text())


def save_state(state: dict) -> None:
    state["updatedAt"] = now()
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2) + "\n")


def append_event(event_type: str, payload: dict) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        events = json.loads(HISTORY_PATH.read_text())
        if not isinstance(events, list):
            events = []
    except Exception:
        events = []
    events.append({"type": event_type, "createdAt": now(), **payload})
    HISTORY_PATH.write_text(json.dumps(events, indent=2) + "\n")


def run_job(job: dict) -> None:
    source = Path(job["sourcePath"])
    export_dir = Path(job["exportDir"])
    if not source.exists():
        raise FileNotFoundError(source)
    export_dir.mkdir(parents=True, exist_ok=True)

    # Keep only final expected names in the export folder for deterministic verification.
    for name in ("vocals.wav", "music.wav"):
        p = export_dir / name
        if p.exists():
            p.unlink()

    work = TMP_ROOT / job["songId"]
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        "-m",
        "demucs",
        "--two-stems=vocals",
        "--name",
        "htdemucs",
        "--out",
        str(work),
        str(source),
    ]
    print("RUN", " ".join(map(str, cmd)), flush=True)
    subprocess.run(cmd, cwd=str(ROOT), check=True)

    # Demucs writes work/htdemucs/<input-stem>/{vocals,no_vocals}.wav
    matches = list(work.glob("htdemucs/*/vocals.wav"))
    if not matches:
        raise FileNotFoundError(f"Demucs vocals output missing under {work}")
    vocals = matches[0]
    music = vocals.with_name("no_vocals.wav")
    if not music.exists():
        raise FileNotFoundError(music)
    shutil.copy2(vocals, export_dir / "vocals.wav")
    shutil.copy2(music, export_dir / "music.wav")
    print("WROTE", export_dir / "vocals.wav", export_dir / "music.wav", flush=True)


def main() -> int:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    state = load_state()
    jobs = state.get("queue", [])[:limit]
    state["mode"] = "running"
    save_state(state)
    ok = 0
    for job in jobs:
        state = load_state()
        job_in_state = next((j for j in state.get("queue", []) if j.get("id") == job.get("id")), job)
        job_in_state["status"] = "waiting_for_export"
        job_in_state["attempts"] = int(job_in_state.get("attempts", 0)) + 1
        job_in_state["updatedAt"] = now()
        state["activeJobId"] = job_in_state.get("id")
        save_state(state)
        append_event("aceStemQueue.job.demucs.started", {"jobId": job_in_state.get("id"), "songId": job_in_state.get("songId"), "sourcePath": job_in_state.get("sourcePath")})
        try:
            run_job(job_in_state)
            job_in_state["status"] = "completed"
            job_in_state["vocalStemPath"] = str(Path(job_in_state["exportDir"]) / "vocals.wav")
            job_in_state["musicStemPath"] = str(Path(job_in_state["exportDir"]) / "music.wav")
            job_in_state["updatedAt"] = now()
            state = load_state()
            for idx, queued in enumerate(state.get("queue", [])):
                if queued.get("id") == job_in_state.get("id"):
                    state["queue"][idx].update(job_in_state)
            state.setdefault("telemetry", {})["completed"] = int(state.setdefault("telemetry", {}).get("completed", 0)) + 1
            save_state(state)
            append_event("aceStemQueue.job.completed", {"jobId": job_in_state.get("id"), "songId": job_in_state.get("songId"), "vocalStemPath": job_in_state["vocalStemPath"], "musicStemPath": job_in_state["musicStemPath"], "separator": "demucs htdemucs two-stems=vocals"})
            ok += 1
        except Exception as exc:
            state = load_state()
            for queued in state.get("queue", []):
                if queued.get("id") == job_in_state.get("id"):
                    queued["status"] = "failed"
                    queued["error"] = str(exc)
                    queued["updatedAt"] = now()
            state.setdefault("telemetry", {})["failed"] = int(state.setdefault("telemetry", {}).get("failed", 0)) + 1
            save_state(state)
            append_event("aceStemQueue.job.failed", {"jobId": job_in_state.get("id"), "songId": job_in_state.get("songId"), "error": str(exc)})
            raise
    state = load_state()
    state["mode"] = "stopped"
    state["activeJobId"] = None
    save_state(state)
    print(f"completed={ok}/{len(jobs)}", flush=True)
    return 0 if ok == len(jobs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
