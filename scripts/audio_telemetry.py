#!/usr/bin/env python3
"""Analyze-once/use-many audio telemetry queue for Hapa Song Registry.

This script intentionally has a stdlib/ffmpeg baseline so the telemetry layer works
before heavier MIR dependencies (librosa/demucs/essentia) are installed. When
ffprobe/ffmpeg are available it extracts real duration/format/loudness-ish peak
and PCM peak windows. When they are not available, it still writes provenance-rich
blocked/fallback artifacts instead of silently pretending hook detection is fact.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
import pathlib
import shutil
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import wave
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
REGISTRY_PATH = DATA / "registry.json"
DB_PATH = DATA / "hapa_registry.sqlite"
TELEMETRY_ROOT = DATA / "audio_telemetry"
QUEUE_PATH = TELEMETRY_ROOT / "queue.json"
ANALYZER = "hapa-audio-telemetry"
ANALYZER_VERSION = "1.0.0"
SCHEMA_VERSION = 1
DEFAULT_PEAK_WINDOW_MS = 50
DEFAULT_SAMPLE_RATE = 22050


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: pathlib.Path, fallback: Any) -> Any:
    try:
        if not path.exists():
            return fallback
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def write_json(path: pathlib.Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def stable_id(*parts: Any, prefix: str = "job") -> str:
    digest = hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def sha256_file(path: pathlib.Path, limit_bytes: Optional[int] = None) -> Optional[str]:
    try:
        h = hashlib.sha256()
        remaining = limit_bytes
        with path.open("rb") as f:
            while True:
                if remaining is not None and remaining <= 0:
                    break
                chunk_size = 1024 * 1024 if remaining is None else min(1024 * 1024, remaining)
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                h.update(chunk)
                if remaining is not None:
                    remaining -= len(chunk)
        return h.hexdigest()
    except Exception:
        return None


def file_info(path_value: str) -> Dict[str, Any]:
    p = pathlib.Path(path_value) if path_value else pathlib.Path("/__missing__")
    exists = p.exists()
    st = p.stat() if exists else None
    return {
        "path": str(p) if path_value else None,
        "exists": exists,
        "sizeBytes": st.st_size if st else None,
        "mtime": datetime.fromtimestamp(st.st_mtime, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z") if st else None,
        "sha256": sha256_file(p) if exists and st and st.st_size <= 100 * 1024 * 1024 else None,
        "sha256Head": sha256_file(p, limit_bytes=4 * 1024 * 1024) if exists else None,
    }


def ensure_layout() -> None:
    for sub in ["manifests", "runs", "latest", "exports"]:
        (TELEMETRY_ROOT / sub).mkdir(parents=True, exist_ok=True)


def load_registry(path: Optional[pathlib.Path] = None) -> Dict[str, Any]:
    path = path or REGISTRY_PATH
    registry = read_json(path, None)
    if not isinstance(registry, dict):
        raise SystemExit(f"Missing registry JSON at {path}; run npm run ingest first.")
    registry.setdefault("songs", [])
    registry.setdefault("counts", {})
    return registry


def default_queue() -> Dict[str, Any]:
    now = utcnow()
    return {
        "schemaVersion": SCHEMA_VERSION,
        "mode": "stopped",
        "activeJobIds": [],
        "createdAt": now,
        "updatedAt": now,
        "defaults": {
            "analyzer": ANALYZER,
            "analyzerVersion": ANALYZER_VERSION,
            "requiredKinds": ["summary", "peaks", "beats", "sections", "hooks"],
            "overwrite": False,
        },
        "telemetry": {"queued": 0, "running": 0, "completed": 0, "failed": 0, "skipped": 0, "blocked": 0},
        "queue": [],
    }


def load_queue() -> Dict[str, Any]:
    ensure_layout()
    state = read_json(QUEUE_PATH, None)
    if not isinstance(state, dict):
        state = default_queue()
    state.setdefault("queue", [])
    state.setdefault("telemetry", {})
    return state


def save_queue(state: Dict[str, Any]) -> None:
    counts = {k: 0 for k in ["queued", "claimed", "running", "writing", "completed", "failed", "skipped", "blocked"]}
    for job in state.get("queue", []):
        status = job.get("status", "queued")
        counts[status] = counts.get(status, 0) + 1
    state["telemetry"] = counts
    state["updatedAt"] = utcnow()
    write_json(QUEUE_PATH, state)


def analysis_key(song: Dict[str, Any], source: Dict[str, Any], params: Dict[str, Any]) -> str:
    payload = {
        "songId": song.get("id"),
        "path": source.get("path"),
        "sizeBytes": source.get("sizeBytes"),
        "mtime": source.get("mtime"),
        "sha256": source.get("sha256") or source.get("sha256Head"),
        "analyzer": ANALYZER,
        "version": ANALYZER_VERSION,
        "params": params,
    }
    return "sha256:" + hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def manifest_for(song_id: str) -> Optional[Dict[str, Any]]:
    m = read_json(TELEMETRY_ROOT / "manifests" / f"{song_id}.json", None)
    return m if isinstance(m, dict) else None


def latest_matches(song_id: str, key: str) -> bool:
    m = manifest_for(song_id)
    return bool(m and m.get("analysisKey") == key and pathlib.Path(m.get("runPath", "")).exists())


def make_job(song: Dict[str, Any], priority: int = 50, overwrite: bool = False) -> Dict[str, Any]:
    params = {"sampleRate": DEFAULT_SAMPLE_RATE, "peakWindowMs": DEFAULT_PEAK_WINDOW_MS, "beatTracker": "ffmpeg+internal", "sectionMethod": "energy+lyrics", "hookMethod": "repetition+energy+lyric_chorus_candidate"}
    source = file_info(song.get("localPath") or "")
    key = analysis_key(song, source, params)
    status = "queued"
    last_error = None
    if not source.get("exists"):
        status = "blocked"
        last_error = "missing source audio"
    elif not overwrite and latest_matches(song.get("id"), key):
        status = "skipped"
    return {
        "id": stable_id(song.get("id"), key, prefix="job"),
        "songId": song.get("id"),
        "title": song.get("title") or "Untitled",
        "status": status,
        "priority": priority,
        "attempts": 0,
        "maxAttempts": 3,
        "createdAt": utcnow(),
        "updatedAt": utcnow(),
        "sourceAudio": source,
        "inputRefs": {"registryGeneratedAt": song.get("generatedAt"), "lyricTimingRunId": (song.get("lyricTiming") or {}).get("runId")},
        "analysisKey": key,
        "params": params,
        "lastError": last_error,
    }


def enqueue(song_ids: List[str], overwrite: bool = False, limit: Optional[int] = None) -> Dict[str, Any]:
    registry = load_registry()
    songs = [s for s in registry.get("songs", []) if s.get("localPath")]
    if song_ids:
        wanted = set(song_ids)
        songs = [s for s in songs if s.get("id") in wanted]
    if limit:
        songs = songs[:limit]
    state = load_queue()
    by_id = {j.get("id"): j for j in state.get("queue", [])}
    added = updated = 0
    for song in songs:
        job = make_job(song, overwrite=overwrite)
        if job["id"] in by_id:
            if overwrite and by_id[job["id"]].get("status") in {"completed", "skipped", "failed", "blocked"}:
                by_id[job["id"]].update(job)
                updated += 1
            continue
        state["queue"].append(job)
        added += 1
    save_queue(state)
    return {"added": added, "updated": updated, "queuePath": str(QUEUE_PATH), "telemetry": state.get("telemetry", {})}


def run_cmd(args: List[str], timeout: int = 60) -> Tuple[int, str, str]:
    try:
        proc = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
        return proc.returncode, proc.stdout, proc.stderr
    except FileNotFoundError as e:
        return 127, "", str(e)
    except subprocess.TimeoutExpired as e:
        return 124, e.stdout or "", e.stderr or "timeout"


def ffprobe(path: pathlib.Path) -> Tuple[Dict[str, Any], List[str]]:
    warnings: List[str] = []
    code, out, err = run_cmd(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)], timeout=45)
    if code != 0:
        warnings.append(f"ffprobe failed: {err.strip()[:240]}")
        return {}, warnings
    try:
        data = json.loads(out)
    except Exception as e:
        warnings.append(f"ffprobe json parse failed: {e}")
        return {}, warnings
    fmt = data.get("format") or {}
    audio_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), {})
    duration = float(fmt.get("duration") or audio_stream.get("duration") or 0) if (fmt.get("duration") or audio_stream.get("duration")) else None
    return {
        "formatName": fmt.get("format_name"),
        "formatLongName": fmt.get("format_long_name"),
        "duration": duration,
        "bitRate": int(fmt.get("bit_rate")) if str(fmt.get("bit_rate", "")).isdigit() else None,
        "codec": audio_stream.get("codec_name"),
        "sampleRate": int(audio_stream.get("sample_rate")) if str(audio_stream.get("sample_rate", "")).isdigit() else None,
        "channels": audio_stream.get("channels"),
    }, warnings


def decode_to_wav(path: pathlib.Path, sample_rate: int) -> Tuple[Optional[pathlib.Path], List[str]]:
    warnings: List[str] = []
    if not shutil.which("ffmpeg"):
        return None, ["ffmpeg not installed; waveform/beat analysis skipped"]
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="hapa_audio_telemetry_")) / "audio.wav"
    code, _out, err = run_cmd(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(path), "-ac", "1", "-ar", str(sample_rate), "-f", "wav", str(tmp)], timeout=180)
    if code != 0:
        warnings.append(f"ffmpeg decode failed: {err.strip()[:240]}")
        return None, warnings
    return tmp, warnings


def read_pcm_peaks(wav_path: pathlib.Path, sample_rate: int, window_ms: int) -> Tuple[Dict[str, Any], List[float], List[str]]:
    warnings: List[str] = []
    try:
        with contextlib.closing(wave.open(str(wav_path), "rb")) as wf:
            nframes = wf.getnframes()
            channels = wf.getnchannels()
            width = wf.getsampwidth()
            sr = wf.getframerate()
            raw = wf.readframes(nframes)
    except Exception as e:
        return {"duration": None, "sampleRate": sample_rate, "windowMs": window_ms, "peaks": []}, [], [f"wave read failed: {e}"]
    if width != 2:
        return {"duration": nframes / max(1, sample_rate), "sampleRate": sr, "windowMs": window_ms, "peaks": []}, [], [f"unsupported sample width {width}; expected 16-bit PCM"]
    import struct
    count = len(raw) // 2
    samples = struct.unpack("<" + "h" * count, raw)
    if channels > 1:
        samples = samples[::channels]
    vals = [s / 32768.0 for s in samples]
    win = max(1, int(sr * window_ms / 1000))
    peak_rows = []
    rms_curve = []
    for i in range(0, len(vals), win):
        seg = vals[i:i + win]
        if not seg:
            continue
        mn, mx = min(seg), max(seg)
        rms = math.sqrt(sum(x * x for x in seg) / len(seg))
        peak_rows.append([round(mn, 4), round(mx, 4), round(rms, 4)])
        rms_curve.append(rms)
    duration = len(vals) / max(1, sr)
    peak_abs = max((abs(x) for x in vals), default=0.0)
    peak_dbfs = 20 * math.log10(peak_abs) if peak_abs > 0 else None
    rms_mean = statistics.mean(rms_curve) if rms_curve else 0.0
    rms_peak = max(rms_curve) if rms_curve else 0.0
    return {
        "duration": duration,
        "sampleRate": sr,
        "channels": 1,
        "windowMs": window_ms,
        "windowSamples": win,
        "peakCount": len(peak_rows),
        "peaks": peak_rows,
        "rmsMean": round(rms_mean, 6),
        "rmsPeak": round(rms_peak, 6),
        "peakDbfs": round(peak_dbfs, 3) if peak_dbfs is not None else None,
    }, rms_curve, warnings


def estimate_bpm_and_beats(rms_curve: List[float], duration: float) -> Dict[str, Any]:
    if not rms_curve or duration <= 0:
        bpm = 120.0
        confidence = 0.1
    else:
        mean = statistics.mean(rms_curve)
        stdev = statistics.pstdev(rms_curve) or 1e-6
        peaks = []
        for i in range(1, len(rms_curve) - 1):
            if rms_curve[i] > rms_curve[i - 1] and rms_curve[i] >= rms_curve[i + 1] and rms_curve[i] > mean + 0.35 * stdev:
                t = (i / len(rms_curve)) * duration
                if not peaks or t - peaks[-1] > 0.18:
                    peaks.append(t)
        intervals = [b - a for a, b in zip(peaks, peaks[1:]) if 0.25 <= b - a <= 2.0]
        if intervals:
            median = statistics.median(intervals)
            bpm = 60.0 / median
            while bpm < 70:
                bpm *= 2
            while bpm > 180:
                bpm /= 2
            confidence = min(0.75, 0.25 + len(intervals) / 80)
        else:
            bpm = 120.0
            confidence = 0.15
    beat_interval = 60.0 / max(1.0, bpm)
    beat_times = [round(i * beat_interval, 3) for i in range(int(duration / beat_interval) + 1)] if duration else []
    bar_times = [round(t, 3) for idx, t in enumerate(beat_times) if idx % 4 == 0]
    return {"bpm": round(bpm, 2), "tempoConfidence": round(confidence, 3), "beatTimes": beat_times, "barTimes": bar_times}


def section_and_hook_events(song: Dict[str, Any], duration: float, rms_curve: List[float], rhythm: Dict[str, Any]) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    for idx, t in enumerate(rhythm.get("beatTimes", [])[:2000]):
        events.append({"id": stable_id(song.get("id"), "beat", idx, prefix="evt"), "type": "beat", "start": t, "end": t, "label": f"Beat {idx + 1}", "confidence": rhythm.get("tempoConfidence", 0.1), "source": "internal_rms_grid"})
    for idx, t in enumerate(rhythm.get("barTimes", [])[:600]):
        events.append({"id": stable_id(song.get("id"), "bar", idx, prefix="evt"), "type": "bar", "start": t, "end": t, "label": f"Bar {idx + 1}", "confidence": rhythm.get("tempoConfidence", 0.1), "source": "internal_rms_grid"})
    if duration > 0:
        names = ["intro", "body_a", "body_b", "finale"] if duration >= 60 else ["whole_song"]
        for idx, name in enumerate(names):
            start = duration * idx / len(names)
            end = duration * (idx + 1) / len(names)
            events.append({"id": stable_id(song.get("id"), "section", name, prefix="evt"), "type": "section", "start": round(start, 3), "end": round(end, 3), "label": name, "confidence": 0.35, "source": "duration_partition", "reasons": ["coarse baseline section heuristic"]})
        if rms_curve:
            win_count = len(rms_curve)
            third = max(1, win_count // 3)
            segments = [(i, min(win_count, i + third)) for i in range(0, win_count, third)]
            scored = []
            for i, (a, b) in enumerate(segments):
                energy = statistics.mean(rms_curve[a:b]) if b > a else 0
                start = duration * a / win_count
                end = duration * b / win_count
                scored.append((energy, i, start, end))
            for rank, (energy, i, start, end) in enumerate(sorted(scored, reverse=True)[:2]):
                confidence = min(0.65, 0.25 + energy * 3)
                events.append({"id": stable_id(song.get("id"), "hook", i, prefix="evt"), "type": "hook_candidate", "start": round(start, 3), "end": round(end, 3), "label": f"Hook candidate {rank + 1}", "score": round(confidence, 3), "confidence": round(confidence, 3), "source": "energy_baseline", "reasons": ["high relative RMS energy", "candidate only; not verified chorus"]})
    return events


def analyze_song(song: Dict[str, Any], job: Dict[str, Any]) -> Dict[str, Any]:
    source_path = pathlib.Path(song.get("localPath") or job.get("sourceAudio", {}).get("path") or "")
    created = utcnow()
    audio_hash = job.get("sourceAudio", {}).get("sha256") or job.get("sourceAudio", {}).get("sha256Head") or "nohash"
    run_id = f"atr_{created.replace('-', '').replace(':', '').replace('Z', 'Z')}_{audio_hash[:8]}_v{ANALYZER_VERSION.replace('.', '_')}"
    warnings: List[str] = []
    errors: List[str] = []
    ffmeta, w = ffprobe(source_path)
    warnings.extend(w)
    wav_path, w = decode_to_wav(source_path, int(job.get("params", {}).get("sampleRate") or DEFAULT_SAMPLE_RATE))
    warnings.extend(w)
    waveform = {"duration": ffmeta.get("duration") or song.get("duration"), "sampleRate": DEFAULT_SAMPLE_RATE, "windowMs": DEFAULT_PEAK_WINDOW_MS, "peaks": []}
    rms_curve: List[float] = []
    if wav_path:
        waveform, rms_curve, w = read_pcm_peaks(wav_path, DEFAULT_SAMPLE_RATE, int(job.get("params", {}).get("peakWindowMs") or DEFAULT_PEAK_WINDOW_MS))
        warnings.extend(w)
        with contextlib.suppress(Exception):
            shutil.rmtree(wav_path.parent)
    duration = float(waveform.get("duration") or ffmeta.get("duration") or song.get("duration") or 0)
    rhythm = estimate_bpm_and_beats(rms_curve, duration)
    events = section_and_hook_events(song, duration, rms_curve, rhythm)
    section_count = sum(1 for e in events if e.get("type") == "section")
    hook_count = sum(1 for e in events if e.get("type") == "hook_candidate")
    confidence = 0.2 + (0.25 if waveform.get("peaks") else 0) + min(0.35, rhythm.get("tempoConfidence", 0) * 0.35)
    summary = {
        "bpm": rhythm.get("bpm"),
        "tempoConfidence": rhythm.get("tempoConfidence"),
        "key": None,
        "keyConfidence": None,
        "loudnessIntegratedLufs": None,
        "rmsMean": waveform.get("rmsMean"),
        "rmsPeak": waveform.get("rmsPeak"),
        "peakDbfs": waveform.get("peakDbfs"),
        "dynamicRange": None,
        "vocalCoverage": None,
        "energyArc": "baseline_energy_sections" if rms_curve else "unknown",
        "hookCount": hook_count,
        "sectionCount": section_count,
        "beatCount": len(rhythm.get("beatTimes", [])),
        "barCount": len(rhythm.get("barTimes", [])),
    }
    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "hapa.audioTelemetry.run",
        "runId": run_id,
        "songId": song.get("id"),
        "title": song.get("title"),
        "createdAt": created,
        "updatedAt": created,
        "duration": duration,
        "status": "complete" if not errors else "partial",
        "confidence": round(min(0.95, confidence), 3),
        "summary": summary,
        "waveform": {k: v for k, v in waveform.items() if k != "peaks"},
        "rhythm": {"bpm": rhythm.get("bpm"), "tempoConfidence": rhythm.get("tempoConfidence"), "beatCount": len(rhythm.get("beatTimes", [])), "barCount": len(rhythm.get("barTimes", []))},
        "timeline": {"timebase": "seconds", "events": events},
        "features": {"rmsCurveWindowMs": job.get("params", {}).get("peakWindowMs", DEFAULT_PEAK_WINDOW_MS), "rmsCurve": [round(x, 6) for x in rms_curve[:5000]]},
        "assets": {},
        "provenance": {"analyzer": ANALYZER, "analyzerVersion": ANALYZER_VERSION, "params": job.get("params", {}), "analysisKey": job.get("analysisKey"), "sourceAudio": job.get("sourceAudio", {}), "ffprobe": ffmeta},
        "warnings": warnings,
        "errors": errors,
        "dense": {"peaks": waveform.get("peaks", [])[:10000], "beatTimes": rhythm.get("beatTimes", [])[:5000], "barTimes": rhythm.get("barTimes", [])[:1500]},
    }


def commit_run(run: Dict[str, Any], job: Dict[str, Any]) -> Dict[str, Any]:
    ensure_layout()
    song_id = run["songId"]
    run_id = run["runId"]
    run_dir = TELEMETRY_ROOT / "runs" / song_id
    run_path = run_dir / f"{run_id}.json"
    latest_path = TELEMETRY_ROOT / "latest" / f"{song_id}.json"
    manifest_path = TELEMETRY_ROOT / "manifests" / f"{song_id}.json"
    write_json(run_path, run)
    write_json(latest_path, run)
    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "hapa.audioTelemetry.manifest",
        "songId": song_id,
        "title": run.get("title"),
        "runId": run_id,
        "status": run.get("status"),
        "confidence": run.get("confidence"),
        "createdAt": run.get("createdAt"),
        "updatedAt": utcnow(),
        "analysisKey": job.get("analysisKey"),
        "summary": run.get("summary", {}),
        "runPath": str(run_path),
        "latestPath": str(latest_path),
        "timelineEventCount": len((run.get("timeline") or {}).get("events") or []),
        "warnings": run.get("warnings", []),
    }
    write_json(manifest_path, manifest)
    update_sqlite_for_runs([run], DB_PATH)
    export_jsonl()
    return manifest


def update_sqlite_for_runs(runs: Iterable[Dict[str, Any]], db_path: pathlib.Path = DB_PATH) -> None:
    if not db_path.exists():
        return
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.executescript("""
    create table if not exists audio_telemetry_runs(song_id text primary key, run_id text, status text, confidence real, created_at text, updated_at text, duration real, bpm real, tempo_confidence real, hook_count integer, section_count integer, beat_count integer, bar_count integer, summary_json text, manifest_path text, run_path text, warnings_json text, provenance_json text);
    create table if not exists audio_telemetry_events(song_id text, run_id text, event_id text, event_type text, label text, start real, end real, confidence real, score real, source text, reasons_json text, metadata_json text, primary key(song_id, run_id, event_id));
    create table if not exists audio_telemetry_queue_jobs(id text primary key, song_id text, title text, status text, priority integer, attempts integer, updated_at text, analysis_key text, last_error text, source_json text);
    create index if not exists idx_audio_telemetry_events_type on audio_telemetry_events(event_type);
    create index if not exists idx_audio_telemetry_events_song_type on audio_telemetry_events(song_id, event_type);
    """)
    for run in runs:
        song_id = run.get("songId")
        run_id = run.get("runId")
        summary = run.get("summary") or {}
        manifest_path = str(TELEMETRY_ROOT / "manifests" / f"{song_id}.json")
        run_path = str(TELEMETRY_ROOT / "runs" / str(song_id) / f"{run_id}.json")
        cur.execute("delete from audio_telemetry_runs where song_id=?", (song_id,))
        cur.execute("insert into audio_telemetry_runs values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            song_id, run_id, run.get("status"), run.get("confidence"), run.get("createdAt"), run.get("updatedAt"), run.get("duration"), summary.get("bpm"), summary.get("tempoConfidence"), summary.get("hookCount"), summary.get("sectionCount"), summary.get("beatCount"), summary.get("barCount"), json.dumps(summary, ensure_ascii=False), manifest_path, run_path, json.dumps(run.get("warnings", []), ensure_ascii=False), json.dumps(run.get("provenance", {}), ensure_ascii=False)
        ))
        cur.execute("delete from audio_telemetry_events where song_id=?", (song_id,))
        for ev in (run.get("timeline") or {}).get("events", []):
            cur.execute("insert or replace into audio_telemetry_events values(?,?,?,?,?,?,?,?,?,?,?,?)", (
                song_id, run_id, ev.get("id") or stable_id(song_id, ev.get("type"), ev.get("start"), prefix="evt"), ev.get("type"), ev.get("label"), ev.get("start"), ev.get("end"), ev.get("confidence"), ev.get("score"), ev.get("source"), json.dumps(ev.get("reasons", []), ensure_ascii=False), json.dumps(ev, ensure_ascii=False)
            ))
    con.commit(); con.close()


def update_sqlite_queue(state: Dict[str, Any], db_path: pathlib.Path = DB_PATH) -> None:
    if not db_path.exists():
        return
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute("create table if not exists audio_telemetry_queue_jobs(id text primary key, song_id text, title text, status text, priority integer, attempts integer, updated_at text, analysis_key text, last_error text, source_json text)")
    for job in state.get("queue", []):
        cur.execute("insert or replace into audio_telemetry_queue_jobs values(?,?,?,?,?,?,?,?,?,?)", (job.get("id"), job.get("songId"), job.get("title"), job.get("status"), job.get("priority"), job.get("attempts"), job.get("updatedAt"), job.get("analysisKey"), job.get("lastError"), json.dumps(job.get("sourceAudio", {}), ensure_ascii=False)))
    con.commit(); con.close()


def worker(limit: int = 1) -> Dict[str, Any]:
    registry = load_registry()
    songs_by_id = {s.get("id"): s for s in registry.get("songs", [])}
    state = load_queue()
    completed = failed = blocked = skipped = 0
    jobs = sorted([j for j in state.get("queue", []) if j.get("status") == "queued"], key=lambda j: (-int(j.get("priority", 50)), j.get("createdAt", "")))
    for job in jobs[:limit]:
        song = songs_by_id.get(job.get("songId"))
        if not song:
            job.update({"status": "blocked", "lastError": "song not found in registry", "updatedAt": utcnow()}); blocked += 1; continue
        if latest_matches(song.get("id"), job.get("analysisKey")):
            job.update({"status": "skipped", "updatedAt": utcnow()}); skipped += 1; continue
        if not pathlib.Path(song.get("localPath") or "").exists():
            job.update({"status": "blocked", "lastError": "source audio missing", "updatedAt": utcnow()}); blocked += 1; continue
        try:
            job.update({"status": "running", "attempts": int(job.get("attempts", 0)) + 1, "updatedAt": utcnow()}); save_queue(state)
            run = analyze_song(song, job)
            job["status"] = "writing"; job["updatedAt"] = utcnow(); save_queue(state)
            manifest = commit_run(run, job)
            job.update({"status": "completed", "updatedAt": utcnow(), "runId": manifest.get("runId"), "manifestPath": manifest.get("runPath"), "lastError": None})
            completed += 1
        except Exception as e:
            attempts = int(job.get("attempts", 1))
            job.update({"status": "failed" if attempts >= int(job.get("maxAttempts", 3)) else "queued", "updatedAt": utcnow(), "lastError": str(e)})
            failed += 1
    save_queue(state)
    update_sqlite_queue(state)
    return {"completed": completed, "failed": failed, "blocked": blocked, "skipped": skipped, "telemetry": state.get("telemetry", {})}


def show(song_id: Optional[str] = None) -> Dict[str, Any]:
    state = load_queue()
    if song_id:
        return {"manifest": manifest_for(song_id), "latest": read_json(TELEMETRY_ROOT / "latest" / f"{song_id}.json", None), "jobs": [j for j in state.get("queue", []) if j.get("songId") == song_id]}
    return {"queuePath": str(QUEUE_PATH), "telemetry": state.get("telemetry", {}), "recent": state.get("queue", [])[-10:]}


def export_jsonl() -> Dict[str, str]:
    ensure_layout()
    hooks = []
    sections = []
    high = []
    for latest in sorted((TELEMETRY_ROOT / "latest").glob("*.json")):
        run = read_json(latest, {})
        for ev in (run.get("timeline") or {}).get("events", []):
            row = {"songId": run.get("songId"), "title": run.get("title"), "runId": run.get("runId"), **ev}
            if ev.get("type") == "hook_candidate":
                hooks.append(row)
            if ev.get("type") == "section":
                sections.append(row)
            if float(ev.get("confidence") or 0) >= 0.55:
                high.append(row)
    outputs = {"hooks": TELEMETRY_ROOT / "exports" / "hooks.jsonl", "sections": TELEMETRY_ROOT / "exports" / "sections.jsonl", "highConfidenceEvents": TELEMETRY_ROOT / "exports" / "high_confidence_events.jsonl"}
    for rows, path in [(hooks, outputs["hooks"]), (sections, outputs["sections"]), (high, outputs["highConfidenceEvents"] )]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return {k: str(v) for k, v in outputs.items()}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Hapa audio telemetry queue/analyzer")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("enqueue"); p.add_argument("--song", action="append", default=[]); p.add_argument("--limit", type=int); p.add_argument("--overwrite", action="store_true")
    p = sub.add_parser("worker"); p.add_argument("--limit", type=int, default=1)
    p = sub.add_parser("show"); p.add_argument("song_id", nargs="?")
    sub.add_parser("export")
    p = sub.add_parser("analyze"); p.add_argument("song_id"); p.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    if args.cmd == "enqueue":
        result = enqueue(args.song, overwrite=args.overwrite, limit=args.limit)
    elif args.cmd == "worker":
        result = worker(limit=args.limit)
    elif args.cmd == "show":
        result = show(args.song_id)
    elif args.cmd == "export":
        result = export_jsonl()
    elif args.cmd == "analyze":
        enq = enqueue([args.song_id], overwrite=args.overwrite, limit=1)
        wrk = worker(limit=1)
        result = {"enqueue": enq, "worker": wrk, "show": show(args.song_id)}
    else:
        raise AssertionError(args.cmd)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
