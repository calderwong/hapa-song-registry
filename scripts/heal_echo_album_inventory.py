#!/usr/bin/env python3
"""Heal one Echo Album manifest from verified exact-ID assets already on disk.

The command is dry-run by default. It spawns no child processes, uses one worker,
performs no retries, and mutates only with --apply. WAVs are accepted only when
their bytes are RIFF/WAVE and an adjacent metadata.json identifies the exact Suno
song ID. Timing pairs must pass the measured timing gate and match the current
audio and lyrics SHA-256 hashes before promotion.
"""

import argparse
import hashlib
import json
import os
import pathlib
import shutil
import sys
from datetime import datetime, timezone

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import audit_echo_album as audit_lib


def read_json(path, fallback=None):
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except Exception:
        return fallback


def sha256_file(path):
    digest = hashlib.sha256()
    with pathlib.Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_copy(source, destination):
    source = pathlib.Path(source)
    destination = pathlib.Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".inventory-heal.tmp")
    if temporary.exists():
        temporary.unlink()
    try:
        os.link(source, temporary)
    except OSError:
        shutil.copy2(source, temporary)
    temporary.replace(destination)


def backup_existing(path, backup_root, label):
    path = pathlib.Path(path)
    if not path.exists():
        return None
    destination = pathlib.Path(backup_root) / label / path.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    counter = 1
    while destination.exists():
        destination = destination.with_name(f"{destination.stem}-{counter}{destination.suffix}")
        counter += 1
    shutil.copy2(path, destination)
    return str(destination)


def metadata_id(path):
    doc = read_json(path, {}) or {}
    nested = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}
    return str(doc.get("id") or nested.get("id") or "")


def wav_inventory(roots, wanted_ids):
    found = {song_id: [] for song_id in wanted_ids}
    for root in roots:
        root = pathlib.Path(root)
        if not root.exists():
            continue
        for metadata_path in root.rglob("metadata.json"):
            song_id = metadata_id(metadata_path)
            if song_id not in found:
                continue
            candidate = metadata_path.parent / "song.wav"
            if audit_lib.audio_kind(candidate) == "wav":
                found[song_id].append(candidate)
    for candidates in found.values():
        candidates.sort(key=lambda path: (-path.stat().st_size, str(path)))
    return found


def timing_inventory(roots, wanted_ids):
    found = {song_id: [] for song_id in wanted_ids}
    ignored = {"manifest.json", "timing-run-progress.json"}
    for root in roots:
        root = pathlib.Path(root)
        if not root.exists():
            continue
        for timing_path in root.rglob("*.json"):
            if timing_path.name.endswith(".stt.json") or timing_path.name in ignored:
                continue
            doc = read_json(timing_path)
            if not isinstance(doc, dict):
                continue
            song_id = str(doc.get("songId") or timing_path.stem)
            if song_id not in found:
                continue
            stt_path = timing_path.with_name(timing_path.name.replace(".json", ".stt.json"))
            accepted, reasons = audit_lib.timing_gate(doc, timing_path, song_id)
            found[song_id].append({
                "path": timing_path,
                "sttPath": stt_path,
                "doc": doc,
                "accepted": accepted,
                "reasons": reasons,
            })
    return found


def current_hashes(song):
    local_dir = pathlib.Path(song.get("localDir") or "")
    audio = audit_lib.first_valid(local_dir, ["song.mp3", "song.wav"])
    lyrics = pathlib.Path(song.get("lyricsPath") or local_dir / "lyrics.txt")
    return {
        "audioPath": audio,
        "audioSha256": sha256_file(audio) if audio else None,
        "lyricsPath": lyrics if lyrics.is_file() else None,
        "lyricsSha256": audit_lib.sha256_lyrics_text(lyrics) if lyrics.is_file() else None,
    }


def verified_timing_candidates(entries, hashes):
    verified = []
    for entry in entries:
        reasons = list(entry["reasons"])
        provenance = entry["doc"].get("provenance") if isinstance(entry["doc"].get("provenance"), dict) else {}
        if provenance.get("audioSha256") != hashes.get("audioSha256"):
            reasons.append("audio-hash-does-not-match-current-song")
        if provenance.get("lyricsSha256") != hashes.get("lyricsSha256"):
            reasons.append("lyrics-hash-does-not-match-current-song")
        if not entry["sttPath"].is_file():
            reasons.append("missing-stt-sidecar")
        entry = {**entry, "accepted": not reasons, "reasons": sorted(set(reasons))}
        if entry["accepted"]:
            verified.append(entry)
    verified.sort(key=lambda row: (
        -float(row["doc"].get("confidence") or 0),
        str(row["path"]),
    ))
    return verified


def heal(manifest_path, wav_roots, timing_roots, apply=False):
    manifest_path = pathlib.Path(manifest_path)
    manifest = read_json(manifest_path)
    if not isinstance(manifest, dict) or not isinstance(manifest.get("songs"), list):
        raise ValueError(f"Invalid manifest: {manifest_path}")
    songs = manifest["songs"]
    wanted_ids = {str(song.get("id")) for song in songs}
    wavs = wav_inventory(wav_roots, wanted_ids)
    timings = timing_inventory(timing_roots, wanted_ids)
    destination_timing_root = manifest_path.parent / "lyric_timings"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = manifest_path.parent / "backups" / f"inventory-heal-{timestamp}"
    rows = []
    for song in songs:
        song_id = str(song.get("id"))
        local_dir = pathlib.Path(song.get("localDir") or "")
        current_wav = local_dir / "song.wav"
        wav_ok = audit_lib.audio_kind(current_wav) == "wav"
        wav_source = next((path for path in wavs[song_id] if path != current_wav), None)
        wav_action = "already-complete" if wav_ok else "copy" if wav_source else "blocked-no-exact-id-wav"
        destination_timing = destination_timing_root / f"{song_id}.json"
        destination_stt = destination_timing_root / f"{song_id}.stt.json"
        existing_timing_ok, existing_timing_reasons = audit_lib.timing_gate(
            read_json(destination_timing), destination_timing, song_id
        )
        hashes = current_hashes(song)
        candidates = verified_timing_candidates(timings[song_id], hashes)
        selected_timing = candidates[0] if candidates else None
        timing_action = (
            "not-required-instrumental" if audit_lib.is_instrumental(read_json(song.get("metadataPath") or local_dir / "metadata.json", {}) or {})
            else "already-complete" if existing_timing_ok
            else "copy" if selected_timing
            else "blocked-no-current-hash-measured-timing"
        )
        backups = []
        if apply and wav_action == "copy":
            backup = backup_existing(current_wav, backup_root, f"{song_id}/wav")
            if backup:
                backups.append(backup)
            atomic_copy(wav_source, current_wav)
        if apply and timing_action == "copy":
            for destination in (destination_timing, destination_stt):
                backup = backup_existing(destination, backup_root, f"{song_id}/timing")
                if backup:
                    backups.append(backup)
            atomic_copy(selected_timing["path"], destination_timing)
            atomic_copy(selected_timing["sttPath"], destination_stt)
        rows.append({
            "songId": song_id,
            "title": song.get("title") or "Untitled",
            "wav": {
                "action": wav_action,
                "source": str(wav_source or ""),
                "destination": str(current_wav),
            },
            "timing": {
                "action": timing_action,
                "source": str(selected_timing["path"] if selected_timing else ""),
                "destination": str(destination_timing),
                "existingFailureReasons": existing_timing_reasons if not existing_timing_ok else [],
                "candidateCount": len(timings[song_id]),
                "verifiedCandidateCount": len(candidates),
            },
            "backups": backups,
        })
    return {
        "schemaVersion": "hapa.echo-album.inventory-heal.v1",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "mode": "apply" if apply else "dry-run",
        "manifestPath": str(manifest_path),
        "summary": {
            "songs": len(rows),
            "wavAlreadyComplete": sum(row["wav"]["action"] == "already-complete" for row in rows),
            "wavEligible": sum(row["wav"]["action"] == "copy" for row in rows),
            "wavBlocked": sum(row["wav"]["action"].startswith("blocked") for row in rows),
            "timingAlreadyComplete": sum(row["timing"]["action"] == "already-complete" for row in rows),
            "timingEligible": sum(row["timing"]["action"] == "copy" for row in rows),
            "timingBlocked": sum(row["timing"]["action"].startswith("blocked") for row in rows),
            "timingNotRequired": sum(row["timing"]["action"] == "not-required-instrumental" for row in rows),
        },
        "rows": rows,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--wav-root", action="append", default=[])
    parser.add_argument("--timing-root", action="append", default=[])
    parser.add_argument("--json-out")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    manifest_path = pathlib.Path(args.manifest)
    report = heal(
        manifest_path,
        args.wav_root or [manifest_path.parent / "songs"],
        args.timing_root or [manifest_path.parent / "lyric_timings"],
        apply=args.apply,
    )
    if args.json_out:
        output = pathlib.Path(args.json_out)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
