#!/usr/bin/env python3
import json
import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
REGISTRY_PATH = DATA / 'registry.json'
DB_PATH = DATA / 'hapa_registry.sqlite'

errors = []
if not REGISTRY_PATH.exists():
    errors.append(f'missing {REGISTRY_PATH}')
if not DB_PATH.exists():
    errors.append(f'missing {DB_PATH}')
if errors:
    print('\n'.join(errors))
    sys.exit(1)

reg = json.loads(REGISTRY_PATH.read_text(encoding='utf-8'))
counts = reg.get('counts', {})
expected_from_json = {
    'songs': len(reg.get('songs', [])),
    'stems': len(reg.get('stems', [])),
    'groups': len(reg.get('groups', [])),
    'similarities': len(reg.get('similarities', [])),
    'externalLyrics': len(reg.get('externalLyrics', [])),
    'lyricMasters': len(reg.get('lyricMasters', [])),
    'promptGroups': len(reg.get('promptGroups', [])),
    'mashups': len([s for s in reg.get('songs', []) if s.get('isMashup')]),
    'lyricTimings': len([s for s in reg.get('songs', []) if s.get('lyricTiming')]),
}
for key, actual in expected_from_json.items():
    if counts.get(key) != actual:
        errors.append(f'json counts.{key}: expected {actual}, got {counts.get(key)}')

missing_song_paths = [s['id'] for s in reg.get('songs', []) if not s.get('localPath') or not pathlib.Path(s['localPath']).exists()]
missing_stem_paths = [s['id'] for s in reg.get('stems', []) if not s.get('localPath') or not pathlib.Path(s['localPath']).exists()]
if missing_song_paths:
    errors.append(f'missing song paths: {len(missing_song_paths)}')
if missing_stem_paths:
    errors.append(f'missing stem paths: {len(missing_stem_paths)}')

con = sqlite3.connect(DB_PATH)
cur = con.cursor()
tables = {r[0] for r in cur.execute("select name from sqlite_master where type='table'")}
required_tables = {
    'songs', 'stems', 'facets', 'groups', 'similarities',
    'authors', 'song_authors', 'stem_authors', 'external_lyrics',
    'lyric_masters', 'lyric_variations', 'prompt_groups', 'mashups', 'events', 'rename_history',
    'loops', 'derivatives', 'engagements',
}
missing_tables = sorted(required_tables - tables)
if missing_tables:
    errors.append(f'missing sqlite tables: {", ".join(missing_tables)}')

def count_table(table):
    if table not in tables:
        return None
    return cur.execute(f'select count(*) from {table}').fetchone()[0]

for table, key in [('songs', 'songs'), ('stems', 'stems'), ('groups', 'groups'), ('similarities', 'similarities'), ('external_lyrics', 'externalLyrics'), ('lyric_masters', 'lyricMasters'), ('prompt_groups', 'promptGroups'), ('mashups', 'mashups')]:
    n = count_table(table)
    if n is not None and n != counts.get(key, 0):
        errors.append(f'sqlite {table}: expected {counts.get(key, 0)}, got {n}')

if 'authors' in tables:
    author_names = {r[0] for r in cur.execute('select name from authors')}
    for required in reg.get('defaultAuthors', ['Calder', 'Waldercong', 'DeadpanDecoders95']):
        if required not in author_names:
            errors.append(f'missing default author: {required}')

if 'lyric_variations' in tables and 'lyric_masters' in tables:
    orphan_variations = cur.execute('''
        select count(*) from lyric_variations v
        left join lyric_masters m on m.id = v.lyric_master_id
        where m.id is null
    ''').fetchone()[0]
    if orphan_variations:
        errors.append(f'lyric_variations orphan rows: {orphan_variations}')

# Lyric timing tables are produced by scripts/analyze_lyric_timing.py. Verify them when present,
# but do not hardcode counts because the registry is regenerated from live libraries.
if {'lyric_timing_runs', 'lyric_lines'}.issubset(tables):
    timing_runs = count_table('lyric_timing_runs')
    if timing_runs is not None and timing_runs > counts.get('songs', 0):
        errors.append(f'sqlite lyric_timing_runs: expected <= songs ({counts.get("songs", 0)}), got {timing_runs}')
    line_count = count_table('lyric_lines') or 0
    if timing_runs and line_count <= 0:
        errors.append('sqlite lyric_lines: expected timestamped lyric lines when timing runs exist')
    invalid_lines = cur.execute('select count(*) from lyric_lines where start < 0 or end <= start').fetchone()[0]
    if invalid_lines:
        errors.append(f'sqlite lyric_lines: invalid timing rows {invalid_lines}')

con.close()
if errors:
    print('\n'.join(errors))
    sys.exit(1)
print('Registry verified')
print(json.dumps(counts, indent=2))
