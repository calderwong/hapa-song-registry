"""Runs the peer music owner test (test/peer-music.test.js) under the Python test runner."""
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PeerMusicTest(unittest.TestCase):
    def test_peer_music_owner(self):
        r = subprocess.run(["node", "test/peer-music.test.js"], cwd=ROOT, capture_output=True, text=True, timeout=180)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("peer-music: all passed", r.stdout)


if __name__ == "__main__":
    unittest.main()
