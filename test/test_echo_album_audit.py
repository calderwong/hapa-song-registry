import importlib.util
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
            (timing_dir / "abc.json").write_text(json.dumps({
                "method": "stt_lyric_align", "analyzedAt": "now", "confidence": .8,
                "lines": [{"start": 0, "end": 1}],
                "provenance": {"audioSha256": "a", "lyricsSha256": "b"},
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


if __name__ == "__main__":
    unittest.main()
