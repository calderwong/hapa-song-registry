#!/usr/bin/env python3
"""Incrementally upsert one exported playlist song into Registry JSON + SQLite.

This is the fast path for an existing or newly exported song. It scans one song
directory, rewrites the monolithic compatibility JSON once, and updates only the
song/stem rows plus small derived tables in SQLite. It spawns no subprocesses,
has concurrency 1, and performs no retries.
"""

import argparse
import json
import pathlib
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import audit_echo_album as audit_lib
import ingest_suno as ingest


def load_json(path):
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def exact_manifest_song(manifest_path, song_id):
    manifest = load_json(manifest_path)
    matches = [row for row in manifest.get("songs", []) if str(row.get("id")) == str(song_id)]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one manifest row for {song_id}; found {len(matches)}")
    return manifest, matches[0]


def valid_master(song_dir, declared_path=None):
    candidates = [song_dir / "song.mp3", song_dir / "song.wav"]
    if declared_path:
        candidates.append(pathlib.Path(declared_path))
    for path in candidates:
        if audit_lib.audio_kind(path):
            return path
    raise ValueError(f"No valid master audio container in {song_dir}")


def build_target(manifest_path, song_id, project_root):
    manifest_path = pathlib.Path(manifest_path)
    _, row = exact_manifest_song(manifest_path, song_id)
    song_dir = pathlib.Path(row.get("localDir") or "")
    metadata_path = pathlib.Path(row.get("metadataPath") or song_dir / "metadata.json")
    clip = load_json(metadata_path)
    if str(clip.get("id")) != str(song_id):
        raise ValueError(f"Metadata ID mismatch for {song_id}: {clip.get('id')}")
    master = valid_master(song_dir, row.get("songPath"))
    clip = ingest.with_export_fields(clip, song_dir, master, "song")
    clips = [clip, *ingest.discover_playlist_export_stems(song_dir, clip)]
    library_root = manifest_path.parents[2]
    songs, stems = ingest.normalize_clips(clips, library_root)
    songs = [song for song in songs if str(song.get("id")) == str(song_id)]
    stems = [stem for stem in stems if str(stem.get("parentId")) == str(song_id)]
    if len(songs) != 1:
        raise ValueError(f"Normalization did not produce one song for {song_id}")
    song = songs[0]
    registry_stub = {}
    timing_paths = list(audit_lib.timing_candidates(row, song_dir, manifest_path.parent, registry_stub))
    project_timing = pathlib.Path(project_root) / "data" / "lyric_timings" / f"{song_id}.json"
    if project_timing.is_file() and project_timing not in timing_paths:
        timing_paths.append(project_timing)
    for path in timing_paths:
        timing = ingest.read_json_file(path)
        ok, _ = audit_lib.timing_gate(timing, path)
        if ok:
            timing.setdefault("sourcePath", str(path))
            song["lyricTiming"] = timing
            break
    ingest.load_existing_audio_telemetry(project_root, [song])
    return song, stems, library_root


def rebuild_derived(registry):
    songs = registry.get("songs", [])
    stems = registry.get("stems", [])
    for row in [*songs, *stems]:
        row.pop("lyricMasterId", None)
        row.pop("promptGroupId", None)
    external = registry.get("externalLyrics", [])
    lyric_masters = ingest.build_lyric_masters(songs, stems, external)
    prompt_groups = ingest.build_prompt_groups(songs, lyric_masters)
    stems_by_parent = defaultdict(list)
    for stem in stems:
        stems_by_parent[stem.get("parentId")].append(stem)
    groups = ingest.build_groups(songs, stems_by_parent)
    similarities = ingest.build_similarities(songs)
    registry.update({
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "lyricMasters": lyric_masters,
        "promptGroups": prompt_groups,
        "groups": groups,
        "similarities": similarities,
        "facets": ingest.facet_summary(songs),
    })
    registry["counts"] = {
        "songs": len(songs),
        "stems": len(stems),
        "groups": len(groups),
        "similarities": len(similarities),
        "externalLyrics": len(external),
        "lyricMasters": len(lyric_masters),
        "promptGroups": len(prompt_groups),
        "mashups": sum(1 for song in songs if song.get("isMashup")),
        "supplementalSongs": sum(1 for song in songs if song.get("raw", {}).get("_hapaSupplementalImport")),
        "lyricTimings": sum(1 for song in songs if song.get("lyricTiming")),
        "audioTelemetry": sum(1 for song in songs if song.get("audioTelemetry")),
    }
    return registry


def merge_target(registry, song, stems):
    song_id = song["id"]
    registry["songs"] = [row for row in registry.get("songs", []) if row.get("id") != song_id] + [song]
    registry["songs"].sort(key=lambda row: (row.get("createdAt") or "", row.get("id") or ""))
    registry["stems"] = [row for row in registry.get("stems", []) if row.get("parentId") != song_id] + stems
    registry["stems"].sort(key=lambda row: (row.get("parentId") or "", row.get("stemType") or "", row.get("id") or ""))
    return rebuild_derived(registry)


def insert_song(cur, song, generated_at):
    values = (
        song["id"], song.get("title"), song.get("createdAt"), song.get("duration"), song.get("model"),
        song.get("majorModelVersion"), song.get("localPath"), song.get("audioUrl"), song.get("imageUrl"),
        song.get("prompt"), song.get("lyrics"), song.get("tags"), song.get("lyricsFingerprint"),
        song.get("lyricMasterId"), song.get("promptGroupId"), song.get("stylePrompt"),
        song.get("stylePromptFingerprint"), song.get("contentType"), 1 if song.get("isMashup") else 0,
        json.dumps(song.get("mashupSourceIds", []), ensure_ascii=False), song.get("stemCount", 0),
        json.dumps(song.get("authors", []), ensure_ascii=False), json.dumps(song.get("raw", {}), ensure_ascii=False),
    )
    cur.execute("insert or replace into songs values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", values)
    author_ids = {name: ingest.stable_id("author", name) for name in song.get("authors", ingest.DEFAULT_AUTHORS)}
    for author, author_id in author_ids.items():
        cur.execute("insert or ignore into authors values(?,?)", (author_id, author))
        cur.execute("insert or ignore into song_authors values(?,?,?)", (song["id"], author_id, "author"))
    cur.execute("insert or replace into events values(?,?,?,?,?,?)", (
        ingest.stable_id("event", "song", song["id"], "created"), "song", song["id"], "created",
        song.get("createdAt") or generated_at, json.dumps({"title": song.get("title")}, ensure_ascii=False),
    ))
    if song.get("isMashup"):
        cur.execute("insert or replace into mashups values(?,?,?,?)", (
            song["id"], song.get("contentType"), json.dumps(song.get("mashupSourceIds", []), ensure_ascii=False),
            json.dumps({"title": song.get("title"), "stylePrompt": song.get("stylePrompt")}, ensure_ascii=False),
        ))
    timing = song.get("lyricTiming")
    if timing:
        cur.execute("insert or replace into lyric_timing_runs values(?,?,?,?,?,?,?,?,?)", (
            song["id"], timing.get("version"), timing.get("method"), timing.get("source"), timing.get("sourcePath"),
            timing.get("analyzedAt"), timing.get("confidence"), json.dumps(timing.get("warnings", []), ensure_ascii=False),
            json.dumps(timing.get("stats", {}), ensure_ascii=False),
        ))
        for line in timing.get("lines", []):
            cur.execute("insert or replace into lyric_lines values(?,?,?,?,?,?,?,?,?)", (
                song["id"], line.get("index"), line.get("sectionIndex"), line.get("section"), line.get("text"),
                line.get("start"), line.get("end"), line.get("timestamp"), line.get("confidence"),
            ))
        for section in timing.get("sections", []):
            cur.execute("insert or replace into lyric_sections values(?,?,?,?,?,?,?,?,?)", (
                song["id"], section.get("index"), section.get("label"), section.get("start"), section.get("end"),
                section.get("timestamp"), section.get("lineStart"), section.get("lineEnd"), section.get("confidence"),
            ))
    telemetry = song.get("audioTelemetry")
    if telemetry:
        summary = telemetry.get("summary") or {}
        cur.execute("insert or replace into audio_telemetry_runs values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            song["id"], telemetry.get("latestRunId"), telemetry.get("status"), telemetry.get("confidence"), None,
            telemetry.get("updatedAt"), song.get("duration"), summary.get("bpm"), summary.get("tempoConfidence"),
            summary.get("hookCount"), summary.get("sectionCount"), summary.get("beatCount"), summary.get("barCount"),
            json.dumps(summary, ensure_ascii=False), telemetry.get("manifestPath"),
            telemetry.get("runPath") or telemetry.get("timelinePath"),
            json.dumps(telemetry.get("warnings", []), ensure_ascii=False),
            json.dumps({"source": "registry_manifest"}, ensure_ascii=False),
        ))
        latest_path = telemetry.get("timelinePath") or telemetry.get("runPath")
        run_doc = ingest.read_json_file(latest_path, {}) if latest_path else {}
        for event in (run_doc.get("timeline") or {}).get("events", []):
            cur.execute("insert or replace into audio_telemetry_events values(?,?,?,?,?,?,?,?,?,?,?,?)", (
                song["id"], telemetry.get("latestRunId"),
                event.get("id") or ingest.stable_id("audioevt", song["id"], event.get("type"), event.get("start")),
                event.get("type"), event.get("label"), event.get("start"), event.get("end"), event.get("confidence"),
                event.get("score"), event.get("source"), json.dumps(event.get("reasons", []), ensure_ascii=False),
                json.dumps(event, ensure_ascii=False),
            ))
    for kind, values in song.get("facets", {}).items():
        for value in values:
            cur.execute("insert into facets values(?,?,?)", (song["id"], kind, value))


def insert_stem(cur, stem, generated_at):
    cur.execute("insert or replace into stems values(?,?,?,?,?,?,?,?,?,?,?,?)", (
        stem["id"], stem.get("parentId"), stem.get("stemType"), stem.get("title"), stem.get("duration"), stem.get("model"),
        stem.get("localPath"), stem.get("audioUrl"), stem.get("lyricsFingerprint"), stem.get("lyricMasterId"),
        json.dumps(stem.get("authors", []), ensure_ascii=False), json.dumps(stem.get("raw", {}), ensure_ascii=False),
    ))
    for author in stem.get("authors", ingest.DEFAULT_AUTHORS):
        author_id = ingest.stable_id("author", author)
        cur.execute("insert or ignore into authors values(?,?)", (author_id, author))
        cur.execute("insert or ignore into stem_authors values(?,?,?)", (stem["id"], author_id, "author"))
    cur.execute("insert or replace into events values(?,?,?,?,?,?)", (
        ingest.stable_id("event", "stem", stem["id"], "created"), "stem", stem["id"], "created",
        stem.get("createdAt") or generated_at, json.dumps({"title": stem.get("title"), "parentId": stem.get("parentId")}, ensure_ascii=False),
    ))
    cur.execute("insert or replace into derivatives values(?,?,?,?,?,?,?,?)", (
        ingest.stable_id("derivative", stem.get("parentId"), stem["id"]), "song", stem.get("parentId"), "stem", stem["id"],
        stem.get("stemType") or "stem", generated_at, json.dumps({}, ensure_ascii=False),
    ))


def update_sqlite(db_path, registry, song_id):
    db_path = pathlib.Path(db_path)
    if not db_path.is_file():
        raise ValueError(f"Registry SQLite does not exist; bootstrap once with ingest_suno.py: {db_path}")
    song = next(row for row in registry["songs"] if row.get("id") == song_id)
    stems = [row for row in registry["stems"] if row.get("parentId") == song_id]
    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()
        old_stem_ids = [row[0] for row in cur.execute("select id from stems where parent_id=?", (song_id,)).fetchall()]
        subject_ids = [song_id, *old_stem_ids]
        cur.execute("begin immediate")
        cur.execute("delete from song_authors where song_id=?", (song_id,))
        cur.execute("delete from mashups where song_id=?", (song_id,))
        cur.execute("delete from lyric_lines where song_id=?", (song_id,))
        cur.execute("delete from lyric_sections where song_id=?", (song_id,))
        cur.execute("delete from lyric_timing_runs where song_id=?", (song_id,))
        cur.execute("delete from audio_telemetry_events where song_id=?", (song_id,))
        cur.execute("delete from audio_telemetry_runs where song_id=?", (song_id,))
        cur.execute("delete from facets where song_id=?", (song_id,))
        for stem_id in old_stem_ids:
            cur.execute("delete from stem_authors where stem_id=?", (stem_id,))
        if old_stem_ids:
            placeholders = ",".join("?" for _ in old_stem_ids)
            cur.execute(
                f"delete from derivatives where parent_id=? or child_id in ({placeholders})",
                (song_id, *old_stem_ids),
            )
        else:
            cur.execute("delete from derivatives where parent_id=?", (song_id,))
        cur.execute("delete from stems where parent_id=?", (song_id,))
        for subject_id in subject_ids:
            cur.execute("delete from events where subject_id=?", (subject_id,))
        insert_song(cur, song, registry.get("generatedAt"))
        for stem in stems:
            insert_stem(cur, stem, registry.get("generatedAt"))
        for table in ("lyric_variations", "lyric_masters", "prompt_groups", "groups", "similarities"):
            cur.execute(f"delete from {table}")
        for master in registry.get("lyricMasters", []):
            cur.execute("insert into lyric_masters values(?,?,?,?,?,?)", (
                master["id"], master.get("lyricsFingerprint"), master.get("sourceTitle"), master.get("lyrics"),
                json.dumps(master.get("authors", []), ensure_ascii=False), master.get("variationCount", 0),
            ))
            for value in master.get("variations", []):
                cur.execute("insert into lyric_variations values(?,?,?,?,?,?,?)", (
                    master["id"], value.get("kind"), value.get("id"), value.get("title"), value.get("parentId"),
                    value.get("path"), json.dumps(value, ensure_ascii=False),
                ))
        for group in registry.get("promptGroups", []):
            cur.execute("insert into prompt_groups values(?,?,?,?,?,?,?,?,?)", (
                group["id"], group.get("lyricMasterId"), group.get("stylePromptFingerprint"), group.get("stylePrompt"),
                group.get("songCount", 0), json.dumps(group.get("facets", {}), ensure_ascii=False),
                json.dumps(group.get("contentTypes", []), ensure_ascii=False), group.get("mashupCount", 0),
                json.dumps(group.get("songIds", []), ensure_ascii=False),
            ))
        for group in registry.get("groups", []):
            cur.execute("insert into groups values(?,?,?,?,?)", (group["id"], group["kind"], group["key"], group["count"], json.dumps(group["songIds"])))
        for similarity in registry.get("similarities", []):
            cur.execute("insert into similarities values(?,?,?,?)", (similarity["songA"], similarity["songB"], similarity["score"], similarity["reason"]))
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def apply_update(manifest_path, song_id, project_root, registry_path, sqlite_path, apply=False):
    song, stems, library_root = build_target(manifest_path, song_id, project_root)
    registry_path = pathlib.Path(registry_path)
    registry = merge_target(load_json(registry_path), song, stems)
    registry["sourceLibrary"] = str(library_root)
    receipt = {
        "songId": song_id,
        "title": song.get("title"),
        "localPath": song.get("localPath"),
        "stemCount": len(stems),
        "lyricTiming": bool(song.get("lyricTiming")),
        "audioTelemetry": bool(song.get("audioTelemetry")),
        "mode": "apply" if apply else "dry-run",
    }
    if not apply:
        return receipt
    temp_path = registry_path.with_suffix(registry_path.suffix + ".song-update.tmp")
    temp_path.write_text(json.dumps(registry, ensure_ascii=False), encoding="utf-8")
    try:
        update_sqlite(sqlite_path, registry, song_id)
        temp_path.replace(registry_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return receipt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--song-id", required=True)
    parser.add_argument("--project", default=str(ingest.DEFAULT_PROJECT))
    parser.add_argument("--registry")
    parser.add_argument("--sqlite")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    project = pathlib.Path(args.project)
    receipt = apply_update(
        args.manifest, args.song_id, project,
        args.registry or project / "data" / "registry.json",
        args.sqlite or project / "data" / "hapa_registry.sqlite",
        apply=args.apply,
    )
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
