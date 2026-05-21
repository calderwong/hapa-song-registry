# Hapa Song Registry Implementation Plan

Goal: Build a local Electron desktop app that turns the downloaded Suno library into a searchable, playable Hapa Music Library with telemetry, grouping, similarity, variations, stems, lyrics, and creative visualization.

Architecture: A Python ingestion pipeline reads `/Users/calderwong/Desktop/suno-library/suno_library_metadata.json`, discovers local song/stem audio files, extracts normalized telemetry, computes heuristic facets and relationships, persists to SQLite plus a JSON application cache, and the Electron app loads the registry through IPC. The renderer is a vanilla HTML/CSS/JS app using Web Audio APIs for playback, stem toggles, approximate lyric following, and canvas visualizations.

Tech Stack: Python 3.9, SQLite 3, Node 25, Electron, vanilla JavaScript, Web Audio API.

Tasks:
1. Create Node/Electron project scaffold with package scripts and app entrypoints.
2. Create ingestion tests covering lyric extraction, stem detection, grouping, and relationship generation.
3. Implement ingestion script that creates `data/hapa_registry.sqlite` and `data/registry.json`.
4. Implement Electron main/preload IPC for loading registry data and resolving file URLs.
5. Implement renderer UI: library, filters, search/sort, song detail, telemetry panels.
6. Implement playback: main audio, stem audio toggles, volume controls, playlists/queue/favorites.
7. Implement canvas visualizations and approximate lyric highlighting.
8. Verify with generated data counts: songs, stems, groups, facets, similarities.
9. Run tests and smoke-check the app build/start command.

Acceptance Criteria:
- Registry includes all 1,227 non-stem songs and all 4,476 stem files from the local Suno download.
- Every song has telemetry: title, prompt/lyrics, style/tags/settings/model/duration/date/URLs/raw metadata.
- Songs are grouped by lyrics fingerprint, themes, instruments, mood, message, and variation-like similarity.
- Stem relationships connect stem clips to parent songs and show stem type counts.
- Electron app can search/filter/sort/play songs, show telemetry/lyrics, toggle stems, and visualize audio.
- Tests pass and project has a README with commands.
