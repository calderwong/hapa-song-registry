# Hapa Song Registry Audio Telemetry Analysis Architecture

Status: proposed design
Repository: `$HAPA_SONG_REGISTRY_ROOT`
Primary data root: `$HAPA_SONG_REGISTRY_ROOT/data`

## Goal

Add an analyze-once/use-many audio telemetry layer for Hapa Song Registry. Each song is queued for offline analysis exactly when needed, outputs are persisted as per-song JSON and SQLite rows, and downstream consumers can read stable summaries/events without repeatedly decoding audio.

The layer complements the existing registry outputs:

- `data/registry.json` remains the broad app cache.
- `data/hapa_registry.sqlite` remains the query/index store.
- `data/lyric_timings/*.json` remains the current lyric timing cache.
- New telemetry artifacts live under `data/audio_telemetry/` and can be merged into app/UI/API views.

## Design principles

1. Analyze once, reuse many times.
2. Per-song artifacts are immutable by run ID; “latest” is a pointer/view.
3. Queue status is durable and restartable.
4. JSON is the portable agent/human artifact; SQLite is the fast query surface.
5. Timeline events use one shared shape for hooks, peaks, beats, sections, lyric lines, drops, stems, and future annotations.
6. Every event has provenance: source audio, analyzer version, params, content hash, timestamps, and confidence.
7. The desktop app can work without an HTTP server, but a loopback API can expose the same read/write surfaces to agents/apps.

## Proposed file layout

```text
data/
  audio_telemetry/
    queue.json                         # durable lightweight queue state
    manifests/
      <song_id>.json                   # latest run pointer + quick summary
    runs/
      <song_id>/
        <run_id>.json                  # complete normalized telemetry artifact
        <run_id>.peaks.json            # optional dense peak/envelope payload
        <run_id>.beats.json            # optional dense beat grid payload
    latest/
      <song_id>.json                   # copy/symlink of latest complete artifact
    exports/
      hooks.jsonl                      # optional agent-friendly projections
      sections.jsonl
      high_confidence_events.jsonl
```

Recommended `run_id` format:

```text
atr_<YYYYMMDDTHHMMSSZ>_<short_audio_sha256>_<analyzer_semver>
```

Example:

```text
atr_20260526T210533Z_a13f92bc_v1_0_0
```

## Queue architecture

### Queue lifecycle

1. Discover songs from `registry.json` / SQLite.
2. For each song, compute an analysis key:
   - `song_id`
   - source audio path
   - source audio size/mtime/hash when available
   - selected stem paths and hashes when available
   - analyzer name/version
   - parameter hash
3. If latest manifest has a matching key and required outputs, skip.
4. Otherwise enqueue a job.
5. Worker claims one job at a time or N jobs with a process pool.
6. Worker writes run JSON to a temp file, validates it, commits to final path, then updates SQLite and manifest in one transaction-like sequence.
7. Queue marks job complete/failed/skipped.
8. Append a `history_events.json` event for operator/audit visibility.

### Queue state JSON

`data/audio_telemetry/queue.json`:

```json
{
  "schemaVersion": 1,
  "mode": "stopped",
  "activeJobIds": [],
  "createdAt": "2026-05-26T21:05:33Z",
  "updatedAt": "2026-05-26T21:05:33Z",
  "defaults": {
    "analyzer": "hapa-audio-telemetry",
    "analyzerVersion": "1.0.0",
    "requiredKinds": ["summary", "peaks", "beats", "sections", "hooks"],
    "overwrite": false
  },
  "telemetry": {
    "queued": 0,
    "running": 0,
    "completed": 0,
    "failed": 0,
    "skipped": 0
  },
  "queue": [
    {
      "id": "job_8b0b9f2e",
      "songId": "97cd5415-3eb8-41c5-b289-96c4573460c4",
      "title": "PipasaySenpai Yippee x Bounce",
      "status": "queued",
      "priority": 50,
      "attempts": 0,
      "maxAttempts": 3,
      "createdAt": "2026-05-26T21:05:33Z",
      "updatedAt": "2026-05-26T21:05:33Z",
      "sourceAudio": {
        "path": "$HAPA_SUNO_LIBRARY_ROOT/.../song.mp3",
        "sha256": null,
        "sizeBytes": 12345678,
        "mtime": "2026-05-26T02:19:16Z"
      },
      "inputRefs": {
        "registryGeneratedAt": "2026-05-26T19:22:49.237196Z",
        "lyricTimingRunId": null,
        "vocalStemPath": null,
        "musicStemPath": null
      },
      "analysisKey": "sha256:...",
      "params": {
        "sampleRate": 22050,
        "hopLength": 512,
        "peakWindowMs": 50,
        "beatTracker": "librosa|aubio|internal",
        "sectionMethod": "novelty+lyrics+energy",
        "hookMethod": "repetition+energy+lyric_chorus"
      },
      "lastError": null
    }
  ]
}
```

Queue statuses:

- `queued`: ready for a worker.
- `claimed`: worker has lease but has not started decoding.
- `running`: analysis in progress.
- `writing`: artifacts are being committed.
- `completed`: manifest/JSON/SQLite complete.
- `skipped`: latest artifact already satisfies analysis key.
- `failed`: final failure after max attempts.
- `blocked`: missing audio, unreadable file, no ffmpeg, or dependency unavailable.

Worker lease fields should include `workerId`, `claimedAt`, and `leaseExpiresAt` so crashes can be recovered.

## Per-song telemetry artifact

`data/audio_telemetry/runs/<song_id>/<run_id>.json` is the canonical complete output.

Top-level shape:

```json
{
  "schemaVersion": 1,
  "kind": "hapa.audioTelemetry.run",
  "runId": "atr_20260526T210533Z_a13f92bc_v1_0_0",
  "songId": "97cd5415-3eb8-41c5-b289-96c4573460c4",
  "title": "PipasaySenpai Yippee x Bounce",
  "createdAt": "2026-05-26T21:05:33Z",
  "updatedAt": "2026-05-26T21:06:10Z",
  "duration": 232.52,
  "status": "complete",
  "confidence": 0.82,
  "summary": {
    "bpm": 92.1,
    "tempoConfidence": 0.81,
    "key": "A minor",
    "keyConfidence": 0.55,
    "loudnessIntegratedLufs": -10.8,
    "rmsMean": 0.134,
    "rmsPeak": 0.911,
    "peakDbfs": -0.4,
    "dynamicRange": 8.7,
    "vocalCoverage": 0.63,
    "energyArc": "intro_build_chorus_drop_bridge_finale",
    "hookCount": 3,
    "sectionCount": 8,
    "beatCount": 357,
    "barCount": 89
  },
  "timeline": {
    "timebase": "seconds",
    "events": []
  },
  "tracks": [],
  "features": {},
  "provenance": {},
  "warnings": [],
  "errors": []
}
```

### Timeline event schema

All timeline annotations share one event table/array shape. This is the most important downstream contract.

```json
{
  "id": "evt_hook_0003",
  "songId": "97cd5415-3eb8-41c5-b289-96c4573460c4",
  "runId": "atr_20260526T210533Z_a13f92bc_v1_0_0",
  "kind": "hook",
  "label": "Chorus hook: Bounce",
  "start": 44.128,
  "end": 61.772,
  "duration": 17.644,
  "timebase": "seconds",
  "confidence": 0.88,
  "rank": 1,
  "importance": 0.96,
  "source": "detector:hook_repetition_energy_v1",
  "sourceRefs": {
    "lyricLineIds": [12, 13, 14],
    "sectionIds": ["evt_section_0002"],
    "beatIds": ["evt_beat_0068", "evt_beat_0096"]
  },
  "features": {
    "energyMean": 0.74,
    "energyPeak": 0.93,
    "novelty": 0.62,
    "repetitionScore": 0.91,
    "vocalPresence": 0.84,
    "spectralCentroid": 2840.5
  },
  "tags": ["chorus", "repeat", "candidate_clip"],
  "metadata": {
    "lyricText": "Bounce, bounce, bounce",
    "barStart": 17,
    "barEnd": 24
  }
}
```

Required fields for every event:

- `id`: stable within run.
- `songId`
- `runId`
- `kind`
- `start`
- `end`
- `confidence`
- `source`

Recommended event kinds:

- `beat`: individual beat timestamps.
- `bar`: grouped beats according to meter.
- `downbeat`: bar start marker when known.
- `peak`: local amplitude/energy peak.
- `energy_region`: high/low/transition energy span.
- `section`: intro, verse, prechorus, chorus, bridge, drop, outro, instrumental, spoken, unknown.
- `hook`: repeated or high-importance musical/lyric phrase.
- `drop`: strong onset/energy release.
- `break`: silence, pause, or sparse arrangement.
- `lyric_line`: copied/linked from lyric timing analysis.
- `phrase`: vocal phrase interval from existing timing logic.
- `stem_activity`: activity span on vocals/music/stems.
- `loop_candidate`: suggested loop/clip range for DAW/media workflows.
- `manual_annotation`: human-entered event.

### Event examples

Beat:

```json
{
  "id": "evt_beat_0001",
  "kind": "beat",
  "label": "beat 1",
  "start": 0.652,
  "end": 0.652,
  "confidence": 0.76,
  "source": "detector:beat_tracker_v1",
  "metadata": { "beatIndex": 1, "barIndex": 1, "positionInBar": 1, "bpmLocal": 92.0 }
}
```

Peak:

```json
{
  "id": "evt_peak_0042",
  "kind": "peak",
  "label": "energy peak",
  "start": 72.42,
  "end": 72.92,
  "confidence": 0.84,
  "importance": 0.79,
  "source": "detector:rms_peak_v1",
  "features": { "rms": 0.91, "dbfs": -1.2, "zscore": 2.8 }
}
```

Section:

```json
{
  "id": "evt_section_0004",
  "kind": "section",
  "label": "chorus",
  "start": 62.0,
  "end": 94.1,
  "confidence": 0.73,
  "source": "detector:section_novelty_lyrics_v1",
  "metadata": { "sectionIndex": 4, "lineStart": 20, "lineEnd": 31 }
}
```

Hook:

```json
{
  "id": "evt_hook_0001",
  "kind": "hook",
  "label": "main hook",
  "start": 44.128,
  "end": 61.772,
  "confidence": 0.88,
  "rank": 1,
  "importance": 0.96,
  "source": "detector:hook_repetition_energy_v1",
  "tags": ["chorus", "clip_candidate"]
}
```

## Provenance and versioning

Every run should include this `provenance` object:

```json
{
  "registry": {
    "path": "$HAPA_SONG_REGISTRY_ROOT/data/registry.json",
    "generatedAt": "2026-05-26T19:22:49.237196Z",
    "songRecordHash": "sha256:..."
  },
  "sourceAudio": {
    "path": "$HAPA_SUNO_LIBRARY_ROOT/.../song.mp3",
    "sha256": "sha256:...",
    "sizeBytes": 12345678,
    "mtime": "2026-05-26T02:19:16Z",
    "duration": 232.52
  },
  "inputs": {
    "preferredTrack": "vocal_stem_if_available_else_full_mix",
    "tracks": [
      {
        "role": "full_mix",
        "path": "$HAPA_SUNO_LIBRARY_ROOT/.../song.mp3",
        "sha256": "sha256:..."
      },
      {
        "role": "vocals",
        "path": "$HAPA_SONG_REGISTRY_ROOT/data/ace-stems/<song_id>/vocals.wav",
        "sha256": "sha256:..."
      }
    ],
    "lyricTiming": {
      "source": "data/lyric_timings/<song_id>.json",
      "version": 1,
      "hash": "sha256:..."
    }
  },
  "analyzer": {
    "name": "hapa-audio-telemetry",
    "version": "1.0.0",
    "codeVersion": "git:<commit>",
    "command": "python3 scripts/analyze_audio_telemetry.py worker --limit 1",
    "paramsHash": "sha256:...",
    "dependencies": {
      "ffmpeg": "...",
      "numpy": "...",
      "librosa": "optional"
    }
  },
  "run": {
    "runId": "atr_20260526T210533Z_a13f92bc_v1_0_0",
    "queuedAt": "2026-05-26T21:05:33Z",
    "startedAt": "2026-05-26T21:05:35Z",
    "finishedAt": "2026-05-26T21:06:10Z",
    "workerId": "local-macbook-01"
  }
}
```

Versioning rules:

- `schemaVersion` changes only on breaking artifact/schema changes.
- `analyzer.version` changes when detector logic changes.
- `paramsHash` changes when thresholds/window sizes/models change.
- `analysisKey` is the idempotency key: source hashes + analyzer version + params hash + requested output kinds.
- Never overwrite a completed run artifact. Create a new run and move `latest` pointers.
- Keep old SQLite rows by `run_id`; mark latest in manifest or SQL view.

## SQLite schema additions

Add these tables to `data/hapa_registry.sqlite` alongside existing `songs`, `lyric_timing_runs`, `lyric_lines`, `lyric_sections`, and `events` tables.

```sql
create table if not exists audio_telemetry_runs (
  run_id text primary key,
  song_id text not null,
  schema_version integer not null,
  analyzer_name text not null,
  analyzer_version text not null,
  analysis_key text not null,
  status text not null,
  created_at text not null,
  started_at text,
  finished_at text,
  duration real,
  confidence real,
  bpm real,
  tempo_confidence real,
  musical_key text,
  key_confidence real,
  loudness_lufs real,
  peak_dbfs real,
  dynamic_range real,
  hook_count integer default 0,
  section_count integer default 0,
  beat_count integer default 0,
  event_count integer default 0,
  artifact_path text not null,
  manifest_path text,
  source_audio_path text,
  source_audio_sha256 text,
  params_json text,
  provenance_json text,
  warnings_json text,
  errors_json text,
  unique(song_id, analysis_key)
);

create index if not exists idx_audio_telemetry_runs_song on audio_telemetry_runs(song_id);
create index if not exists idx_audio_telemetry_runs_status on audio_telemetry_runs(status);
create index if not exists idx_audio_telemetry_runs_analyzer on audio_telemetry_runs(analyzer_name, analyzer_version);

create table if not exists audio_telemetry_events (
  id text not null,
  run_id text not null,
  song_id text not null,
  kind text not null,
  label text,
  start real not null,
  end real not null,
  duration real,
  confidence real,
  rank integer,
  importance real,
  source text,
  features_json text,
  tags_json text,
  metadata_json text,
  source_refs_json text,
  primary key(run_id, id),
  foreign key(run_id) references audio_telemetry_runs(run_id)
);

create index if not exists idx_audio_events_song_kind_time on audio_telemetry_events(song_id, kind, start);
create index if not exists idx_audio_events_kind_importance on audio_telemetry_events(kind, importance desc);
create index if not exists idx_audio_events_run_kind on audio_telemetry_events(run_id, kind);

create table if not exists audio_telemetry_queue_jobs (
  id text primary key,
  song_id text not null,
  status text not null,
  priority integer default 50,
  attempts integer default 0,
  max_attempts integer default 3,
  worker_id text,
  claimed_at text,
  lease_expires_at text,
  created_at text not null,
  updated_at text not null,
  started_at text,
  finished_at text,
  analysis_key text,
  params_json text,
  input_refs_json text,
  result_run_id text,
  last_error text
);

create index if not exists idx_audio_queue_status_priority on audio_telemetry_queue_jobs(status, priority desc, created_at);
create index if not exists idx_audio_queue_song on audio_telemetry_queue_jobs(song_id);
```

Useful views:

```sql
create view if not exists audio_telemetry_latest_runs as
select r.*
from audio_telemetry_runs r
join (
  select song_id, max(finished_at) as finished_at
  from audio_telemetry_runs
  where status = 'complete'
  group by song_id
) latest
on latest.song_id = r.song_id and latest.finished_at = r.finished_at;

create view if not exists audio_hook_candidates as
select e.*, s.title, r.bpm, r.confidence as run_confidence
from audio_telemetry_events e
join audio_telemetry_latest_runs r on r.run_id = e.run_id
join songs s on s.id = e.song_id
where e.kind in ('hook', 'loop_candidate')
order by e.importance desc, e.confidence desc;
```

## Registry JSON integration

Do not embed dense telemetry into `registry.json`; it is already large. Add a compact per-song pointer/summary only:

```json
{
  "id": "97cd5415-3eb8-41c5-b289-96c4573460c4",
  "title": "PipasaySenpai Yippee x Bounce",
  "audioTelemetry": {
    "status": "complete",
    "latestRunId": "atr_20260526T210533Z_a13f92bc_v1_0_0",
    "schemaVersion": 1,
    "analyzerVersion": "1.0.0",
    "artifactPath": "data/audio_telemetry/latest/97cd5415-3eb8-41c5-b289-96c4573460c4.json",
    "analyzedAt": "2026-05-26T21:06:10Z",
    "confidence": 0.82,
    "summary": {
      "bpm": 92.1,
      "key": "A minor",
      "hookCount": 3,
      "sectionCount": 8,
      "beatCount": 357,
      "topHook": { "start": 44.128, "end": 61.772, "label": "main hook", "confidence": 0.88 }
    }
  }
}
```

## Analyzer pipeline

Recommended stages:

1. Load song record, local audio path, stems, lyric timing if present.
2. Decode full mix with ffmpeg to float mono/stereo.
3. Optional: decode vocal/music stems if available for better vocal coverage/hooks.
4. Compute low-cost frame features:
   - RMS/energy envelope
   - peak envelope
   - spectral centroid/rolloff/flux if dependencies permit
   - onset strength
   - silence/activity masks
5. Beat/tempo detection:
   - Use librosa/aubio when installed.
   - Fall back to autocorrelation/onset interval estimator.
6. Section segmentation:
   - novelty curve over energy/spectral/onset features
   - align boundaries to beats/bars
   - blend lyric sections from existing `lyric_sections`
7. Hook detection:
   - repeated lyric sections/chorus labels
   - repeated audio fingerprints/chroma or energy shape
   - high energy + vocal presence + repeated phrase text
   - rank by confidence and clip usefulness
8. Peak/drop/break detection:
   - local maxima in energy envelope
   - onset bursts after low-energy regions
   - low RMS spans for breaks
9. Create timeline events, sorted by `(start, kind, rank)`.
10. Validate monotonic times and duration bounds.
11. Persist JSON and SQLite.
12. Append registry/history event.

## CLI surfaces

Add script: `scripts/analyze_audio_telemetry.py`.

Suggested commands:

```bash
# Build/refresh queue for all songs missing valid latest telemetry
python3 scripts/analyze_audio_telemetry.py queue --missing

# Queue one song
python3 scripts/analyze_audio_telemetry.py queue --song-id <song_id>

# Queue all songs, forcing new runs when analyzer/params changed
python3 scripts/analyze_audio_telemetry.py queue --all --force --priority 80

# Run workers
python3 scripts/analyze_audio_telemetry.py worker --workers 4
python3 scripts/analyze_audio_telemetry.py worker --song-id <song_id>
python3 scripts/analyze_audio_telemetry.py worker --limit 25

# Inspect status
python3 scripts/analyze_audio_telemetry.py status
python3 scripts/analyze_audio_telemetry.py status --song-id <song_id> --json

# Export agent/human friendly projections
python3 scripts/analyze_audio_telemetry.py export --kind hooks --format jsonl
python3 scripts/analyze_audio_telemetry.py export --song-id <song_id> --include-events beat,section,hook

# Validate persisted artifacts against schema and SQLite rows
python3 scripts/analyze_audio_telemetry.py validate
```

Suggested npm aliases:

```json
{
  "analyze-audio:queue": "python3 scripts/analyze_audio_telemetry.py queue --missing",
  "analyze-audio:worker": "python3 scripts/analyze_audio_telemetry.py worker --workers 4",
  "analyze-audio:status": "python3 scripts/analyze_audio_telemetry.py status",
  "analyze-audio:validate": "python3 scripts/analyze_audio_telemetry.py validate"
}
```

## HTTP/API surfaces

The Electron app does not currently require an HTTP server. If a loopback service is added, keep it local-first and read from the same JSON/SQLite artifacts.

Base URL example: `http://127.0.0.1:8798`.

### Queue endpoints

```text
GET  /api/audio-telemetry/queue
POST /api/audio-telemetry/queue
POST /api/audio-telemetry/queue/:jobId/cancel
POST /api/audio-telemetry/queue/start
POST /api/audio-telemetry/queue/pause
POST /api/audio-telemetry/queue/stop
```

`POST /api/audio-telemetry/queue` body:

```json
{
  "songIds": ["97cd5415-3eb8-41c5-b289-96c4573460c4"],
  "mode": "missing|force|if_stale",
  "priority": 70,
  "requiredKinds": ["summary", "hooks", "sections", "beats", "peaks"]
}
```

### Read endpoints

```text
GET /api/audio-telemetry/songs/:songId
GET /api/audio-telemetry/songs/:songId/summary
GET /api/audio-telemetry/songs/:songId/events
GET /api/audio-telemetry/songs/:songId/events?kind=hook,section&minConfidence=0.7
GET /api/audio-telemetry/runs/:runId
GET /api/audio-telemetry/hooks?limit=100&minConfidence=0.75
GET /api/audio-telemetry/sections?label=chorus
GET /api/audio-telemetry/search-events?q=bounce&kind=hook
```

### Write/manual annotation endpoints

Manual annotations should create a new overlay run or a separate `manual_annotation` event source, not mutate detector runs.

```text
POST /api/audio-telemetry/songs/:songId/events
PATCH /api/audio-telemetry/songs/:songId/events/:eventId
DELETE /api/audio-telemetry/songs/:songId/events/:eventId
```

Manual event body:

```json
{
  "kind": "manual_annotation",
  "label": "Best chorus cut for trailer",
  "start": 44.128,
  "end": 61.772,
  "confidence": 1.0,
  "tags": ["human", "trailer_candidate"],
  "metadata": { "author": "Calder" }
}
```

### Agent-friendly response shape

`GET /api/audio-telemetry/songs/:songId/summary`:

```json
{
  "songId": "97cd5415-3eb8-41c5-b289-96c4573460c4",
  "title": "PipasaySenpai Yippee x Bounce",
  "latestRunId": "atr_20260526T210533Z_a13f92bc_v1_0_0",
  "status": "complete",
  "confidence": 0.82,
  "summary": {
    "duration": 232.52,
    "bpm": 92.1,
    "key": "A minor",
    "hookCount": 3,
    "sectionCount": 8
  },
  "topEvents": {
    "hooks": [
      { "start": 44.128, "end": 61.772, "label": "main hook", "confidence": 0.88 }
    ],
    "sections": [
      { "start": 0.0, "end": 12.4, "label": "intro", "confidence": 0.71 }
    ],
    "peaks": [
      { "start": 72.42, "end": 72.92, "importance": 0.79 }
    ]
  },
  "artifactPath": "data/audio_telemetry/latest/97cd5415-3eb8-41c5-b289-96c4573460c4.json"
}
```

## Electron/UI surfaces

Add a new “Audio Telemetry” panel/tab in the song detail view:

- Status badge: missing / queued / running / complete / stale / failed.
- Buttons:
  - Analyze this song
  - Re-analyze with latest analyzer
  - Open telemetry JSON
  - Copy agent summary
- Summary cards:
  - BPM, key, loudness, peak, hook count, section count, confidence.
- Timeline lane overlay on existing audio/DAW visualization:
  - Beat ticks
  - Section blocks
  - Hook highlights
  - Peak markers
  - Lyric lines from existing timing analysis
- Event table:
  - kind, label, start, end, confidence, tags, source
  - click event seeks player/DAW clock
  - “create loop from event” uses existing loop/mix derivative flow
- Queue dashboard:
  - counts, active jobs, failed jobs, retry buttons
  - filter by missing/stale/failed/complete

Preload IPC additions:

```js
contextBridge.exposeInMainWorld('hapa', {
  // existing calls...
  loadAudioTelemetry: (songId, opts) => ipcRenderer.invoke('audioTelemetry:load', songId, opts),
  queueAudioTelemetry: (payload) => ipcRenderer.invoke('audioTelemetry:queue', payload),
  audioTelemetryStatus: () => ipcRenderer.invoke('audioTelemetry:status'),
  openAudioTelemetryArtifact: (songId) => ipcRenderer.invoke('audioTelemetry:openArtifact', songId),
});
```

## Downstream consumers

### AI agents

Agents should prefer:

1. SQLite for search/filter:
   - latest hooks
   - songs with missing telemetry
   - high confidence sections
2. Per-song JSON for detailed context in prompts.
3. JSONL exports for batch tasks.

Common agent tasks:

- “Find all strong hooks between 10 and 30 seconds.”
- “Pick a 15-second trailer clip for this song.”
- “Align visual cut points to drops/peaks.”
- “Generate a beat-synced story reel.”
- “Compare versions with same lyric master by hook placement.”

### Apps

Apps should use API/SQLite summaries and lazy-load dense beat/peak arrays only when needed.

### Humans

Humans should use the Electron panel, queue dashboard, event table, and exported JSON for review/editing.

## History/audit events

Append to existing `data/history_events.json` using event types:

- `audioTelemetry.queue.created`
- `audioTelemetry.job.queued`
- `audioTelemetry.job.started`
- `audioTelemetry.job.completed`
- `audioTelemetry.job.failed`
- `audioTelemetry.run.promotedLatest`
- `audioTelemetry.manualEvent.created`
- `audioTelemetry.manualEvent.updated`

Example:

```json
{
  "id": "...",
  "at": "2026-05-26T21:06:10Z",
  "type": "audioTelemetry.job.completed",
  "songId": "97cd5415-3eb8-41c5-b289-96c4573460c4",
  "runId": "atr_20260526T210533Z_a13f92bc_v1_0_0",
  "artifactPath": "data/audio_telemetry/runs/97cd.../atr_...json",
  "eventCount": 486,
  "confidence": 0.82
}
```

## Staleness rules

A latest artifact is stale if any of these change:

- source audio hash/size/mtime
- chosen stem hashes
- lyric timing source hash if lyric-aligned sections/hooks are requested
- analyzer name/version
- params hash
- schema version incompatible with current reader
- required event kinds missing

Stale artifacts remain readable but should display `status: stale` in UI/API until a newer complete run is promoted.

## Implementation phases

### Phase 1: persistent contract

- Create `data/audio_telemetry/` layout.
- Add SQLite tables/views.
- Implement queue/status/validate CLI.
- Implement simple analyzer using existing ffmpeg/numpy style from `scripts/analyze_lyric_timing.py`:
  - duration
  - RMS peaks
  - phrase/activity regions
  - lyric sections copied as section/lyric_line events

### Phase 2: beats/sections/hooks

- Add beat tracker and peak/drop detection.
- Add section segmentation aligned to lyric sections.
- Add hook detector and ranker.
- Add registry pointer summaries.

### Phase 3: UI/API

- Add Electron IPC + panel.
- Add optional loopback HTTP API for agents/apps.
- Add exports: hooks/sections/high-confidence events JSONL.

### Phase 4: manual review and overlays

- Add manual annotations as overlay events.
- Add event-to-loop/clip flows.
- Add comparison by lyric master/prompt group/mashup lineage.

## Validation checklist

For every completed run:

- Artifact JSON parses and has required fields.
- `songId` exists in registry/SQLite.
- `duration` matches registry duration within tolerance.
- All event start/end times are finite and within `[0, duration]`.
- `end >= start` for all events.
- Required event kinds exist or warning explains absence.
- SQLite `audio_telemetry_runs.event_count` equals inserted events for run.
- Manifest latest points to an existing artifact.
- History event appended.

## Open implementation notes

- Dense beat/peak arrays can make JSON large. Keep summaries in SQLite and allow optional sidecar JSON for dense data.
- Hashing full audio is ideal but expensive; first pass can use size+mtime and background hash when needed.
- Manual annotations should not modify detector output; store as overlay events or separate manual runs.
- API should bind to `127.0.0.1` by default and avoid exposing local paths unless explicitly requested.
- Existing `lyric_timing_runs`, `lyric_lines`, and `lyric_sections` can seed `lyric_line`, `phrase`, and `section` telemetry events immediately.
