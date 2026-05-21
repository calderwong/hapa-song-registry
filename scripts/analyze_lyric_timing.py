#!/usr/bin/env python3
import argparse
import json
import math
import pathlib
import re
import sqlite3
import subprocess
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
REGISTRY = ROOT / 'data' / 'registry.json'
DB = ROOT / 'data' / 'hapa_registry.sqlite'
TIMING_DIR = ROOT / 'data' / 'lyric_timings'
FFMPEG = '/opt/homebrew/bin/ffmpeg'
SR = 11025
FRAME = 2048
HOP = 1024


def fmt_time(seconds):
    seconds = max(0.0, float(seconds or 0.0))
    m = int(seconds // 60)
    s = seconds - 60 * m
    return f'{m}:{s:05.2f}'


def line_weight(text):
    text = str(text or '').strip()
    words = re.findall(r"[A-Za-z0-9']+", text)
    if not words:
        return 1.0
    syllables = 0
    for word in words:
        groups = re.findall(r'[aeiouyAEIOUY]+', word)
        syllables += max(1, len(groups))
    pause = 0.0
    pause += 0.7 * text.count('…')
    pause += 0.4 * text.count('—')
    pause += 0.15 * (text.count(',') + text.count(';') + text.count(':'))
    if len(words) <= 2:
        return max(0.9, min(2.2, syllables * 0.65 + pause))
    return max(1.0, min(12.0, syllables * 0.78 + pause))


def cumulative_to_time(x, phrases, fallback_start, fallback_end):
    if not phrases:
        return fallback_start + x * max(0.1, fallback_end - fallback_start)
    lengths = [max(0.05, b - a) for a, b in phrases]
    total = sum(lengths)
    target = max(0.0, min(1.0, x)) * total
    acc = 0.0
    for (start, end), length in zip(phrases, lengths):
        if acc + length >= target:
            return start + (target - acc) / length * (end - start)
        acc += length
    return phrases[-1][1]


def map_lines_to_phrases(lines, sections, phrases, duration, source, warnings=None):
    warnings = warnings or []
    if not lines:
        return {'version': 1, 'method': 'no_lyrics', 'source': source, 'duration': duration, 'confidence': 0, 'warnings': ['no lyric lines'], 'stats': {}, 'sections': [], 'lines': []}
    phrases = [(max(0.0, float(a)), min(float(duration), float(b))) for a, b in phrases if b > a]
    if phrases:
        first, last = phrases[0][0], phrases[-1][1]
        method = 'audio_phrase_weighted'
    else:
        first, last = max(0.0, duration * 0.06), max(duration * 0.94, duration - 1.0)
        method = 'weighted_even_fallback'
        warnings.append('no reliable vocal phrase intervals detected')
    weights = [line_weight(line['text']) for line in lines]
    total = sum(weights) or len(lines)
    lyric_lines = []
    acc = 0.0
    for i, line in enumerate(lines):
        start = cumulative_to_time(acc / total, phrases, first, last)
        acc += weights[i]
        end = cumulative_to_time(acc / total, phrases, first, last)
        if i < len(lines) - 1:
            next_start = cumulative_to_time(acc / total, phrases, first, last)
            end = min(end, next_start)
        if end - start < 0.45:
            end = min(duration, start + 0.45)
        lyric_lines.append({
            'index': line['index'],
            'sectionIndex': line.get('sectionIndex', 0),
            'section': line.get('section', 'Lyrics'),
            'text': line['text'],
            'start': round(start, 3),
            'end': round(end, 3),
            'timestamp': fmt_time(start),
            'duration': round(max(0.0, end - start), 3),
            'confidence': 0.72 if phrases else 0.35,
        })
    timed_sections = []
    for sec in sections:
        sec_lines = [line for line in lyric_lines if line.get('sectionIndex') == sec.get('index')]
        if sec_lines:
            timed_sections.append({
                'index': sec.get('index'),
                'label': sec.get('label', 'Lyrics'),
                'start': sec_lines[0]['start'],
                'end': sec_lines[-1]['end'],
                'timestamp': fmt_time(sec_lines[0]['start']),
                'lineStart': sec_lines[0]['index'],
                'lineEnd': sec_lines[-1]['index'],
                'confidence': round(sum(l['confidence'] for l in sec_lines) / len(sec_lines), 3),
            })
    confidence = 0.72 if phrases else 0.35
    if len(phrases) < max(3, len(lines) // 8):
        confidence -= 0.08
        warnings.append('few phrase intervals relative to lyric length')
    return {
        'version': 1,
        'method': method,
        'source': source,
        'analyzedAt': datetime.utcnow().isoformat() + 'Z',
        'duration': round(float(duration), 3),
        'confidence': round(max(0.1, min(0.95, confidence)), 3),
        'warnings': sorted(set(warnings)),
        'stats': {'lineCount': len(lines), 'sectionCount': len(timed_sections), 'phraseCount': len(phrases), 'firstVocal': round(first, 3), 'lastVocal': round(last, 3), 'vocalCoverage': round(sum(b-a for a,b in phrases) / max(1.0, duration), 3)},
        'sections': timed_sections,
        'lines': lyric_lines,
    }


def decode_audio(path):
    cmd = [FFMPEG, '-v', 'error', '-i', str(path), '-ac', '1', '-ar', str(SR), '-f', 'f32le', '-']
    raw = subprocess.check_output(cmd)
    audio = np.frombuffer(raw, dtype=np.float32)
    if audio.size == 0:
        raise RuntimeError('decoded audio is empty')
    audio = np.nan_to_num(audio)
    peak = np.max(np.abs(audio)) or 1.0
    if peak > 0:
        audio = audio / peak
    return audio


def frame_rms(audio):
    if len(audio) < FRAME:
        return np.array([float(np.sqrt(np.mean(audio * audio)))])
    n = 1 + (len(audio) - FRAME) // HOP
    shape = (n, FRAME)
    strides = (audio.strides[0] * HOP, audio.strides[0])
    frames = np.lib.stride_tricks.as_strided(audio, shape=shape, strides=strides)
    return np.sqrt(np.mean(frames * frames, axis=1) + 1e-12)


def smooth(x, width=9):
    if len(x) < width:
        return x
    kernel = np.ones(width) / width
    return np.convolve(x, kernel, mode='same')


def detect_phrases(audio, duration, is_vocal_stem=False):
    rms = smooth(frame_rms(audio), 11)
    log = 20 * np.log10(rms + 1e-6)
    p20, p88, p95 = np.percentile(log, [20, 88, 95])
    if is_vocal_stem:
        threshold = p20 + 0.22 * (p95 - p20)
    else:
        threshold = p20 + 0.34 * (p95 - p20)
    active = log > threshold
    # Remove very quiet tails and close small gaps.
    max_gap_frames = max(1, int(0.70 * SR / HOP))
    min_phrase_frames = max(1, int(0.45 * SR / HOP))
    active = close_gaps(active, max_gap_frames)
    intervals = boolean_intervals(active)
    phrases = []
    for a, b in intervals:
        if b - a < min_phrase_frames:
            continue
        start = a * HOP / SR
        end = min(duration, (b * HOP + FRAME) / SR)
        if end - start >= 0.45:
            phrases.append((start, end))
    # Split very long regions at energy valleys.
    split = []
    for start, end in phrases:
        if end - start <= 10.0:
            split.append((start, end)); continue
        split.extend(split_long_phrase(start, end, log))
    if not split:
        return []
    # Trim microscopic overlaps and guarantee monotonic.
    out = []
    for start, end in split:
        start = max(0.0, min(duration, start)); end = max(start + 0.1, min(duration, end))
        if out and start < out[-1][1]:
            start = out[-1][1]
        if end - start >= 0.35:
            out.append((start, end))
    return out


def close_gaps(active, max_gap):
    active = active.copy()
    i = 0
    while i < len(active):
        if active[i]:
            i += 1; continue
        j = i
        while j < len(active) and not active[j]:
            j += 1
        if i > 0 and j < len(active) and j - i <= max_gap:
            active[i:j] = True
        i = j
    return active


def boolean_intervals(active):
    intervals = []
    i = 0
    while i < len(active):
        if not active[i]:
            i += 1; continue
        j = i
        while j < len(active) and active[j]:
            j += 1
        intervals.append((i, j)); i = j
    return intervals


def split_long_phrase(start, end, log):
    start_frame = int(start * SR / HOP)
    end_frame = min(len(log), int(end * SR / HOP))
    duration = end - start
    pieces = max(2, int(round(duration / 5.5)))
    candidates = []
    for k in range(1, pieces):
        target = start_frame + int((end_frame - start_frame) * k / pieces)
        lo = max(start_frame, target - int(1.0 * SR / HOP))
        hi = min(end_frame, target + int(1.0 * SR / HOP))
        if hi > lo:
            valley = lo + int(np.argmin(log[lo:hi]))
            candidates.append(valley * HOP / SR)
    bounds = [start] + sorted(candidates) + [end]
    return [(bounds[i], bounds[i+1]) for i in range(len(bounds)-1) if bounds[i+1] - bounds[i] >= 0.45]


def choose_timing_source(song, stems):
    vocal = [s for s in stems if s.get('parentId') == song['id'] and s.get('localPath') and s.get('stemType') == 'Vocals']
    if vocal:
        return vocal[0]['localPath'], 'vocals_stem', True
    return song.get('localPath'), 'full_mix', False


def analyze_song(args):
    song, stems = args
    parse = song.get('lyricParse') or {}
    lines = parse.get('lines') or [{'index': i, 'sectionIndex': 0, 'section': 'Lyrics', 'text': t} for i, t in enumerate((song.get('lyrics') or '').split('\n')) if t.strip()]
    sections = parse.get('sections') or [{'index': 0, 'label': 'Lyrics', 'lineStart': 0, 'lineEnd': max(0, len(lines)-1)}]
    if not lines:
        return song['id'], None
    source_path, source, is_vocal = choose_timing_source(song, stems)
    warnings = []
    phrases = []
    duration = float(song.get('duration') or 0.0)
    try:
        audio = decode_audio(source_path)
        decoded_duration = len(audio) / SR
        if decoded_duration > 0:
            duration = decoded_duration
        phrases = detect_phrases(audio, duration, is_vocal)
    except Exception as e:
        warnings.append(f'audio analysis failed: {type(e).__name__}: {e}')
    timing = map_lines_to_phrases(lines, sections, phrases, duration, source, warnings)
    timing['sourcePath'] = source_path
    return song['id'], timing


def update_sqlite(registry, db_path):
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.executescript('''
    drop table if exists lyric_lines;
    drop table if exists lyric_sections;
    drop table if exists lyric_timing_runs;
    create table lyric_lines(song_id text, line_index integer, section_index integer, section_label text, text text, start real, end real, timestamp text, confidence real, primary key(song_id,line_index));
    create table lyric_sections(song_id text, section_index integer, label text, start real, end real, timestamp text, line_start integer, line_end integer, confidence real, primary key(song_id,section_index));
    create table lyric_timing_runs(song_id text primary key, version integer, method text, source text, source_path text, analyzed_at text, confidence real, warnings_json text, stats_json text);
    create index if not exists idx_lyric_lines_time on lyric_lines(song_id,start,end);
    ''')
    for song in registry['songs']:
        timing = song.get('lyricTiming')
        if not timing:
            continue
        cur.execute('insert into lyric_timing_runs values(?,?,?,?,?,?,?,?,?)', (song['id'], timing.get('version'), timing.get('method'), timing.get('source'), timing.get('sourcePath'), timing.get('analyzedAt'), timing.get('confidence'), json.dumps(timing.get('warnings', [])), json.dumps(timing.get('stats', {}))))
        for line in timing.get('lines', []):
            cur.execute('insert into lyric_lines values(?,?,?,?,?,?,?,?,?)', (song['id'], line['index'], line.get('sectionIndex'), line.get('section'), line.get('text'), line.get('start'), line.get('end'), line.get('timestamp'), line.get('confidence')))
        for sec in timing.get('sections', []):
            cur.execute('insert into lyric_sections values(?,?,?,?,?,?,?,?,?)', (song['id'], sec.get('index'), sec.get('label'), sec.get('start'), sec.get('end'), sec.get('timestamp'), sec.get('lineStart'), sec.get('lineEnd'), sec.get('confidence')))
    con.commit(); con.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--registry', default=str(REGISTRY))
    parser.add_argument('--db', default=str(DB))
    parser.add_argument('--workers', type=int, default=6)
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--song-id', default='')
    args = parser.parse_args()
    path = pathlib.Path(args.registry)
    registry = json.loads(path.read_text())
    songs = [s for s in registry['songs'] if s.get('lyrics') and s.get('localPath')]
    if args.song_id:
        songs = [s for s in songs if s['id'] == args.song_id]
    if args.limit:
        songs = songs[:args.limit]
    stems = registry.get('stems', [])
    TIMING_DIR.mkdir(parents=True, exist_ok=True)
    print(f'Analyzing lyric timing for {len(songs)} songs with {args.workers} workers')
    timings = {}
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(analyze_song, (song, stems)): song for song in songs}
        for i, fut in enumerate(as_completed(futs), 1):
            song_id, timing = fut.result()
            if timing:
                timings[song_id] = timing
                (TIMING_DIR / f'{song_id}.json').write_text(json.dumps(timing, ensure_ascii=False), encoding='utf-8')
            if i % 25 == 0 or i == len(songs):
                print(f'  {i}/{len(songs)} complete')
    for song in registry['songs']:
        if song['id'] in timings:
            song['lyricTiming'] = timings[song['id']]
    registry['counts']['lyricTimings'] = len([s for s in registry['songs'] if s.get('lyricTiming')])
    registry['generatedAt'] = datetime.utcnow().isoformat() + 'Z'
    path.write_text(json.dumps(registry, ensure_ascii=False), encoding='utf-8')
    update_sqlite(registry, pathlib.Path(args.db))
    print(f'Updated {path}')
    print(f'Updated {args.db}')
    print(f'Lyric timings: {registry["counts"]["lyricTimings"]}')

if __name__ == '__main__':
    main()
