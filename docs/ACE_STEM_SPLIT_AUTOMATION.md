# ACE Studio / ACE Step stem-split automation

This document is the local runbook for using ACE Studio to generate basic two-stem splits for Hapa Song Registry tracks that do not yet have a `vocals` + `music`/`instrumental` pair.

## Current implementation

Control-plane script:

```text
$HAPA_SONG_REGISTRY_ROOT/scripts/ace_stem_queue.py
```

Local dashboard:

```bash
cd "$HAPA_SONG_REGISTRY_ROOT"
python3 scripts/ace_stem_queue.py serve --open
```

Default URL:

```text
http://127.0.0.1:8797
```

State files:

```text
data/ace-stem-queue/state.json
data/ace-stems/<songId>/
data/history_events.json
```

## What it does now

- Reads `data/registry.json`.
- Finds songs whose exact variation does not have a basic two-stem split.
- Builds a queue with source path, song id, title, status, attempts, and export folder.
- Provides start/pause/stop/monitor controls in a small local web app.
- Starts/opens the current source audio in `/Applications/ACE Studio.app`.
- Watches each song's export folder for a pair of audio files whose names include:
  - `vocal` or `voice`
  - `music`, `instrumental`, or `accompaniment`
- Appends queue events to `data/history_events.json`.
- Provides a calibrated local fallback script, `scripts/export_five_stems_demucs.py`, that runs Demucs two-stem vocal separation over the active queue and writes deterministic `vocals.wav` + `music.wav` files into each queued job folder. This uses the same queue success condition as ACE exports: verified files on disk.

## Manual export convention for the current calibrated-safe version

For the active job, export from ACE into:

```text
data/ace-stems/<songId>/
```

Use filenames like:

```text
vocals.wav
music.wav
```

or:

```text
<song-title> - vocals.wav
<song-title> - instrumental.wav
```

Then press `Scan exports` or let the dashboard monitor detect the pair. Press `Mark active complete` if needed.

## Intended full automation path

The safe architecture is:

1. Queue controller owns state and source-of-truth telemetry.
2. One ACE automation adapter owns GUI/API interaction.
3. File monitor verifies outputs before advancing the queue.
4. Registry ingest/indexer later imports the produced stems as first-class stem records.

Do not let GUI clicks be the source of truth. The queue state and detected output files are source of truth.

## ACE GUI calibration still needed

ACE Studio is currently running locally, but exact menu/button/export affordances must be calibrated before the automation should click through unattended. The next pass should use macOS background computer-use or AppleScript accessibility inspection to record:

- How to import/open an audio file into ACE.
- Which menu/button starts vocal/music stem splitting.
- How completion is visible in the UI.
- How export destination and filenames are selected.
- What error dialogs can appear.

Until that is calibrated, this dashboard starts jobs and tracks outputs, but does not claim reliable hands-free GUI export.

## Commands

Create or replace queue from current registry:

```bash
cd "$HAPA_SONG_REGISTRY_ROOT"
python3 scripts/ace_stem_queue.py queue --replace
```

Create a small smoke queue:

```bash
python3 scripts/ace_stem_queue.py queue --replace --limit 3
```

Create the current five-song export test queue and run the local Demucs fallback export:

```bash
python3 scripts/ace_stem_queue.py queue --replace --limit 5
python3 scripts/export_five_stems_demucs.py 5
python3 scripts/ace_stem_queue.py monitor
```

This writes each job's verified files as:

```text
data/ace-stems/<songId>/vocals.wav
data/ace-stems/<songId>/music.wav
```

Demucs dependency setup used during calibration:

```bash
python3 -m pip install --user demucs soundfile
```

Start/open next job in ACE:

```bash
python3 scripts/ace_stem_queue.py start
```

Pause/stop:

```bash
python3 scripts/ace_stem_queue.py pause
python3 scripts/ace_stem_queue.py stop
```

Inspect state:

```bash
python3 scripts/ace_stem_queue.py state
```

## Registry import follow-up

The current script detects and tracks exported files. A follow-up ingest pass should append generated ACE stems into registry data using records shaped like:

```json
{
  "id": "ace-<songId>-vocals",
  "parentId": "<songId>",
  "stemType": "ACE Vocals",
  "localPath": "data/ace-stems/<songId>/vocals.wav",
  "source": "ACE Studio",
  "createdBy": "ace_stem_queue"
}
```

and similarly for `ACE Music`.

## Verification checklist

- `python3 scripts/ace_stem_queue.py queue --replace --limit 3` creates three queued jobs.
- `python3 scripts/ace_stem_queue.py start` opens ACE Studio and marks one job `waiting_for_export`.
- Saving `vocals.wav` and `music.wav` into the active job's export folder makes `monitor` detect both files.
- `data/history_events.json` receives queue events.
- Dashboard buttons update `data/ace-stem-queue/state.json`.
