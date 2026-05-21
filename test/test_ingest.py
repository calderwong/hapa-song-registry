import importlib.util
import json
import pathlib
import sqlite3
import tempfile
import unittest
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('ingest_suno', ROOT / 'scripts' / 'ingest_suno.py')
ingest = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ingest)


class IngestHelpersTest(unittest.TestCase):
    def test_extract_lyrics_removes_section_headers_but_keeps_lines(self):
        raw = '[Verse 1]\nHello world\n\n[Chorus - bright]\nSing again'
        self.assertEqual(ingest.extract_lyrics(raw), 'Hello world\nSing again')

    def test_parse_lyrics_preserves_sections_for_timing(self):
        raw = '[Intro — soft]\nMm…\n[Verse 1]\nHello world\n[Chorus - bright]\nSing again'
        parsed = ingest.parse_lyrics(raw)
        self.assertEqual([s['label'] for s in parsed['sections']], ['Intro — soft', 'Verse 1', 'Chorus - bright'])
        self.assertEqual([l['section'] for l in parsed['lines']], ['Intro — soft', 'Verse 1', 'Chorus - bright'])
        self.assertEqual(parsed['lines'][1]['text'], 'Hello world')

    def test_classifies_prompt_facets_from_tags_and_lyrics(self):
        clip = {
            'title': 'Ubuntu Bell',
            'metadata': {
                'prompt': 'I am because we are\nRing the bell',
                'tags': 'sacred communal folk soul anthem warm hand percussion choir luminous tender euphoric'
            }
        }
        facets = ingest.classify_facets(clip)
        self.assertIn('folk', facets['themes'])
        self.assertIn('percussion', facets['instruments'])
        self.assertIn('communal', facets['message'])
        self.assertIn('euphoric', facets['mood'])

    def test_stem_detection_and_parent_id(self):
        clip = {'metadata': {'stem_from_id': 'parent-123', 'stem_type_group_name': 'Backing_Vocals'}}
        self.assertTrue(ingest.is_stem(clip))
        self.assertEqual(ingest.stem_group(clip), 'Backing Vocals')
        self.assertEqual(ingest.parent_id_for_stem(clip), 'parent-123')

    def test_local_file_discovery_by_id_prefix(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            (root / 'Song - abcdef12.mp3').write_bytes(b'abc')
            self.assertEqual(ingest.find_audio_file(root, 'abcdef12-0000'), str(root / 'Song - abcdef12.mp3'))

    def test_external_markdown_and_docx_lyrics_are_ingested_and_deduped_with_suno(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            library = root / 'suno'
            lyrics_dir = root / 'Hapa Song Lyrics'
            project = root / 'project'
            library.mkdir()
            lyrics_dir.mkdir()
            (library / 'Suno Tune - song-001.mp3').write_bytes(b'audio')
            (library / 'Stem Tune - stem-001.mp3').write_bytes(b'audio')
            shared_prompt = '[Verse]\nShared lyric line\n[Chorus]\nSame chorus'
            metadata = [
                {
                    'id': 'song-001', 'status': 'complete', 'title': 'Suno Tune',
                    'audio_url': 'https://example.test/song.mp3', 'model_name': 'v4',
                    'metadata': {'prompt': shared_prompt, 'tags': 'folk', 'duration': 10},
                },
                {
                    'id': 'stem-001', 'status': 'complete', 'title': 'Suno Tune (Vocals)',
                    'audio_url': 'https://example.test/stem.mp3', 'model_name': 'v4',
                    'metadata': {'prompt': shared_prompt, 'stem_from_id': 'song-001', 'stem_type_group_name': 'Vocals', 'duration': 10},
                },
            ]
            (library / 'suno_library_metadata.json').write_text(json.dumps(metadata), encoding='utf-8')
            (lyrics_dir / 'Shared.md').write_text('# Shared\n\nShared lyric line\nSame chorus\n', encoding='utf-8')
            with zipfile.ZipFile(lyrics_dir / 'Unique.docx', 'w') as zf:
                zf.writestr('[Content_Types].xml', '')
                zf.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Docx only line</w:t></w:r></w:p></w:body></w:document>')

            registry = ingest.build_registry(library, project_root=project, lyric_roots=[lyrics_dir])

            self.assertEqual(registry['counts']['externalLyrics'], 2)
            self.assertEqual(registry['counts']['lyricMasters'], 2)
            song = registry['songs'][0]
            stem = registry['stems'][0]
            self.assertEqual(song['authors'], ['Calder', 'Waldercong', 'DeadpanDecoders95'])
            self.assertEqual(stem['authors'], ['Calder', 'Waldercong', 'DeadpanDecoders95'])
            self.assertEqual(song['lyricMasterId'], stem['lyricMasterId'])
            shared_master = next(m for m in registry['lyricMasters'] if m['id'] == song['lyricMasterId'])
            self.assertEqual(shared_master['variationCount'], 3)
            self.assertEqual({v['kind'] for v in shared_master['variations']}, {'song', 'stem', 'external_lyric'})
            self.assertTrue(any(m['sourceTitle'] == 'Unique' for m in registry['lyricMasters']))

    def test_prompt_groups_layer_style_prompts_under_the_same_lyrics(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            library = root / 'suno'
            project = root / 'project'
            library.mkdir()
            shared_lyrics = '[Verse]\nSame lyric line\n[Chorus]\nSame hook'
            metadata = [
                {'id': 'song-001', 'status': 'complete', 'title': 'Acoustic take', 'audio_url': 'x', 'metadata': {'prompt': shared_lyrics, 'tags': 'warm acoustic folk tender', 'duration': 1, 'type': 'gen'}},
                {'id': 'song-002', 'status': 'complete', 'title': 'Electro take', 'audio_url': 'x', 'metadata': {'prompt': shared_lyrics, 'tags': 'dark synth electronic aggressive', 'duration': 1, 'type': 'gen'}},
                {'id': 'song-003', 'status': 'complete', 'title': 'Acoustic sibling', 'audio_url': 'x', 'metadata': {'prompt': shared_lyrics, 'tags': 'warm acoustic folk tender', 'duration': 1, 'type': 'gen'}},
            ]
            for clip in metadata:
                (library / f"{clip['title']} - {clip['id'][:8]}.mp3").write_bytes(b'audio')
            (library / 'suno_library_metadata.json').write_text(json.dumps(metadata), encoding='utf-8')

            registry = ingest.build_registry(library, project_root=project, lyric_roots=[])
            self.assertEqual(registry['counts']['lyricMasters'], 1)
            self.assertEqual(registry['counts']['promptGroups'], 2)
            master = registry['lyricMasters'][0]
            self.assertEqual(master['promptGroupCount'], 2)
            self.assertEqual(len(master['promptGroups']), 2)
            acoustic = next(g for g in registry['promptGroups'] if 'acoustic' in g['stylePrompt'])
            electro = next(g for g in registry['promptGroups'] if 'electronic' in g['stylePrompt'])
            self.assertEqual(acoustic['songCount'], 2)
            self.assertEqual(electro['songCount'], 1)
            self.assertIn('folk', acoustic['facets']['themes'])
            self.assertIn('electronic', electro['facets']['themes'])
            self.assertEqual({s['promptGroupId'] for s in registry['songs']}, {g['id'] for g in registry['promptGroups']})

    def test_mashup_metadata_is_captured_and_queryable_in_sqlite(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            library = root / 'suno'
            project = root / 'project'
            library.mkdir()
            clips = [
                {'id': 'base-001', 'status': 'complete', 'title': 'Base', 'audio_url': 'x', 'metadata': {'prompt': 'Base lyric', 'tags': 'folk', 'duration': 1, 'type': 'gen'}},
                {'id': 'mash-001', 'status': 'complete', 'title': 'Base Mashup', 'audio_url': 'x', 'metadata': {'prompt': 'Base lyric', 'tags': 'folk trap cinematic', 'duration': 1, 'type': 'mashup', 'task': 'mashup', 'mashup_source_clip_ids': ['base-001', 'other-002']}},
            ]
            for clip in clips:
                (library / f"{clip['title']} - {clip['id'][:8]}.mp3").write_bytes(b'audio')
            (library / 'suno_library_metadata.json').write_text(json.dumps(clips), encoding='utf-8')

            registry = ingest.build_registry(library, project_root=project, lyric_roots=[])
            mash = next(s for s in registry['songs'] if s['id'] == 'mash-001')
            self.assertTrue(mash['isMashup'])
            self.assertEqual(mash['contentType'], 'mashup')
            self.assertEqual(mash['mashupSourceIds'], ['base-001', 'other-002'])
            self.assertEqual(registry['counts']['mashups'], 1)
            _, db_path = ingest.write_outputs(registry, project)
            con = sqlite3.connect(db_path)
            cur = con.cursor()
            self.assertIn('prompt_groups', {r[0] for r in cur.execute("select name from sqlite_master where type='table'")})
            self.assertIn('mashups', {r[0] for r in cur.execute("select name from sqlite_master where type='table'")})
            self.assertEqual(cur.execute('select count(*) from mashups').fetchone()[0], 1)
            self.assertEqual(cur.execute('select content_type, source_ids_json from songs where id=?', ('mash-001',)).fetchone()[0], 'mashup')
            con.close()

    def test_sqlite_contains_foundation_tables_for_authors_events_history_lyrics_and_engagement(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            library = root / 'suno'
            project = root / 'project'
            library.mkdir()
            (library / 'Song - song-001.mp3').write_bytes(b'audio')
            (library / 'suno_library_metadata.json').write_text(json.dumps([{
                'id': 'song-001', 'status': 'complete', 'title': 'Song', 'audio_url': 'x',
                'metadata': {'prompt': 'Hello lyric', 'tags': '', 'duration': 1},
            }]), encoding='utf-8')

            registry = ingest.build_registry(library, project_root=project, lyric_roots=[])
            _, db_path = ingest.write_outputs(registry, project)

            con = sqlite3.connect(db_path)
            cur = con.cursor()
            tables = {r[0] for r in cur.execute("select name from sqlite_master where type='table'")}
            for table in ['authors', 'song_authors', 'lyric_masters', 'lyric_variations', 'events', 'rename_history', 'loops', 'derivatives', 'engagements']:
                self.assertIn(table, tables)
            self.assertEqual(cur.execute('select count(*) from authors').fetchone()[0], 3)
            self.assertEqual(cur.execute('select count(*) from song_authors').fetchone()[0], 3)
            self.assertEqual(cur.execute("select count(*) from events where event_type='created'").fetchone()[0], 1)
            con.close()

    def test_existing_lyric_timing_files_are_preserved_when_regenerating_registry(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            library = root / 'suno'
            project = root / 'project'
            timing_dir = project / 'data' / 'lyric_timings'
            library.mkdir()
            timing_dir.mkdir(parents=True)
            (library / 'Song - song-001.mp3').write_bytes(b'audio')
            (library / 'suno_library_metadata.json').write_text(json.dumps([{
                'id': 'song-001', 'status': 'complete', 'title': 'Song', 'audio_url': 'x',
                'metadata': {'prompt': '[Verse]\nHello lyric', 'tags': '', 'duration': 1},
            }]), encoding='utf-8')
            timing_dir.joinpath('song-001.json').write_text(json.dumps({
                'version': 1, 'method': 'test', 'source': 'full_mix', 'sourcePath': '/tmp/song.mp3',
                'analyzedAt': '2026-01-01T00:00:00Z', 'confidence': 0.9,
                'warnings': [], 'stats': {},
                'lines': [{'index': 0, 'sectionIndex': 0, 'section': 'Verse', 'text': 'Hello lyric', 'start': 0, 'end': 1, 'timestamp': '0:00', 'confidence': 0.9}],
                'sections': [{'index': 0, 'label': 'Verse', 'start': 0, 'end': 1, 'timestamp': '0:00', 'lineStart': 0, 'lineEnd': 0, 'confidence': 0.9}],
            }), encoding='utf-8')

            registry = ingest.build_registry(library, project_root=project, lyric_roots=[])
            self.assertEqual(registry['counts']['lyricTimings'], 1)
            self.assertEqual(registry['songs'][0]['lyricTiming']['method'], 'test')
            _, db_path = ingest.write_outputs(registry, project)
            con = sqlite3.connect(db_path)
            cur = con.cursor()
            self.assertEqual(cur.execute('select count(*) from lyric_timing_runs').fetchone()[0], 1)
            self.assertEqual(cur.execute('select count(*) from lyric_lines').fetchone()[0], 1)
            con.close()


if __name__ == '__main__':
    unittest.main()
