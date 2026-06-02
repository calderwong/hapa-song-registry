#!/usr/bin/env python3
import argparse
import hashlib
import json
import math
import os
import pathlib
import re
import sqlite3
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from html import unescape

DEFAULT_LIBRARY = pathlib.Path.home() / 'Desktop' / 'suno-library'
DEFAULT_PROJECT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_LYRIC_ROOTS = [pathlib.Path.home() / 'Desktop' / 'Hapa Song Lyrics', pathlib.Path.home() / 'Desktop' / 'Hapa Song Library']
DEFAULT_AUTHORS = ['Calder', 'Waldercong', 'DeadpanDecoders95']
STOPWORDS = set('a an and are as at be because but by for from has have i in into is it its just let like me my no not of on or our so the to we when with you your was were will every this that through'.split())

THEME_WORDS = {
    'folk': ['folk', 'acoustic', 'americana', 'appalachian'],
    'soul': ['soul', 'gospel', 'r&b', 'torch'],
    'pop': ['pop', 'anthem', 'hook'],
    'rock': ['rock', 'grunge', 'guitar'],
    'electronic': ['electronic', 'synth', 'chiptune', 'edm', 'glitch'],
    'cinematic': ['cinematic', 'orchestral', 'score', 'trailer'],
    'jazz': ['jazz', 'swing', 'brass', 'bossa'],
    'communal': ['communal', 'choir', 'together', 'ubuntu', 'we are'],
    'spiritual': ['sacred', 'prayer', 'hymn', 'spiritual', 'bell'],
    'love': ['love', 'heart', 'darling', 'kiss'],
    'story': ['story', 'narrative', 'character', 'dialogue'],
}
INSTRUMENT_WORDS = {
    'vocals': ['vocal', 'voice', 'singer', 'choir', 'harmon'],
    'drums': ['drum', 'drums', 'beat', 'kick', 'snare', 'percussion'],
    'percussion': ['percussion', 'clap', 'hand percussion', 'tambourine'],
    'guitar': ['guitar', 'riff', 'strum'],
    'bass': ['bass', 'sub'],
    'piano': ['piano'],
    'keyboard': ['keyboard', 'keys', 'organ', 'rhodes'],
    'synth': ['synth', 'pad', 'lead'],
    'strings': ['string', 'strings', 'violin', 'cello'],
    'brass': ['brass', 'trumpet', 'trombone', 'horn'],
    'woodwinds': ['woodwind', 'flute', 'clarinet', 'sax'],
    'kalimba': ['kalimba', 'mbira'],
}
MOOD_WORDS = {
    'euphoric': ['euphoric', 'triumphant', 'uplifting', 'bright'],
    'tender': ['tender', 'soft', 'warm', 'gentle', 'intimate'],
    'melancholic': ['melancholic', 'sad', 'lonely', 'haunting'],
    'dark': ['dark', 'ominous', 'gothic', 'noir'],
    'aggressive': ['aggressive', 'heavy', 'raw', 'distorted'],
    'dreamy': ['dreamy', 'ethereal', 'floating', 'ambient'],
    'playful': ['playful', 'funny', 'quirky', 'silly'],
    'wise': ['wise', 'reflective', 'philosophical'],
}
MESSAGE_WORDS = {
    'communal': ['together', 'we are', 'ubuntu', 'belonging', 'community', 'shared'],
    'resilience': ['survive', 'resilience', 'rise', 'fire', 'endure'],
    'longing': ['miss', 'longing', 'waiting', 'goodbye'],
    'liberation': ['free', 'freedom', 'break', 'release'],
    'love': ['love', 'heart', 'home', 'hold'],
    'warning': ['warning', 'danger', 'beware'],
    'identity': ['myself', 'name', 'mirror', 'become', 'identity'],
}
SECTION_RE = re.compile(r'^\[([^\]]+)\]$')


def safe_name(s):
    s = (s or 'Untitled').strip()
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', s)
    s = re.sub(r'\s+', ' ', s).strip(' .')
    return s[:160] or 'Untitled'


def parse_lyrics(prompt):
    """Parse Suno prompt lyrics into display text plus timing-friendly sections."""
    sections = []
    lines = []
    current_label = 'Lyrics'
    current_index = -1
    for raw_index, raw in enumerate(str(prompt or '').splitlines()):
        stripped = raw.strip()
        if not stripped:
            continue
        match = SECTION_RE.fullmatch(stripped)
        if match:
            current_label = match.group(1).strip()
            current_index += 1
            sections.append({'index': current_index, 'label': current_label, 'rawIndex': raw_index, 'lineStart': len(lines), 'lineEnd': len(lines)})
            continue
        if current_index < 0:
            current_index = 0
            sections.append({'index': current_index, 'label': current_label, 'rawIndex': raw_index, 'lineStart': len(lines), 'lineEnd': len(lines)})
        line = {'index': len(lines), 'sectionIndex': current_index, 'section': current_label, 'text': stripped, 'rawIndex': raw_index}
        lines.append(line)
        sections[current_index]['lineEnd'] = len(lines) - 1
    return {'lines': lines, 'sections': sections, 'text': '\n'.join(line['text'] for line in lines)}


def extract_lyrics(prompt):
    return parse_lyrics(prompt)['text']


def normalize_text(text):
    return re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9\s]', ' ', (text or '').lower())).strip()


def tokens(text):
    return {t for t in normalize_text(text).split() if len(t) > 2 and t not in STOPWORDS}


def fingerprint(text):
    norm = normalize_text(text)
    return hashlib.sha1(norm.encode('utf-8')).hexdigest() if norm else ''


def stable_id(prefix, *parts):
    digest = hashlib.sha1('|'.join(str(p or '') for p in parts).encode('utf-8')).hexdigest()[:16]
    return f'{prefix}_{digest}'


def strip_markdown(text):
    lines = []
    for raw in str(text or '').splitlines():
        line = raw.strip()
        if not line:
            continue
        if re.match(r'^#{1,6}\s+', line):
            continue
        line = re.sub(r'`([^`]+)`', r'\1', line)
        line = re.sub(r'[*_]{1,3}([^*_]+)[*_]{1,3}', r'\1', line)
        line = re.sub(r'^[-*+]\s+', '', line)
        lines.append(line)
    return '\n'.join(lines)


def read_docx_text(path):
    try:
        with zipfile.ZipFile(path) as zf:
            xml = zf.read('word/document.xml').decode('utf-8', errors='ignore')
    except Exception:
        return ''
    xml = re.sub(r'</w:p\s*>', '\n', xml)
    xml = re.sub(r'<[^>]+>', '', xml)
    return unescape(xml)


def discover_external_lyrics(lyric_roots=None):
    roots = DEFAULT_LYRIC_ROOTS if lyric_roots is None else [pathlib.Path(p) for p in lyric_roots]
    docs = []
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob('*')):
            if not path.is_file() or path.name.startswith('~$'):
                continue
            suffix = path.suffix.lower()
            if suffix not in ('.md', '.markdown', '.docx'):
                continue
            raw = read_docx_text(path) if suffix == '.docx' else path.read_text(encoding='utf-8', errors='ignore')
            lyrics = strip_markdown(raw)
            fp = fingerprint(lyrics)
            if not fp:
                continue
            docs.append({'id': stable_id('extlyr', str(path)), 'title': path.stem, 'path': str(path), 'lyrics': lyrics, 'lyricsFingerprint': fp, 'source': 'external_lyric'})
    return docs


def keyword_hits(text, mapping):
    low = (text or '').lower()
    hits = []
    for label, words in mapping.items():
        if any(w in low for w in words):
            hits.append(label)
    return hits


def classify_facets(clip, style_prompt=None):
    m = clip.get('metadata') or {}
    prompt = m.get('prompt') or ''
    tags = m.get('tags') or ''
    title = clip.get('title') or ''
    combined = ' '.join([title, tags, style_prompt or '', prompt])
    return {
        'themes': keyword_hits(combined, THEME_WORDS) or ['uncategorized'],
        'instruments': keyword_hits(combined, INSTRUMENT_WORDS) or ['unknown'],
        'mood': keyword_hits(combined, MOOD_WORDS) or ['unspecified'],
        'message': keyword_hits(combined, MESSAGE_WORDS) or ['unspecified'],
    }


def style_prompt_for_clip(clip):
    m = clip.get('metadata') or {}
    parts = [m.get('tags') or '']
    for key in ('gpt_description_prompt', 'negative_tags', 'persona_id', 'task', 'type', 'key'):
        if m.get(key):
            parts.append(f'{key}: {m.get(key)}')
    for key in ('control_sliders', 'model_badges', 'secondary_badges'):
        if m.get(key):
            parts.append(f'{key}: {json.dumps(m.get(key), ensure_ascii=False, sort_keys=True)}')
    return '\n'.join(str(p) for p in parts if str(p).strip())


def content_type_for_clip(clip):
    m = clip.get('metadata') or {}
    for val in (m.get('type'), m.get('task'), clip.get('type')):
        if val and 'mash' in str(val).lower():
            return 'mashup'
    blob = json.dumps({'title': clip.get('title'), 'metadata': m.get('secondary_badges') or m.get('history') or m.get('concat_history')}, ensure_ascii=False).lower()
    if 'mashup' in blob or 'mash-up' in blob:
        return 'mashup'
    if m.get('type'):
        return str(m.get('type'))
    return 'song'


def mashup_source_ids(clip):
    m = clip.get('metadata') or {}
    candidates = []
    for key in ('mashup_source_clip_ids', 'mashup_clip_ids', 'source_clip_ids', 'source_ids'):
        val = m.get(key)
        if isinstance(val, list):
            candidates.extend(str(x) for x in val if x)
        elif isinstance(val, str):
            candidates.extend(x.strip() for x in re.split(r'[,\s]+', val) if x.strip())
    for key in ('cover_clip_id', 'artist_clip_id', 'edited_clip_id', 'concat_history'):
        val = m.get(key)
        if isinstance(val, str) and val:
            candidates.append(val)
        elif isinstance(val, list):
            candidates.extend(str(x.get('id') if isinstance(x, dict) else x) for x in val if x)
    return sorted(dict.fromkeys(candidates))


def is_mashup(clip):
    return content_type_for_clip(clip) == 'mashup'


def is_stem(clip):
    m = clip.get('metadata') or {}
    return any(k in m for k in ('stem_from_id', 'stem_task', 'stem_type_id', 'stem_type_group_name'))


def stem_group(clip):
    m = clip.get('metadata') or {}
    return safe_name((m.get('stem_type_group_name') or m.get('stem_task') or 'Stem').replace('_', ' '))


def parent_id_for_stem(clip):
    return (clip.get('metadata') or {}).get('stem_from_id') or (clip.get('metadata') or {}).get('edited_clip_id')


def has_audio(clip):
    return bool(clip.get('audio_url') or any((i.get('url') and i.get('delivery') in (None, 'progressive')) for i in (clip.get('media_urls') or [])))


def find_audio_file(root, clip_id):
    prefix = (clip_id or '')[:8]
    if not prefix:
        return None
    for pattern in [f'* - {prefix}.*', f'*/* - {prefix}.*', f'*/*/* - {prefix}.*']:
        matches = [p for p in pathlib.Path(root).glob(pattern) if p.is_file() and not p.name.endswith('.part') and p.suffix.lower() in ('.mp3', '.m4a', '.wav', '.webm', '.ogg', '.flac', '.aac')]
        if matches:
            return str(matches[0])
    return None


def basename_without_stem_suffix(title):
    return re.sub(r'\s*\((Vocals|Backing Vocals|Drums|Bass|Guitar|Keyboard|Percussion|Strings|Synth|FX|Brass|Woodwinds)\)\s*$', '', title or '', flags=re.I).strip()


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def load_existing_lyric_timings(project_root, songs):
    timing_dir = pathlib.Path(project_root) / 'data' / 'lyric_timings'
    if not timing_dir.exists():
        return 0
    attached = 0
    for song in songs:
        path = timing_dir / f"{song.get('id')}.json"
        if not path.exists():
            continue
        try:
            song['lyricTiming'] = json.loads(path.read_text(encoding='utf-8'))
            attached += 1
        except Exception:
            continue
    return attached


def load_existing_audio_telemetry(project_root, songs):
    manifest_dir = pathlib.Path(project_root) / 'data' / 'audio_telemetry' / 'manifests'
    if not manifest_dir.exists():
        return 0
    attached = 0
    for song in songs:
        path = manifest_dir / f"{song.get('id')}.json"
        if not path.exists():
            continue
        try:
            manifest = json.loads(path.read_text(encoding='utf-8'))
            song['audioTelemetry'] = {
                'status': manifest.get('status'),
                'latestRunId': manifest.get('runId'),
                'summary': manifest.get('summary') or {},
                'manifestPath': str(path),
                'timelinePath': manifest.get('latestPath'),
                'runPath': manifest.get('runPath'),
                'confidence': manifest.get('confidence'),
                'updatedAt': manifest.get('updatedAt'),
                'timelineEventCount': manifest.get('timelineEventCount', 0),
                'warnings': manifest.get('warnings', []),
            }
            attached += 1
        except Exception:
            continue
    return attached


def build_registry(library_root=DEFAULT_LIBRARY, project_root=DEFAULT_PROJECT, lyric_roots=None):
    library_root = pathlib.Path(library_root)
    project_root = pathlib.Path(project_root)
    metadata_path = library_root / 'suno_library_metadata.json'
    raw_clips = json.loads(metadata_path.read_text())
    songs = []
    stems = []
    song_by_id = {}
    for clip in raw_clips:
        if clip.get('status') != 'complete' or not has_audio(clip):
            continue
        m = clip.get('metadata') or {}
        lyric_parse = parse_lyrics(m.get('prompt') or '')
        base = {
            'id': clip.get('id'),
            'title': clip.get('title') or 'Untitled',
            'authors': list(DEFAULT_AUTHORS),
            'createdAt': clip.get('created_at'),
            'duration': m.get('duration'),
            'model': clip.get('model_name'),
            'majorModelVersion': clip.get('major_model_version'),
            'audioUrl': clip.get('audio_url'),
            'imageUrl': clip.get('image_url') or clip.get('image_large_url'),
            'tags': m.get('tags') or '',
            'prompt': m.get('prompt') or '',
            'lyrics': lyric_parse['text'],
            'lyricParse': lyric_parse,
            'settings': {k: v for k, v in m.items() if k not in ('prompt', 'tags', 'history')},
            'raw': clip,
        }
        base['localPath'] = find_audio_file(library_root, base['id'])
        base['lyricsFingerprint'] = fingerprint(base['lyrics'])
        base['stylePrompt'] = style_prompt_for_clip(clip)
        base['stylePromptFingerprint'] = fingerprint(base['stylePrompt'])
        base['promptFingerprint'] = fingerprint(base['prompt'])
        base['contentType'] = content_type_for_clip(clip)
        base['isMashup'] = is_mashup(clip)
        base['mashupSourceIds'] = mashup_source_ids(clip)
        if is_stem(clip):
            base['parentId'] = parent_id_for_stem(clip)
            base['stemType'] = stem_group(clip)
            stems.append(base)
        else:
            base['facets'] = classify_facets(clip, base.get('stylePrompt'))
            base['tokenCount'] = len(tokens(base['prompt'] + ' ' + base['tags'] + ' ' + base.get('stylePrompt', '')))
            songs.append(base)
            song_by_id[base['id']] = base
    stems_by_parent = defaultdict(list)
    for stem in stems:
        stems_by_parent[stem.get('parentId')].append(stem)
    for song in songs:
        linked = stems_by_parent.get(song['id'], [])
        song['stemCount'] = len(linked)
        song['stemTypes'] = sorted(Counter(s['stemType'] for s in linked).keys())
    external_lyrics = discover_external_lyrics(lyric_roots)
    lyric_masters = build_lyric_masters(songs, stems, external_lyrics)
    prompt_groups = build_prompt_groups(songs, lyric_masters)
    lyric_timing_count = load_existing_lyric_timings(project_root, songs)
    audio_telemetry_count = load_existing_audio_telemetry(project_root, songs)
    groups = build_groups(songs, stems_by_parent)
    similarities = build_similarities(songs)
    registry = {
        'generatedAt': datetime.utcnow().isoformat() + 'Z',
        'sourceLibrary': str(library_root),
        'lyricRoots': [str(p) for p in (DEFAULT_LYRIC_ROOTS if lyric_roots is None else [pathlib.Path(p) for p in lyric_roots]) if pathlib.Path(p).exists()],
        'defaultAuthors': list(DEFAULT_AUTHORS),
        'counts': {'songs': len(songs), 'stems': len(stems), 'groups': len(groups), 'similarities': len(similarities), 'externalLyrics': len(external_lyrics), 'lyricMasters': len(lyric_masters), 'promptGroups': len(prompt_groups), 'mashups': sum(1 for s in songs if s.get('isMashup')), 'lyricTimings': lyric_timing_count, 'audioTelemetry': audio_telemetry_count},
        'songs': songs,
        'stems': stems,
        'externalLyrics': external_lyrics,
        'lyricMasters': lyric_masters,
        'promptGroups': prompt_groups,
        'groups': groups,
        'similarities': similarities,
        'facets': facet_summary(songs),
    }
    return registry


def build_lyric_masters(songs, stems, external_lyrics):
    by_fp = defaultdict(lambda: {'songs': [], 'stems': [], 'external': []})
    for s in songs:
        if s.get('lyricsFingerprint'):
            by_fp[s['lyricsFingerprint']]['songs'].append(s)
    for st in stems:
        if st.get('lyricsFingerprint'):
            by_fp[st['lyricsFingerprint']]['stems'].append(st)
    for doc in external_lyrics:
        by_fp[doc['lyricsFingerprint']]['external'].append(doc)

    masters = []
    for fp in sorted(by_fp):
        bucket = by_fp[fp]
        source = (bucket['songs'] or bucket['external'] or bucket['stems'])[0]
        master_id = stable_id('lyr', fp)
        variations = []
        for s in bucket['songs']:
            s['lyricMasterId'] = master_id
            variations.append({'kind': 'song', 'id': s['id'], 'title': s.get('title')})
        for st in bucket['stems']:
            st['lyricMasterId'] = master_id
            variations.append({'kind': 'stem', 'id': st['id'], 'title': st.get('title'), 'parentId': st.get('parentId'), 'stemType': st.get('stemType')})
        for doc in bucket['external']:
            doc['lyricMasterId'] = master_id
            variations.append({'kind': 'external_lyric', 'id': doc['id'], 'title': doc.get('title'), 'path': doc.get('path')})
        masters.append({
            'id': master_id,
            'lyricsFingerprint': fp,
            'sourceTitle': source.get('title') or 'Untitled',
            'lyrics': source.get('lyrics') or '',
            'authors': list(DEFAULT_AUTHORS),
            'variations': variations,
            'variationCount': len(variations),
        })
    return masters


def build_prompt_groups(songs, lyric_masters):
    groups = []
    songs_by_master = defaultdict(list)
    for s in songs:
        if s.get('lyricMasterId'):
            songs_by_master[s['lyricMasterId']].append(s)
    for master in lyric_masters:
        master_groups = []
        buckets = defaultdict(list)
        for s in songs_by_master.get(master['id'], []):
            key = s.get('stylePromptFingerprint') or fingerprint(s.get('tags') or s.get('stylePrompt') or s.get('prompt') or s.get('id'))
            buckets[key].append(s)
        for key in sorted(buckets):
            members = sorted(buckets[key], key=lambda x: (x.get('createdAt') or '', x.get('id') or ''))
            style = members[0].get('stylePrompt') or members[0].get('tags') or ''
            facets = facet_summary(members)
            compact_facets = {kind: [row['name'] for row in facets.get(kind, [])[:8]] for kind in ['themes', 'instruments', 'mood', 'message']}
            group = {
                'id': stable_id('prompt', master['id'], key),
                'lyricMasterId': master['id'],
                'stylePromptFingerprint': key,
                'stylePrompt': style,
                'songIds': [s['id'] for s in members],
                'songCount': len(members),
                'facets': compact_facets,
                'contentTypes': sorted(set(s.get('contentType') or 'song' for s in members)),
                'mashupCount': sum(1 for s in members if s.get('isMashup')),
            }
            groups.append(group)
            master_groups.append({'id': group['id'], 'stylePrompt': style, 'songIds': group['songIds'], 'songCount': group['songCount'], 'facets': compact_facets, 'mashupCount': group['mashupCount']})
            for s in members:
                s['promptGroupId'] = group['id']
        master['promptGroups'] = master_groups
        master['promptGroupCount'] = len(master_groups)
    return groups


def build_groups(songs, stems_by_parent):
    groups = []
    def add_group(kind, key, members):
        if len(members) < 1:
            return
        groups.append({'id': hashlib.sha1(f'{kind}:{key}'.encode()).hexdigest()[:12], 'kind': kind, 'key': key, 'songIds': sorted(members), 'count': len(members)})
    by_lyrics = defaultdict(list)
    by_title = defaultdict(list)
    by_facet = defaultdict(list)
    for s in songs:
        if s['lyricsFingerprint']:
            by_lyrics[s['lyricsFingerprint']].append(s['id'])
        by_title[normalize_text(basename_without_stem_suffix(s['title']))].append(s['id'])
        for kind in ['themes', 'instruments', 'mood', 'message']:
            for v in s['facets'].get(kind, []):
                by_facet[(kind, v)].append(s['id'])
    for k, ids in by_lyrics.items():
        if len(ids) > 1: add_group('lyrics', k, ids)
    for k, ids in by_title.items():
        if len(ids) > 1 and k: add_group('variations', k, ids)
    for (kind, val), ids in by_facet.items():
        add_group(kind, val, ids)
    for parent, stem_list in stems_by_parent.items():
        if parent:
            add_group('stems', parent, [parent])
    return groups


def build_similarities(songs):
    by_title = defaultdict(list)
    for s in songs:
        key = normalize_text(basename_without_stem_suffix(s['title']))
        if key:
            by_title[key].append(s)
    pairs = {}
    # Exact title/variation groups first.
    for members in by_title.values():
        for i in range(len(members)):
            for j in range(i+1, len(members)):
                a, b = members[i], members[j]
                pairs[tuple(sorted([a['id'], b['id']]))] = {'songA': a['id'], 'songB': b['id'], 'score': 1.0, 'reason': 'same normalized title'}
    # Conservative token similarity within same first letter bucket to avoid O(n^2) explosion.
    buckets = defaultdict(list)
    for s in songs:
        buckets[normalize_text(s['title'])[:1]].append(s)
    song_tokens = {s['id']: tokens(s['prompt'] + ' ' + s['tags']) for s in songs}
    for members in buckets.values():
        for i in range(min(len(members), 250)):
            for j in range(i+1, min(len(members), 250)):
                a, b = members[i], members[j]
                score = jaccard(song_tokens[a['id']], song_tokens[b['id']])
                if score >= 0.35:
                    key = tuple(sorted([a['id'], b['id']]))
                    pairs.setdefault(key, {'songA': a['id'], 'songB': b['id'], 'score': round(score, 3), 'reason': 'prompt/tag token overlap'})
    return sorted(pairs.values(), key=lambda x: x['score'], reverse=True)[:5000]


def facet_summary(songs):
    out = {}
    for kind in ['themes', 'instruments', 'mood', 'message']:
        c = Counter()
        for s in songs:
            c.update(s.get('facets', {}).get(kind, []))
        out[kind] = [{'name': k, 'count': v} for k, v in c.most_common()]
    out['models'] = [{'name': k or 'unknown', 'count': v} for k, v in Counter(s.get('model') for s in songs).most_common()]
    return out


def write_outputs(registry, project_root=DEFAULT_PROJECT):
    project_root = pathlib.Path(project_root)
    data_dir = project_root / 'data'
    data_dir.mkdir(parents=True, exist_ok=True)
    json_path = data_dir / 'registry.json'
    db_path = data_dir / 'hapa_registry.sqlite'
    json_path.write_text(json.dumps(registry, ensure_ascii=False), encoding='utf-8')
    write_sqlite(registry, db_path)
    return json_path, db_path


def write_sqlite(registry, db_path):
    if db_path.exists():
        db_path.unlink()
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.executescript('''
    create table songs(id text primary key, title text, created_at text, duration real, model text, model_version text, local_path text, audio_url text, image_url text, prompt text, lyrics text, tags text, lyrics_fingerprint text, lyric_master_id text, prompt_group_id text, style_prompt text, style_prompt_fingerprint text, content_type text, is_mashup integer, source_ids_json text, stem_count integer, authors_json text, raw_json text);
    create table stems(id text primary key, parent_id text, stem_type text, title text, duration real, model text, local_path text, audio_url text, lyrics_fingerprint text, lyric_master_id text, authors_json text, raw_json text);
    create table external_lyrics(id text primary key, title text, path text, lyrics text, lyrics_fingerprint text, lyric_master_id text);
    create table lyric_masters(id text primary key, lyrics_fingerprint text unique, source_title text, lyrics text, authors_json text, variation_count integer);
    create table prompt_groups(id text primary key, lyric_master_id text, style_prompt_fingerprint text, style_prompt text, song_count integer, facets_json text, content_types_json text, mashup_count integer, song_ids_json text);
    create table mashups(song_id text primary key, content_type text, source_ids_json text, metadata_json text);
    create table lyric_variations(lyric_master_id text, variation_kind text, variation_id text, title text, parent_id text, path text, metadata_json text, primary key(lyric_master_id, variation_kind, variation_id));
    create table authors(id text primary key, name text unique);
    create table song_authors(song_id text, author_id text, role text, primary key(song_id, author_id, role));
    create table stem_authors(stem_id text, author_id text, role text, primary key(stem_id, author_id, role));
    create table events(id text primary key, subject_type text, subject_id text, event_type text, event_at text, data_json text);
    create table rename_history(id text primary key, subject_type text, subject_id text, old_title text, new_title text, renamed_at text, event_id text);
    create table loops(id text primary key, song_id text, stem_id text, lyric_master_id text, loop_type text, start_seconds real, end_seconds real, metadata_json text);
    create table derivatives(id text primary key, parent_type text, parent_id text, child_type text, child_id text, relation text, created_at text, metadata_json text);
    create table engagements(id text primary key, subject_type text, subject_id text, platform text, metric text, value real, recorded_at text, metadata_json text);
    create table lyric_lines(song_id text, line_index integer, section_index integer, section_label text, text text, start real, end real, timestamp text, confidence real, primary key(song_id,line_index));
    create table lyric_sections(song_id text, section_index integer, label text, start real, end real, timestamp text, line_start integer, line_end integer, confidence real, primary key(song_id,section_index));
    create table lyric_timing_runs(song_id text primary key, version integer, method text, source text, source_path text, analyzed_at text, confidence real, warnings_json text, stats_json text);
    create table audio_telemetry_runs(song_id text primary key, run_id text, status text, confidence real, created_at text, updated_at text, duration real, bpm real, tempo_confidence real, hook_count integer, section_count integer, beat_count integer, bar_count integer, summary_json text, manifest_path text, run_path text, warnings_json text, provenance_json text);
    create table audio_telemetry_events(song_id text, run_id text, event_id text, event_type text, label text, start real, end real, confidence real, score real, source text, reasons_json text, metadata_json text, primary key(song_id, run_id, event_id));
    create table audio_telemetry_queue_jobs(id text primary key, song_id text, title text, status text, priority integer, attempts integer, updated_at text, analysis_key text, last_error text, source_json text);
    create table facets(song_id text, kind text, value text);
    create table groups(id text primary key, kind text, key text, count integer, song_ids_json text);
    create table similarities(song_a text, song_b text, score real, reason text);
    create index idx_songs_title on songs(title);
    create index idx_stems_parent on stems(parent_id);
    create index idx_facets_kind_value on facets(kind, value);
    create index idx_lyric_variations_master on lyric_variations(lyric_master_id);
    create index idx_prompt_groups_master on prompt_groups(lyric_master_id);
    create index idx_songs_prompt_group on songs(prompt_group_id);
    create index idx_songs_content_type on songs(content_type);
    create index idx_events_subject on events(subject_type, subject_id);
    create index idx_audio_telemetry_events_type on audio_telemetry_events(event_type);
    create index idx_audio_telemetry_events_song_type on audio_telemetry_events(song_id, event_type);
    ''')
    generated_at = registry.get('generatedAt')
    for author in DEFAULT_AUTHORS:
        cur.execute('insert into authors values(?,?)', (stable_id('author', author), author))
    author_ids = {name: stable_id('author', name) for name in DEFAULT_AUTHORS}
    for m in registry.get('lyricMasters', []):
        cur.execute('insert into lyric_masters values(?,?,?,?,?,?)', (m['id'], m.get('lyricsFingerprint'), m.get('sourceTitle'), m.get('lyrics'), json.dumps(m.get('authors', []), ensure_ascii=False), m.get('variationCount', 0)))
        for v in m.get('variations', []):
            cur.execute('insert into lyric_variations values(?,?,?,?,?,?,?)', (m['id'], v.get('kind'), v.get('id'), v.get('title'), v.get('parentId'), v.get('path'), json.dumps(v, ensure_ascii=False)))
    for pg in registry.get('promptGroups', []):
        cur.execute('insert into prompt_groups values(?,?,?,?,?,?,?,?,?)', (pg['id'], pg.get('lyricMasterId'), pg.get('stylePromptFingerprint'), pg.get('stylePrompt'), pg.get('songCount', 0), json.dumps(pg.get('facets', {}), ensure_ascii=False), json.dumps(pg.get('contentTypes', []), ensure_ascii=False), pg.get('mashupCount', 0), json.dumps(pg.get('songIds', []), ensure_ascii=False)))
    for doc in registry.get('externalLyrics', []):
        cur.execute('insert into external_lyrics values(?,?,?,?,?,?)', (doc['id'], doc.get('title'), doc.get('path'), doc.get('lyrics'), doc.get('lyricsFingerprint'), doc.get('lyricMasterId')))
    for s in registry['songs']:
        cur.execute('insert into songs values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (s['id'], s['title'], s.get('createdAt'), s.get('duration'), s.get('model'), s.get('majorModelVersion'), s.get('localPath'), s.get('audioUrl'), s.get('imageUrl'), s.get('prompt'), s.get('lyrics'), s.get('tags'), s.get('lyricsFingerprint'), s.get('lyricMasterId'), s.get('promptGroupId'), s.get('stylePrompt'), s.get('stylePromptFingerprint'), s.get('contentType'), 1 if s.get('isMashup') else 0, json.dumps(s.get('mashupSourceIds', []), ensure_ascii=False), s.get('stemCount', 0), json.dumps(s.get('authors', []), ensure_ascii=False), json.dumps(s.get('raw', {}), ensure_ascii=False)))
        if s.get('isMashup'):
            cur.execute('insert into mashups values(?,?,?,?)', (s['id'], s.get('contentType'), json.dumps(s.get('mashupSourceIds', []), ensure_ascii=False), json.dumps({'title': s.get('title'), 'stylePrompt': s.get('stylePrompt')}, ensure_ascii=False)))
        for author in s.get('authors', DEFAULT_AUTHORS):
            cur.execute('insert or ignore into song_authors values(?,?,?)', (s['id'], author_ids.get(author, stable_id('author', author)), 'author'))
        cur.execute('insert into events values(?,?,?,?,?,?)', (stable_id('event', 'song', s['id'], 'created'), 'song', s['id'], 'created', s.get('createdAt') or generated_at, json.dumps({'title': s.get('title')}, ensure_ascii=False)))
        timing = s.get('lyricTiming')
        if timing:
            cur.execute('insert into lyric_timing_runs values(?,?,?,?,?,?,?,?,?)', (s['id'], timing.get('version'), timing.get('method'), timing.get('source'), timing.get('sourcePath'), timing.get('analyzedAt'), timing.get('confidence'), json.dumps(timing.get('warnings', []), ensure_ascii=False), json.dumps(timing.get('stats', {}), ensure_ascii=False)))
            for line in timing.get('lines', []):
                cur.execute('insert into lyric_lines values(?,?,?,?,?,?,?,?,?)', (s['id'], line.get('index'), line.get('sectionIndex'), line.get('section'), line.get('text'), line.get('start'), line.get('end'), line.get('timestamp'), line.get('confidence')))
            for sec in timing.get('sections', []):
                cur.execute('insert into lyric_sections values(?,?,?,?,?,?,?,?,?)', (s['id'], sec.get('index'), sec.get('label'), sec.get('start'), sec.get('end'), sec.get('timestamp'), sec.get('lineStart'), sec.get('lineEnd'), sec.get('confidence')))
        telemetry = s.get('audioTelemetry')
        if telemetry:
            summary = telemetry.get('summary') or {}
            cur.execute('insert into audio_telemetry_runs values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (
                s['id'], telemetry.get('latestRunId'), telemetry.get('status'), telemetry.get('confidence'), None, telemetry.get('updatedAt'), s.get('duration'), summary.get('bpm'), summary.get('tempoConfidence'), summary.get('hookCount'), summary.get('sectionCount'), summary.get('beatCount'), summary.get('barCount'), json.dumps(summary, ensure_ascii=False), telemetry.get('manifestPath'), telemetry.get('runPath') or telemetry.get('timelinePath'), json.dumps(telemetry.get('warnings', []), ensure_ascii=False), json.dumps({'source': 'registry_manifest'}, ensure_ascii=False)
            ))
            latest_path = telemetry.get('timelinePath') or telemetry.get('runPath')
            try:
                run_doc = json.loads(pathlib.Path(latest_path).read_text(encoding='utf-8')) if latest_path and pathlib.Path(latest_path).exists() else {}
                for ev in (run_doc.get('timeline') or {}).get('events', []):
                    cur.execute('insert or replace into audio_telemetry_events values(?,?,?,?,?,?,?,?,?,?,?,?)', (s['id'], telemetry.get('latestRunId'), ev.get('id') or stable_id('audioevt', s['id'], ev.get('type'), ev.get('start')), ev.get('type'), ev.get('label'), ev.get('start'), ev.get('end'), ev.get('confidence'), ev.get('score'), ev.get('source'), json.dumps(ev.get('reasons', []), ensure_ascii=False), json.dumps(ev, ensure_ascii=False)))
            except Exception:
                pass
        for kind, vals in s.get('facets', {}).items():
            for val in vals:
                cur.execute('insert into facets values(?,?,?)', (s['id'], kind, val))
    for st in registry['stems']:
        cur.execute('insert into stems values(?,?,?,?,?,?,?,?,?,?,?,?)', (st['id'], st.get('parentId'), st.get('stemType'), st.get('title'), st.get('duration'), st.get('model'), st.get('localPath'), st.get('audioUrl'), st.get('lyricsFingerprint'), st.get('lyricMasterId'), json.dumps(st.get('authors', []), ensure_ascii=False), json.dumps(st.get('raw', {}), ensure_ascii=False)))
        for author in st.get('authors', DEFAULT_AUTHORS):
            cur.execute('insert or ignore into stem_authors values(?,?,?)', (st['id'], author_ids.get(author, stable_id('author', author)), 'author'))
        cur.execute('insert into events values(?,?,?,?,?,?)', (stable_id('event', 'stem', st['id'], 'created'), 'stem', st['id'], 'created', st.get('createdAt') or generated_at, json.dumps({'title': st.get('title'), 'parentId': st.get('parentId')}, ensure_ascii=False)))
        if st.get('parentId'):
            cur.execute('insert into derivatives values(?,?,?,?,?,?,?,?)', (stable_id('derivative', st.get('parentId'), st['id']), 'song', st.get('parentId'), 'stem', st['id'], st.get('stemType') or 'stem', generated_at, json.dumps({}, ensure_ascii=False)))
    for g in registry['groups']:
        cur.execute('insert into groups values(?,?,?,?,?)', (g['id'], g['kind'], g['key'], g['count'], json.dumps(g['songIds'])))
    for sim in registry['similarities']:
        cur.execute('insert into similarities values(?,?,?,?)', (sim['songA'], sim['songB'], sim['score'], sim['reason']))
    con.commit(); con.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--library', default=str(DEFAULT_LIBRARY))
    parser.add_argument('--project', default=str(DEFAULT_PROJECT))
    parser.add_argument('--lyrics-root', action='append', dest='lyric_roots', help='External lyric folder (.md/.docx). May be repeated. Defaults to Desktop/Hapa Song Lyrics and Desktop/Hapa Song Library.')
    args = parser.parse_args()
    registry = build_registry(args.library, args.project, lyric_roots=args.lyric_roots)
    json_path, db_path = write_outputs(registry, args.project)
    print(f'Wrote {json_path}')
    print(f'Wrote {db_path}')
    print(json.dumps(registry['counts'], indent=2))

if __name__ == '__main__':
    main()
