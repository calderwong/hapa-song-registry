import importlib.util
import hashlib
import json
import pathlib
import tempfile
import unittest


MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "audit_echo_album.py"
SPEC = importlib.util.spec_from_file_location("audit_echo_album", MODULE_PATH)
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


def mp3_bytes():
    return b"ID3" + (b"\xff\xfb\x90\x64" + b"\0" * 413) * 5


class EchoAlbumAuditTest(unittest.TestCase):
    def test_rejects_opaque_payload_and_synthetic_timing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            song_dir = root / "songs" / "1 - Test - abc"
            song_dir.mkdir(parents=True)
            (song_dir / "song.mp3").write_bytes(b"opaque" * 300)
            (song_dir / "lyrics.txt").write_text("hello world\n", encoding="utf-8")
            (song_dir / "metadata.json").write_text(json.dumps({"id": "abc", "metadata": {}}), encoding="utf-8")
            timing_dir = root / "lyric_timings"
            timing_dir.mkdir()
            (timing_dir / "abc.json").write_text(json.dumps({
                "method": "weighted_even_fallback", "analyzedAt": "now", "confidence": 1,
                "lines": [{"start": 0, "end": 1}],
                "provenance": {"audioSha256": "a", "lyricsSha256": "b"},
            }), encoding="utf-8")
            (timing_dir / "abc.stt.json").write_text("{}", encoding="utf-8")
            manifest = {"songs": [{"id": "abc", "title": "Test", "localDir": str(song_dir), "metadataPath": str(song_dir / "metadata.json"), "stems": []}]}
            manifest_path = root / "manifest.hapa-avatar-builder.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            report = AUDIT.audit(manifest_path)
            row = report["songs"][0]
            self.assertFalse(row["mp3"])
            self.assertFalse(row["actualTiming"])
            self.assertIn("synthetic-method", row["timingFailureReasons"])

    def test_accepts_valid_assets_and_actual_timing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            song_dir = root / "songs" / "1 - Test - abc"
            stems = song_dir / "stems"
            stems.mkdir(parents=True)
            (song_dir / "song.mp3").write_bytes(mp3_bytes())
            (song_dir / "song.wav").write_bytes(b"RIFF" + (2048).to_bytes(4, "little") + b"WAVE" + b"\0" * 2048)
            (stems / "vocals.mp3").write_bytes(mp3_bytes())
            (song_dir / "lyrics.txt").write_text("hello world\n", encoding="utf-8")
            (song_dir / "metadata.json").write_text(json.dumps({"id": "abc", "metadata": {}}), encoding="utf-8")
            timing_dir = root / "lyric_timings"
            timing_dir.mkdir()
            audio_hash = hashlib.sha256((stems / "vocals.mp3").read_bytes()).hexdigest()
            lyrics_hash = hashlib.sha256((song_dir / "lyrics.txt").read_text(encoding="utf-8").strip().encode("utf-8")).hexdigest()
            (timing_dir / "abc.json").write_text(json.dumps({
                "songId": "abc",
                "method": "stt_lyric_align", "engine": "whisper-cli", "analyzedAt": "now", "confidence": .8,
                "lines": [{"start": 0, "end": 1}],
                "provenance": {
                    "audioPath": str(stems / "vocals.mp3"), "audioSha256": audio_hash,
                    "lyricsPath": str(song_dir / "lyrics.txt"), "lyricsSha256": lyrics_hash,
                },
            }), encoding="utf-8")
            (timing_dir / "abc.stt.json").write_text("{}", encoding="utf-8")
            manifest = {"songs": [{
                "id": "abc", "title": "Test", "localDir": str(song_dir),
                "metadataPath": str(song_dir / "metadata.json"),
                "stems": [{"localPath": str(stems / "vocals.mp3")}], "hasStem": True,
            }]}
            manifest_path = root / "manifest.hapa-avatar-builder.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            report = AUDIT.audit(manifest_path)
            row = report["songs"][0]
            self.assertTrue(row["mp3"])
            self.assertTrue(row["wav"])
            self.assertTrue(row["stemsComplete"])
            self.assertTrue(row["actualTiming"])

    def test_rejects_stale_timing_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            audio = root / "audio.mp3"
            lyrics = root / "lyrics.txt"
            timing = root / "abc.json"
            audio.write_bytes(mp3_bytes())
            lyrics.write_text("hello world\n", encoding="utf-8")
            timing.write_text(json.dumps({
                "songId": "abc", "method": "stt_lyric_align", "engine": "whisper-cli",
                "analyzedAt": "now", "confidence": .8,
                "lines": [{"start": 0, "end": 1}],
                "provenance": {
                    "audioPath": str(audio), "audioSha256": "stale",
                    "lyricsPath": str(lyrics), "lyricsSha256": hashlib.sha256(lyrics.read_text(encoding="utf-8").strip().encode("utf-8")).hexdigest(),
                },
            }), encoding="utf-8")
            (root / "abc.stt.json").write_text("{}", encoding="utf-8")
            accepted, reasons = AUDIT.timing_gate(json.loads(timing.read_text()), timing, "abc")
            self.assertFalse(accepted)
            self.assertIn("stale-audio-hash", reasons)

    def test_rejects_non_measured_timing_engine(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            timing = root / "abc.json"
            timing.write_text(json.dumps({
                "method": "audio_phrase_weighted", "analyzedAt": "now", "confidence": .9,
                "lines": [{"start": 0, "end": 1}],
                "provenance": {
                    "audioPath": "/audio.mp3", "audioSha256": "a",
                    "lyricsPath": "/lyrics.txt", "lyricsSha256": "b",
                    "timingSource": "energy-heuristic",
                },
            }), encoding="utf-8")
            (root / "abc.stt.json").write_text("{}", encoding="utf-8")
            accepted, reasons = AUDIT.timing_gate(json.loads(timing.read_text()), timing)
            self.assertFalse(accepted)
            self.assertIn("non-measured-engine", reasons)

    def test_rejects_timing_lines_past_audio_duration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            audio = root / "audio.mp3"
            lyrics = root / "lyrics.txt"
            timing = root / "abc.json"
            audio.write_bytes(mp3_bytes())
            lyrics.write_text("hello world\n", encoding="utf-8")
            timing.write_text(json.dumps({
                "songId": "abc", "method": "stt_lyric_align", "engine": "whisper-cli",
                "analyzedAt": "now", "confidence": .8, "duration": 10,
                "lines": [{"start": 9.5, "end": 10.5}],
                "provenance": {
                    "audioPath": str(audio), "audioSha256": hashlib.sha256(audio.read_bytes()).hexdigest(),
                    "lyricsPath": str(lyrics), "lyricsSha256": hashlib.sha256(lyrics.read_text(encoding="utf-8").strip().encode("utf-8")).hexdigest(),
                },
            }), encoding="utf-8")
            (root / "abc.stt.json").write_text("{}", encoding="utf-8")
            accepted, reasons = AUDIT.timing_gate(json.loads(timing.read_text()), timing, "abc")
            self.assertFalse(accepted)
            self.assertIn("invalid-line-interval", reasons)


if __name__ == "__main__":
    unittest.main()
