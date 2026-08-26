import importlib.util
import json
import pathlib
import sqlite3
import tempfile
import unittest
import wave
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('audio_telemetry', ROOT / 'scripts' / 'audio_telemetry.py')
audio_telemetry = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audio_telemetry)
INGEST_SPEC = importlib.util.spec_from_file_location('ingest_suno', ROOT / 'scripts' / 'ingest_suno.py')
ingest = importlib.util.module_from_spec(INGEST_SPEC)
INGEST_SPEC.loader.exec_module(ingest)


class AudioTelemetryTest(unittest.TestCase):
    def test_pcm_peak_reader_streams_windows_without_loading_entire_file(self):
        with tempfile.TemporaryDirectory() as d:
            wav_path = pathlib.Path(d) / 'sample.wav'
            with wave.open(str(wav_path), 'wb') as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(1000)
                handle.writeframes((b'\x00\x20' * 1000))
            waveform, curve, warnings = audio_telemetry.read_pcm_peaks(wav_path, 1000, 50)
            self.assertEqual(warnings, [])
            self.assertEqual(waveform['peakCount'], 20)
            self.assertEqual(len(curve), 20)
            self.assertAlmostEqual(waveform['duration'], 1.0)

    def test_enqueue_builds_durable_queue_with_analysis_key_and_blocked_missing_audio(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            data = root / 'data'
            data.mkdir()
            registry = {
                'generatedAt': '2026-01-01T00:00:00Z',
                'counts': {'songs': 2},
                'songs': [
                    {'id': 'song-ok', 'title': 'OK', 'localPath': str(root / 'ok.mp3'), 'duration': 1},
                    {'id': 'song-missing', 'title': 'Missing', 'localPath': str(root / 'missing.mp3'), 'duration': 1},
                ],
            }
            (root / 'ok.mp3').write_bytes(b'not-real-audio-but-present')
            (data / 'registry.json').write_text(json.dumps(registry), encoding='utf-8')
            old_root, old_data, old_registry, old_db, old_troot, old_queue = audio_telemetry.ROOT, audio_telemetry.DATA, audio_telemetry.REGISTRY_PATH, audio_telemetry.DB_PATH, audio_telemetry.TELEMETRY_ROOT, audio_telemetry.QUEUE_PATH
            try:
                audio_telemetry.ROOT = root
                audio_telemetry.DATA = data
                audio_telemetry.REGISTRY_PATH = data / 'registry.json'
                audio_telemetry.DB_PATH = data / 'hapa_registry.sqlite'
                audio_telemetry.TELEMETRY_ROOT = data / 'audio_telemetry'
                audio_telemetry.QUEUE_PATH = audio_telemetry.TELEMETRY_ROOT / 'queue.json'
                result = audio_telemetry.enqueue([], overwrite=False)
                queue = json.loads(audio_telemetry.QUEUE_PATH.read_text())
                self.assertEqual(result['added'], 2)
                self.assertEqual(len(queue['queue']), 2)
                ok = next(j for j in queue['queue'] if j['songId'] == 'song-ok')
                missing = next(j for j in queue['queue'] if j['songId'] == 'song-missing')
                self.assertEqual(ok['status'], 'queued')
                self.assertTrue(ok['analysisKey'].startswith('sha256:'))
                self.assertEqual(missing['status'], 'blocked')
                self.assertIn('missing', missing['lastError'])
            finally:
                audio_telemetry.ROOT, audio_telemetry.DATA, audio_telemetry.REGISTRY_PATH, audio_telemetry.DB_PATH, audio_telemetry.TELEMETRY_ROOT, audio_telemetry.QUEUE_PATH = old_root, old_data, old_registry, old_db, old_troot, old_queue

    def test_worker_targets_only_requested_song_and_never_auto_requeues_failure(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            data = root / 'data'
            telemetry = data / 'audio_telemetry'
            telemetry.mkdir(parents=True)
            songs = []
            for song_id in ('older', 'requested'):
                audio_path = root / f'{song_id}.mp3'
                audio_path.write_bytes(b'audio')
                songs.append({'id': song_id, 'title': song_id, 'localPath': str(audio_path)})
            (data / 'registry.json').write_text(json.dumps({'songs': songs}), encoding='utf-8')
            queue = audio_telemetry.default_queue()
            queue['queue'] = [
                {'id': 'old', 'songId': 'older', 'title': 'older', 'status': 'queued', 'priority': 50, 'attempts': 0, 'maxAttempts': 1, 'createdAt': '1', 'analysisKey': 'old'},
                {'id': 'new', 'songId': 'requested', 'title': 'requested', 'status': 'queued', 'priority': 50, 'attempts': 0, 'maxAttempts': 1, 'createdAt': '2', 'analysisKey': 'new'},
            ]
            old_values = audio_telemetry.DATA, audio_telemetry.REGISTRY_PATH, audio_telemetry.DB_PATH, audio_telemetry.TELEMETRY_ROOT, audio_telemetry.QUEUE_PATH
            try:
                audio_telemetry.DATA = data
                audio_telemetry.REGISTRY_PATH = data / 'registry.json'
                audio_telemetry.DB_PATH = data / 'registry.sqlite'
                audio_telemetry.TELEMETRY_ROOT = telemetry
                audio_telemetry.QUEUE_PATH = telemetry / 'queue.json'
                audio_telemetry.write_json(audio_telemetry.QUEUE_PATH, queue)
                with mock.patch.object(audio_telemetry, 'latest_matches', return_value=False), mock.patch.object(audio_telemetry, 'analyze_song', side_effect=RuntimeError('stop')):
                    result = audio_telemetry.worker(limit=1, song_ids=['requested'])
                saved = json.loads(audio_telemetry.QUEUE_PATH.read_text())
                older = next(job for job in saved['queue'] if job['songId'] == 'older')
                requested = next(job for job in saved['queue'] if job['songId'] == 'requested')
                self.assertEqual(result['failed'], 1)
                self.assertEqual(older['status'], 'queued')
                self.assertEqual(requested['status'], 'failed')
            finally:
                audio_telemetry.DATA, audio_telemetry.REGISTRY_PATH, audio_telemetry.DB_PATH, audio_telemetry.TELEMETRY_ROOT, audio_telemetry.QUEUE_PATH = old_values

    def test_ingest_reattaches_audio_telemetry_manifest_and_sqlite_tables(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            library = root / 'suno'
            project = root / 'project'
            manifest_dir = project / 'data' / 'audio_telemetry' / 'manifests'
            latest_dir = project / 'data' / 'audio_telemetry' / 'latest'
            library.mkdir()
            manifest_dir.mkdir(parents=True)
            latest_dir.mkdir(parents=True)
            (library / 'Song - song-001.mp3').write_bytes(b'audio')
            (library / 'suno_library_metadata.json').write_text(json.dumps([{
                'id': 'song-001', 'status': 'complete', 'title': 'Song', 'audio_url': 'x',
                'metadata': {'prompt': '[Verse]\nHello lyric', 'tags': '', 'duration': 1},
            }]), encoding='utf-8')
            run = {
                'runId': 'atr_test', 'songId': 'song-001', 'status': 'complete', 'confidence': 0.5,
                'summary': {'bpm': 120, 'tempoConfidence': 0.4, 'hookCount': 1, 'sectionCount': 1, 'beatCount': 2, 'barCount': 1},
                'timeline': {'events': [{'id': 'evt_hook', 'type': 'hook_candidate', 'label': 'Hook candidate', 'start': 0, 'end': 1, 'confidence': 0.5, 'score': 0.5, 'source': 'test', 'reasons': ['test candidate']}]},
                'warnings': [],
            }
            latest_path = latest_dir / 'song-001.json'
            latest_path.write_text(json.dumps(run), encoding='utf-8')
            (manifest_dir / 'song-001.json').write_text(json.dumps({
                'songId': 'song-001', 'runId': 'atr_test', 'status': 'complete', 'confidence': 0.5,
                'summary': run['summary'], 'runPath': str(latest_path), 'latestPath': str(latest_path),
                'timelineEventCount': 1, 'updatedAt': '2026-01-01T00:00:00Z', 'warnings': [],
            }), encoding='utf-8')

            registry = ingest.build_registry(library, project_root=project, lyric_roots=[])
            self.assertEqual(registry['counts']['audioTelemetry'], 1)
            self.assertEqual(registry['songs'][0]['audioTelemetry']['latestRunId'], 'atr_test')
            _, db_path = ingest.write_outputs(registry, project)
            con = sqlite3.connect(db_path)
            cur = con.cursor()
            tables = {r[0] for r in cur.execute("select name from sqlite_master where type='table'")}
            self.assertIn('audio_telemetry_runs', tables)
            self.assertIn('audio_telemetry_events', tables)
            self.assertEqual(cur.execute('select bpm from audio_telemetry_runs where song_id=?', ('song-001',)).fetchone()[0], 120)
            self.assertEqual(cur.execute("select count(*) from audio_telemetry_events where event_type='hook_candidate'").fetchone()[0], 1)
            con.close()


if __name__ == '__main__':
    unittest.main()
