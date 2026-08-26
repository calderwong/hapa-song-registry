import hashlib
import importlib.util
import json
import pathlib
import tempfile
import unittest


MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "heal_echo_album_inventory.py"
SPEC = importlib.util.spec_from_file_location("heal_echo_album_inventory", MODULE_PATH)
HEAL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HEAL)


def mp3_bytes():
    return b"ID3" + (b"\xff\xfb\x90\x64" + b"\0" * 413) * 5


def wav_bytes():
    return b"RIFF" + (2048).to_bytes(4, "little") + b"WAVE" + b"\0" * 2048


class HealEchoAlbumInventoryTest(unittest.TestCase):
    def test_exact_id_wav_and_current_hash_timing_are_promoted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            current = root / "songs" / "2 - Current - abc"
            old = root / "songs" / "1 - Old - abc"
            archive = root / "archive"
            current.mkdir(parents=True)
            old.mkdir(parents=True)
            archive.mkdir()
            audio = mp3_bytes()
            lyrics = b"hello world\n"
            (current / "song.mp3").write_bytes(audio)
            (current / "lyrics.txt").write_bytes(lyrics)
            (current / "metadata.json").write_text(json.dumps({"id": "abc"}), encoding="utf-8")
            (old / "metadata.json").write_text(json.dumps({"id": "abc"}), encoding="utf-8")
            (old / "song.wav").write_bytes(wav_bytes())
            timing = {
                "songId": "abc", "method": "stt_lyric_align", "engine": "whisper-cli",
                "analyzedAt": "now", "confidence": .8,
                "lines": [{"start": 0, "end": 1, "words": [{"start": 0, "end": .5}]}],
                "provenance": {
                    "audioPath": str(current / "song.mp3"),
                    "audioSha256": hashlib.sha256(audio).hexdigest(),
                    "lyricsPath": str(current / "lyrics.txt"),
                    "lyricsSha256": hashlib.sha256(lyrics.decode("utf-8").strip().encode("utf-8")).hexdigest(),
                },
            }
            (archive / "abc.json").write_text(json.dumps(timing), encoding="utf-8")
            (archive / "abc.stt.json").write_text("{}", encoding="utf-8")
            manifest = {"songs": [{
                "id": "abc", "title": "Current", "localDir": str(current),
                "metadataPath": str(current / "metadata.json"),
                "lyricsPath": str(current / "lyrics.txt"),
            }]}
            manifest_path = root / "manifest.hapa-avatar-builder.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            report = HEAL.heal(manifest_path, [root / "songs"], [archive], apply=True)
            self.assertEqual(report["summary"]["wavEligible"], 1)
            self.assertEqual(report["summary"]["timingEligible"], 1)
            self.assertEqual((current / "song.wav").read_bytes(), wav_bytes())
            self.assertTrue((root / "lyric_timings" / "abc.json").is_file())

    def test_stale_timing_hash_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            current = root / "songs" / "1 - Current - abc"
            archive = root / "archive"
            current.mkdir(parents=True)
            archive.mkdir()
            (current / "song.mp3").write_bytes(mp3_bytes())
            (current / "lyrics.txt").write_text("hello\n", encoding="utf-8")
            (current / "metadata.json").write_text(json.dumps({"id": "abc"}), encoding="utf-8")
            timing = {
                "songId": "abc", "method": "stt_lyric_align", "engine": "whisper-cli",
                "analyzedAt": "now", "confidence": .8, "lines": [{"start": 0, "end": 1}],
                "provenance": {
                    "audioPath": "/old.mp3", "audioSha256": "stale",
                    "lyricsPath": "/old.txt", "lyricsSha256": "stale",
                },
            }
            (archive / "abc.json").write_text(json.dumps(timing), encoding="utf-8")
            (archive / "abc.stt.json").write_text("{}", encoding="utf-8")
            manifest_path = root / "manifest.hapa-avatar-builder.json"
            manifest_path.write_text(json.dumps({"songs": [{
                "id": "abc", "title": "Current", "localDir": str(current),
                "metadataPath": str(current / "metadata.json"),
                "lyricsPath": str(current / "lyrics.txt"),
            }]}), encoding="utf-8")
            report = HEAL.heal(manifest_path, [root / "songs"], [archive], apply=False)
            self.assertEqual(report["summary"]["timingEligible"], 0)
            self.assertEqual(report["summary"]["timingBlocked"], 1)


if __name__ == "__main__":
    unittest.main()
