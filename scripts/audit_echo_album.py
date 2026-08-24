#!/usr/bin/env python3
"""Read-only completeness audit for an exported Suno Echo Album playlist.

Process boundary: this script spawns no child processes, uses one worker, performs
no retries, and only writes when --json-out or --markdown-out is supplied.
"""

import argparse
import json
import pathlib
from collections import Counter
from datetime import datetime, timezone


MIN_AUDIO_BYTES = 1024
MIN_TIMING_CONFIDENCE = 0.60


def read_json(path, fallback=None):
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except Exception:
        return fallback


def audio_kind(path):
    path = pathlib.Path(path)
    try:
        if path.stat().st_size < MIN_AUDIO_BYTES:
            return None
        with path.open("rb") as handle:
            head = handle.read(1024 * 1024)
    except OSError:
        return None
    if head.startswith(b"RIFF") and head[8:12] == b"WAVE":
        return "wav"
    if mp3_frame_count(head) >= 3:
        return "mp3"
    if len(head) >= 12 and head[4:8] == b"ftyp":
        return "mp4-audio"
    if head.startswith(b"OggS"):
        return "ogg"
    if head.startswith(b"fLaC"):
        return "flac"
    return None


def mp3_frame_count(data):
    """Require multiple plausible MPEG audio frames, not an ID3 label alone."""
    count = 0
    for index in range(max(0, len(data) - 3)):
        b0, b1, b2 = data[index], data[index + 1], data[index + 2]
        if b0 != 0xFF or b1 & 0xE0 != 0xE0:
            continue
        version = (b1 >> 3) & 0x03
        layer = (b1 >> 1) & 0x03
        bitrate_index = (b2 >> 4) & 0x0F
        sample_rate_index = (b2 >> 2) & 0x03
        if version == 1 or layer == 0 or bitrate_index in (0, 15) or sample_rate_index == 3:
            continue
        count += 1
        if count >= 3:
            return count
    return count


def first_valid(local_dir, names, expected=None):
    for name in names:
        candidate = pathlib.Path(local_dir) / name
        kind = audio_kind(candidate)
        if kind and (expected is None or kind == expected):
            return candidate
    return None


def is_instrumental(metadata):
    nested = metadata.get("metadata") if isinstance(metadata.get("metadata"), dict) else {}
    return metadata.get("make_instrumental") is True or nested.get("make_instrumental") is True


def timing_gate(doc, source_path):
    reasons = []
    if not isinstance(doc, dict):
        return False, ["missing-or-invalid-json"]
    method = str(doc.get("method") or "").lower()
    if "synthetic" in method or "fallback" in method or "weighted_even" in method:
        reasons.append("synthetic-method")
    if not doc.get("analyzedAt"):
        reasons.append("missing-analyzed-at")
    try:
        confidence = float(doc.get("confidence"))
    except (TypeError, ValueError):
        confidence = -1
    if confidence < MIN_TIMING_CONFIDENCE:
        reasons.append("confidence-below-0.60")
    lines = doc.get("lines") if isinstance(doc.get("lines"), list) else []
    if not lines:
        reasons.append("no-timed-lines")
    prior_end = -1.0
    starts = set()
    for line in lines:
        try:
            start = float(line.get("start"))
            end = float(line.get("end"))
        except (AttributeError, TypeError, ValueError):
            reasons.append("invalid-line-interval")
            break
        if start < 0 or end <= start:
            reasons.append("invalid-line-interval")
            break
        rounded = round(start, 4)
        if rounded in starts:
            reasons.append("duplicate-line-start")
            break
        starts.add(rounded)
        if start < prior_end - 0.001:
            reasons.append("overlapping-lines")
            break
        prior_end = end
    provenance = doc.get("provenance") if isinstance(doc.get("provenance"), dict) else {}
    if not provenance.get("audioSha256") or not provenance.get("lyricsSha256"):
        reasons.append("missing-audio-or-lyrics-hash")
    stt_candidates = [
        pathlib.Path(str(source_path).replace(".json", ".stt.json")),
        pathlib.Path(source_path).with_name("lyric-timing.stt.json"),
    ]
    if not any(path.is_file() for path in stt_candidates):
        reasons.append("missing-stt-sidecar")
    return not reasons, sorted(set(reasons))


def timing_candidates(song, local_dir, playlist_root, registry_song):
    values = [
        song.get("lyricTimingPath"),
        playlist_root / "lyric_timings" / f"{song.get('id')}.json",
        local_dir / "lyric-timing.json",
    ]
    timing = (registry_song or {}).get("lyricTiming")
    if isinstance(timing, dict):
        source = timing.get("sourcePath") or ""
        if source:
            values.append(source)
    seen = set()
    for value in values:
        if not value:
            continue
        path = pathlib.Path(value)
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        if path.is_file():
            yield path


def project_index(builder_root):
    index = set()
    if not builder_root:
        return index
    for path in (pathlib.Path(builder_root) / "data" / "music-video-projects").glob("*.json"):
        doc = read_json(path, {})
        project = doc.get("music_video_project") if isinstance(doc.get("music_video_project"), dict) else doc
        for value in (
            doc.get("song_id"),
            project.get("song_id"),
            project.get("audio_id"),
            project.get("registry_track_id"),
            (doc.get("song_edit_map") or {}).get("source_song_id"),
            (doc.get("song_edit_map") or {}).get("registry_track_id"),
            (project.get("song_edit_map") or {}).get("source_song_id"),
            (project.get("song_edit_map") or {}).get("registry_track_id"),
        ):
            if value:
                index.add(str(value))
        index.add(path.stem)
        for value in (doc.get("source_clip_id"), doc.get("suno_id")):
            if value:
                index.add(str(value))
        if "director_show_graph" in doc or "directorShowGraph" in doc:
            index.add(f"modern:{path.stem}")
    return index


def has_director(song_id, projects):
    return song_id in projects


def audit(manifest_path, registry_path=None, builder_root=None):
    manifest_path = pathlib.Path(manifest_path)
    manifest = read_json(manifest_path)
    if not isinstance(manifest, dict) or not isinstance(manifest.get("songs"), list):
        raise ValueError(f"Invalid playlist manifest: {manifest_path}")
    playlist_root = manifest_path.parent
    registry = read_json(registry_path, {}) if registry_path else {}
    registry_by_id = {row.get("id"): row for row in registry.get("songs", []) if isinstance(row, dict)}
    projects = project_index(builder_root)
    rows = []
    for song in manifest["songs"]:
        song_id = str(song.get("id") or "")
        local_dir = pathlib.Path(song.get("localDir") or "")
        metadata = read_json(song.get("metadataPath") or local_dir / "metadata.json", {}) or {}
        instrumental = is_instrumental(metadata)
        mp3 = first_valid(local_dir, ["song.mp3"], "mp3")
        wav = first_valid(local_dir, ["song.wav"], "wav")
        declared_master = pathlib.Path(song.get("songPath") or "")
        declared_kind = audio_kind(declared_master)
        manifest_path_current = bool(declared_kind and declared_master in {mp3, wav})
        lyrics_path = pathlib.Path(song.get("lyricsPath") or local_dir / "lyrics.txt")
        try:
            lyric_text = lyrics_path.read_text(encoding="utf-8").strip()
        except OSError:
            lyric_text = ""
        expected_stems = song.get("stems") if isinstance(song.get("stems"), list) else []
        valid_stems = []
        invalid_stems = []
        for stem in expected_stems:
            path = pathlib.Path(stem.get("localPath") or "")
            if audio_kind(path):
                valid_stems.append(str(path))
            else:
                invalid_stems.append(str(path))
        stem_source_available = bool(song.get("hasStem") or expected_stems or song.get("discoveredStemCount"))
        stems_complete = bool(expected_stems) and len(valid_stems) == len(expected_stems)
        registry_song = registry_by_id.get(song_id, {})
        timing_path = None
        timing_reasons = ["missing"]
        for candidate in timing_candidates(song, local_dir, playlist_root, registry_song):
            ok, reasons = timing_gate(read_json(candidate), candidate)
            if ok:
                timing_path = candidate
                timing_reasons = []
                break
            if timing_path is None:
                timing_reasons = reasons
        telemetry = registry_song.get("audioTelemetry") if isinstance(registry_song, dict) else None
        telemetry_ok = isinstance(telemetry, dict) and telemetry.get("status") == "complete" and bool(telemetry.get("latestRunId"))
        lyrics_required = not instrumental
        director_project_present = has_director(song_id, projects) if builder_root else None
        protocol_complete = None
        if builder_root:
            protocol_complete = bool(
                director_project_present and mp3 and wav
                and (stems_complete or not stem_source_available)
                and (lyric_text or instrumental)
                and (timing_path or instrumental)
                and telemetry_ok
            )
        rows.append({
            "id": song_id,
            "title": song.get("title") or "Untitled",
            "localDir": str(local_dir),
            "mp3": bool(mp3),
            "mp3Path": str(mp3 or ""),
            "wav": bool(wav),
            "wavPath": str(wav or ""),
            "declaredMasterPath": str(declared_master),
            "declaredMasterKind": declared_kind,
            "manifestPathCurrent": manifest_path_current,
            "stemSourceAvailable": stem_source_available,
            "stemsExpected": len(expected_stems),
            "stemsValid": len(valid_stems),
            "stemsComplete": stems_complete,
            "invalidStemPaths": invalid_stems,
            "instrumental": instrumental,
            "lyricsRequired": lyrics_required,
            "lyrics": bool(lyric_text) if lyrics_required else True,
            "lyricsActual": bool(lyric_text),
            "lyricsPath": str(lyrics_path),
            "actualTiming": bool(timing_path) if lyrics_required else True,
            "actualTimingPath": str(timing_path or ""),
            "timingFailureReasons": timing_reasons if lyrics_required else [],
            "stemAnalysis": telemetry_ok,
            "directorProjectPresent": director_project_present,
            "directorScript": protocol_complete,
        })
    summary = {
        "songs": len(rows),
        "mp3Complete": sum(row["mp3"] for row in rows),
        "mp3Missing": sum(not row["mp3"] for row in rows),
        "wavComplete": sum(row["wav"] for row in rows),
        "wavMissing": sum(not row["wav"] for row in rows),
        "manifestPathsCurrent": sum(row["manifestPathCurrent"] for row in rows),
        "manifestPathsStaleOrInvalid": sum(not row["manifestPathCurrent"] for row in rows),
        "stemSourceAvailable": sum(row["stemSourceAvailable"] for row in rows),
        "stemsComplete": sum(row["stemsComplete"] for row in rows),
        "stemsIncompleteWhereAvailable": sum(row["stemSourceAvailable"] and not row["stemsComplete"] for row in rows),
        "stemsUnavailableAtSource": sum(not row["stemSourceAvailable"] for row in rows),
        "instrumentals": sum(row["instrumental"] for row in rows),
        "lyricsSourcePresent": sum(row["lyricsActual"] for row in rows),
        "lyricsSourceMissing": sum(not row["lyricsActual"] for row in rows),
        "lyricsComplete": sum(row["lyrics"] for row in rows),
        "lyricsMissingRequired": sum(row["lyricsRequired"] and not row["lyrics"] for row in rows),
        "actualTimingComplete": sum(row["actualTiming"] for row in rows),
        "actualTimingMeasured": sum(row["lyricsRequired"] and row["actualTiming"] for row in rows),
        "timingNotRequiredInstrumental": sum(not row["lyricsRequired"] for row in rows),
        "actualTimingMissingRequired": sum(row["lyricsRequired"] and not row["actualTiming"] for row in rows),
        "stemAnalysisComplete": sum(row["stemAnalysis"] for row in rows),
    }
    if builder_root:
        summary["directorProjectsPresent"] = sum(row["directorProjectPresent"] for row in rows)
        summary["directorScriptsComplete"] = sum(row["directorScript"] for row in rows)
        summary["directorScriptsMissing"] = sum(not row["directorScript"] for row in rows)
    return {
        "schemaVersion": "hapa.echo-album.library-audit.v1",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "manifestPath": str(manifest_path),
        "registryPath": str(registry_path or ""),
        "summary": summary,
        "timingGate": {"minimumConfidence": MIN_TIMING_CONFIDENCE, "syntheticTimingAccepted": False},
        "songs": rows,
    }


def markdown(report):
    summary = report["summary"]
    lines = [
        "# Echo Album library inventory",
        "",
        f"Generated: `{report['generatedAt']}`",
        "",
        "This is a read-only, manifest-scoped audit. A path only counts when its bytes and evidence pass the stated gate.",
        "",
        "## Counts",
        "",
    ]
    for key, value in summary.items():
        lines.append(f"- `{key}`: **{value}**")
    lines.extend(["", "## Healing queues", ""])
    queues = [
        ("Missing/invalid MP3", lambda row: not row["mp3"]),
        ("Missing/invalid WAV", lambda row: not row["wav"]),
        ("Stale/invalid declared master path", lambda row: not row["manifestPathCurrent"]),
        ("Incomplete stems where Suno exposes stems", lambda row: row["stemSourceAvailable"] and not row["stemsComplete"]),
        ("Required lyrics missing", lambda row: row["lyricsRequired"] and not row["lyrics"]),
        ("Required actual timing missing or rejected", lambda row: row["lyricsRequired"] and not row["actualTiming"]),
        ("Stem/audio analysis missing", lambda row: not row["stemAnalysis"]),
    ]
    if "directorScriptsMissing" in summary:
        queues.append(("Director script not complete under the six-gate protocol", lambda row: not row["directorScript"]))
    for title, predicate in queues:
        matches = [row for row in report["songs"] if predicate(row)]
        lines.extend([f"### {title} ({len(matches)})", ""])
        if not matches:
            lines.append("- None")
        else:
            for row in matches:
                suffix = ""
                if title.startswith("Required actual") and row["timingFailureReasons"]:
                    suffix = f" — {', '.join(row['timingFailureReasons'])}"
                lines.append(f"- {row['title']} (`{row['id']}`){suffix}")
        lines.append("")
    lines.extend([
        "## Healing order",
        "",
        "1. Reconcile the signed-in Suno playlist and freeze the exact manifest song IDs.",
        "2. Fetch MP3 and WAV independently; validate container bytes and decodability before promotion.",
        "3. Fetch the latest complete stem family where Suno exposes stems; report source-unavailable separately.",
        "4. Persist non-empty lyrics (or a source-declared instrumental classification).",
        "5. Run stem/audio telemetry and STT lyric alignment; promote only actual, hashed, non-overlapping timings.",
        "6. Generate and preflight director scripts only after gates 1–5 are satisfied; leave explicit blocked receipts otherwise.",
        "",
        "## Measured healing plan",
        "",
        "- **Wave 0 — manifest truth:** repair stale declared paths by exact song ID and rerun this byte-level audit. Never count a declared path without validating its current bytes.",
        f"- **Wave 1 — lossless custody:** obtain and validate the {summary['wavMissing']} missing WAV masters through the signed-in Suno download surface in bounded, resumable batches.",
        f"- **Wave 2 — analysis:** produce actual timing for {summary['actualTimingMissingRequired']} vocal songs and complete audio/stem telemetry for {summary['songs'] - summary['stemAnalysisComplete']} songs. Preserve the {summary['stemsUnavailableAtSource']} source-unavailable stem cases as explicit states; the {summary['stemsComplete']} source-available stem families already pass.",
        f"- **Wave 3 — Director:** regenerate/preflight only exact IDs whose prior gates now pass. Today {summary.get('directorScriptsComplete', 0)} pass the full protocol and {summary.get('directorScriptsMissing', summary['songs'])} remain blocked by one or more upstream gates.",
        "- **Checkpoint each batch:** persist exact IDs, hashes, validation results, failed gate/retryability, and a fresh audit diff. Resume at the first invalid gate rather than rebuilding the whole registry.",
    ])
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--registry")
    parser.add_argument("--builder-root")
    parser.add_argument("--json-out")
    parser.add_argument("--markdown-out")
    args = parser.parse_args()
    report = audit(args.manifest, args.registry, args.builder_root)
    if args.json_out:
        pathlib.Path(args.json_out).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.markdown_out:
        pathlib.Path(args.markdown_out).write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
