# Hapa Song Registry

Hapa Song Registry is a local Electron desktop app for browsing, validating, and playing the downloaded Suno/Hapa music library. In the Hapa node ecosystem it acts as the music/stem registry node: it turns local Suno exports and Hapa lyric documents into searchable song, stem, lyric, prompt, timing, and DAW-workstation surfaces for later canon, media, and attribution workflows.

Global wiki link: `../Hapa_Worldbuilding_Wiki/Nodes/Existing/hapa-song-registry.md` (`[[Nodes/Existing/hapa-song-registry]]`).

## Verified current state

Verified from repository files and `data/registry.json` during the 2026-05-21 docs/licensing sweep:

- App shell: Electron + vanilla HTML/CSS/JS (`src/main.js`, `src/preload.js`, `src/index.html`, `src/renderer.js`).
- DAW/stem engine: Web Audio shared-clock multitrack engine in `src/daw-engine.js`.
- Ingestion pipeline: Python scripts under `scripts/` build and verify registry data.
- Test suite: Python `unittest` tests under `test/`.
- Current registry counts in `data/registry.json`:
  - 1,461 songs
  - 4,476 stems
  - 638 lyric/similarity groups
  - 5,000 similarity links
  - 3 external lyric documents
  - 206 lyric masters
  - 651 prompt groups
  - 98 mashups
  - 1,192 songs with lyric timings

## Inputs

- Suno telemetry export: `/Users/calderwong/Desktop/suno-library/suno_library_metadata.json`.
- Local audio files discovered below `/Users/calderwong/Desktop/suno-library`.
- External lyric roots used by default:
  - `/Users/calderwong/Desktop/Hapa Song Lyrics`
  - `/Users/calderwong/Desktop/Hapa Song Library`
- Existing timing cache: `data/lyric_timings/*.json`.

## Outputs and local state

Generated/updated outputs are local runtime artifacts, not network services:

- JSON app cache: `data/registry.json`.
- SQLite registry: `data/hapa_registry.sqlite`.
- Per-song lyric timing files: `data/lyric_timings/*.json`.
- Runtime event/history log: `data/history_events.json`.
- Optional loop/mix derivatives: `data/derivatives/`.

The app does not define an HTTP port. It runs as an Electron desktop window via `npm start`. No repository-local authentication layer was found; access is the local user/session boundary plus local filesystem permissions.

## Run

```bash
cd /Users/calderwong/Desktop/hapa-song-registry
npm install
python3 -m pip install -r requirements.txt
npm start
```

## Rebuild telemetry registry

```bash
cd /Users/calderwong/Desktop/hapa-song-registry
npm run ingest
npm run check
```

`npm run ingest` reads the Suno export and local lyric roots, writes `data/registry.json`, and updates `data/hapa_registry.sqlite`.

## Analyze lyric timings

```bash
cd /Users/calderwong/Desktop/hapa-song-registry
npm run analyze-lyrics
npm run check
```

This decodes local audio with ffmpeg, detects vocal/phrase activity, maps Suno lyric lines onto the analyzed phrase timeline, and writes per-line timestamps into `data/registry.json`, `data/lyric_timings/*.json`, and SQLite.

## Verification commands

Cheap checks available in this repo:

```bash
npm test
npm run check
```

`npm test` runs the Python unit tests. `npm run check` syntax-checks the Electron JavaScript entrypoints and verifies the generated registry JSON/SQLite counts.

## App features

- Search across title, prompt, lyrics, tags, and model.
- Filter by theme, instrument, mood, message, model, audio/stem presence, prompt group, mashup/non-mashup, and variation range.
- Sort by newest, oldest, title, duration, stem count, variation count, and model.
- Play local song audio and queue filtered songs as a playlist.
- View normalized telemetry and raw Suno metadata.
- View prompt, lyrics with audio-analyzed timestamps, style tags, settings, model, duration, local paths, and URLs.
- See groups, prompt groups, mashups, and similarity/variation links.
- See purchased/generated stems by type.
- Toggle stem tracks, mute/solo stems, control stem volume/pan, and use a Web Audio DAW engine for synchronized stem sessions.
- Capture loop regions and render mixer derivatives through ffmpeg.
- Show the current audio file in Finder.

## Hapa role: verified vs inferred

Verified: the repository is a local Electron/Python registry for the Suno/Hapa music library with song, stem, lyric, timing, mashup, and DAW-workstation affordances.

Inferred: inside Hapa, this node can feed music canon review, Roll-The-Tapes/media generation workflows, lyric/prompt lineage, stem reuse, and future Bananas attribution trails. Those integrations are not presented here as active network services unless another node imports this repo's JSON/SQLite outputs.

## Licensing and attribution

Project-level license: MIT under Hapa.ai / Calder Wong. See `LICENSE`.

Third-party dependencies keep their own licenses in `package-lock.json` and `node_modules` metadata; those notices are not replaced by the project-level MIT license.

Bananas attribution option: contributors may opt into Bananas work-contribution tracking for attribution. Bananas tracking is attribution/accounting metadata, not an additional copyright restriction on the MIT-licensed project.

## Notes and risks

- Registry data contains local filesystem paths and generated music metadata. Treat `data/` outputs as local operational state unless intentionally publishing a sanitized snapshot.
- Lyric timing is generated offline from local audio. The analyzer uses purchased/generated Vocals stems when available and falls back to the full mix otherwise. These are phrase-level, audio-derived timings rather than word-level forced alignment; songs with dense mixes or ad-libbed/generated vocals may still be approximate.
- Stem playback and DAW engine behavior depend on browser/Electron Web Audio support and readable local audio paths.

<!-- HAPA-README-SCREENSHOT-2026-05-22 -->

## Screenshot

![hapa-song-registry UI screenshot](docs/assets/screenshots/readme-hapa-song-registry-static-fallback.png)

Hapa Song Registry static-file fallback; Electron preload is required for the full registry UI.
