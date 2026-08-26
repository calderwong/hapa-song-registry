import importlib.util
import json
import pathlib
import tempfile
import unittest


MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "update_registry_song.py"
SPEC = importlib.util.spec_from_file_location("update_registry_song", MODULE_PATH)
UPDATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(UPDATE)


class UpdateRegistrySongTest(unittest.TestCase):
    def test_dry_run_drops_locally_discovered_timing_that_fails_strict_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            project = root / "project"
            data = project / "data"
            data.mkdir(parents=True)
            registry_path = data / "registry.json"
            registry_path.write_text(json.dumps({
                "songs": [], "stems": [], "externalLyrics": [], "lyricMasters": [],
                "promptGroups": [], "groups": [], "similarities": [], "counts": {},
            }), encoding="utf-8")
            playlist = root / "library" / "playlists" / "echo"
            song_dir = playlist / "songs" / "1 - One - abc"
            song_dir.mkdir(parents=True)
            audio = song_dir / "song.mp3"
            lyrics = song_dir / "lyrics.txt"
            audio.write_bytes(b"ID3" + (b"\xff\xfb\x90\x64" + b"\0" * 413) * 5)
            lyrics.write_text("hello world\n", encoding="utf-8")
            metadata_path = song_dir / "metadata.json"
            metadata_path.write_text(json.dumps({
                "id": "abc", "status": "complete", "title": "One",
                "audio_url": "https://example.invalid/abc.mp3",
                "metadata": {"prompt": "hello", "duration": 10},
            }), encoding="utf-8")
            (song_dir / "lyric-timing.json").write_text(json.dumps({
                "songId": "abc", "method": "stt_lyric_align", "engine": "whisper-cli",
                "analyzedAt": "now", "confidence": .2,
                "lines": [{"start": 0, "end": 1}],
                "provenance": {
                    "audioPath": str(audio), "audioSha256": "bad",
                    "lyricsPath": str(lyrics), "lyricsSha256": "bad",
                },
            }), encoding="utf-8")
            (song_dir / "lyric-timing.stt.json").write_text("{}", encoding="utf-8")
            manifest_path = playlist / "manifest.hapa-avatar-builder.json"
            manifest_path.write_text(json.dumps({"songs": [{
                "id": "abc", "title": "One", "localDir": str(song_dir),
                "metadataPath": str(metadata_path), "songPath": str(audio),
            }]}), encoding="utf-8")
            receipt = UPDATE.apply_update(
                manifest_path, "abc", project, registry_path, data / "hapa_registry.sqlite", apply=False,
            )
            self.assertFalse(receipt["lyricTiming"])

    def test_batch_dry_run_rebuilds_derived_state_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            project = root / "project"
            data = project / "data"
            data.mkdir(parents=True)
            registry_path = data / "registry.json"
            registry_path.write_text(json.dumps({
                "songs": [], "stems": [], "externalLyrics": [], "lyricMasters": [],
                "promptGroups": [], "groups": [], "similarities": [], "counts": {},
            }), encoding="utf-8")
            playlist = root / "library" / "playlists" / "echo"
            rows = []
            for index, song_id in enumerate(("abc", "def"), 1):
                song_dir = playlist / "songs" / f"{index} - Song - {song_id}"
                song_dir.mkdir(parents=True)
                (song_dir / "song.mp3").write_bytes(b"ID3" + (b"\xff\xfb\x90\x64" + b"\0" * 413) * 5)
                metadata_path = song_dir / "metadata.json"
                metadata_path.write_text(json.dumps({
                    "id": song_id, "status": "complete", "title": song_id,
                    "audio_url": f"https://example.invalid/{song_id}.mp3",
                    "metadata": {"prompt": song_id, "duration": 10},
                }), encoding="utf-8")
                rows.append({
                    "id": song_id, "title": song_id, "localDir": str(song_dir),
                    "metadataPath": str(metadata_path), "songPath": str(song_dir / "song.mp3"),
                })
            manifest_path = playlist / "manifest.hapa-avatar-builder.json"
            manifest_path.write_text(json.dumps({"songs": rows}), encoding="utf-8")
            receipt = UPDATE.apply_updates(
                manifest_path, ["abc", "def"], project, registry_path,
                data / "hapa_registry.sqlite", apply=False,
            )
            self.assertEqual(receipt["songCount"], 2)
            self.assertEqual(receipt["songIds"], ["abc", "def"])
            self.assertEqual({row["songId"] for row in receipt["rows"]}, {"abc", "def"})

    def test_dry_run_normalizes_only_requested_song(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            project = root / "project"
            data = project / "data"
            data.mkdir(parents=True)
            registry_path = data / "registry.json"
            registry_path.write_text(json.dumps({
                "songs": [], "stems": [], "externalLyrics": [], "lyricMasters": [],
                "promptGroups": [], "groups": [], "similarities": [], "counts": {},
            }), encoding="utf-8")
            playlist = root / "library" / "playlists" / "echo"
            song_dir = playlist / "songs" / "1 - One - abc"
            song_dir.mkdir(parents=True)
            (song_dir / "song.mp3").write_bytes(b"ID3" + (b"\xff\xfb\x90\x64" + b"\0" * 413) * 5)
            metadata = {
                "id": "abc", "status": "complete", "title": "One", "created_at": "2026-01-01T00:00:00Z",
                "audio_url": "https://example.invalid/abc.mp3", "metadata": {"prompt": "hello", "duration": 10},
            }
            metadata_path = song_dir / "metadata.json"
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
            manifest_path = playlist / "manifest.hapa-avatar-builder.json"
            manifest_path.write_text(json.dumps({"songs": [{
                "id": "abc", "title": "One", "localDir": str(song_dir),
                "metadataPath": str(metadata_path), "songPath": str(song_dir / "song.mp3"),
            }]}), encoding="utf-8")
            receipt = UPDATE.apply_update(
                manifest_path, "abc", project, registry_path, data / "hapa_registry.sqlite", apply=False,
            )
            self.assertEqual(receipt["songId"], "abc")
            self.assertEqual(receipt["title"], "One")
            self.assertEqual(receipt["mode"], "dry-run")
            self.assertTrue(receipt["localPath"].endswith("song.mp3"))

    def test_apply_upserts_song_without_rebuilding_database_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            project = root / "project"
            data = project / "data"
            data.mkdir(parents=True)
            playlist = root / "library" / "playlists" / "echo"
            song_dir = playlist / "songs" / "1 - One - abc"
            song_dir.mkdir(parents=True)
            (song_dir / "song.mp3").write_bytes(b"ID3" + (b"\xff\xfb\x90\x64" + b"\0" * 413) * 5)
            metadata_path = song_dir / "metadata.json"
            metadata_path.write_text(json.dumps({
                "id": "abc", "status": "complete", "title": "Updated One", "created_at": "2026-01-01T00:00:00Z",
                "audio_url": "https://example.invalid/abc.mp3", "metadata": {"prompt": "hello", "duration": 10},
            }), encoding="utf-8")
            manifest_path = playlist / "manifest.hapa-avatar-builder.json"
            manifest_path.write_text(json.dumps({"songs": [{
                "id": "abc", "title": "Updated One", "localDir": str(song_dir),
                "metadataPath": str(metadata_path), "songPath": str(song_dir / "song.mp3"),
            }]}), encoding="utf-8")
            telemetry_dir = data / "audio_telemetry" / "manifests"
            telemetry_dir.mkdir(parents=True)
            (telemetry_dir / "abc.json").write_text(json.dumps({
                "status": "complete", "runId": "run-abc", "summary": {"bpm": 120},
                "confidence": 0.9, "updatedAt": "2026-01-01T00:01:00Z",
            }), encoding="utf-8")
            base = UPDATE.rebuild_derived({
                "songs": [], "stems": [], "externalLyrics": [], "lyricMasters": [],
                "promptGroups": [], "groups": [], "similarities": [], "counts": {},
            })
            registry_path = data / "registry.json"
            registry_path.write_text(json.dumps(base), encoding="utf-8")
            db_path = data / "hapa_registry.sqlite"
            UPDATE.ingest.write_sqlite(base, db_path)
            receipt = UPDATE.apply_update(manifest_path, "abc", project, registry_path, db_path, apply=True)
            self.assertEqual(receipt["mode"], "apply")
            saved = json.loads(registry_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["songs"][0]["title"], "Updated One")
            import sqlite3
            con = sqlite3.connect(db_path)
            try:
                self.assertEqual(con.execute("select title from songs where id='abc'").fetchone()[0], "Updated One")
                self.assertEqual(con.execute("select run_id from audio_telemetry_runs where song_id='abc'").fetchone()[0], "run-abc")
            finally:
                con.close()


if __name__ == "__main__":
    unittest.main()
