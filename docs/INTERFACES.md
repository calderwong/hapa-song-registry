# Hapa Song Registry Interfaces

The Electron workbench starts with `npm start`; `npm run api` exposes the
optional loopback API on `127.0.0.1:8798`.

| Surface | Entry | Boundary |
| --- | --- | --- |
| API | `/api/health`, `/api/songs`, `/api/songs/:id`, `/api/audio/:id`, `/api/covers/:id` | Local session/filesystem boundary; do not expose registry paths or audio on a public interface. |
| UI | Electron `src/index.html` + renderer | Song/stem browsing, timing, and DAW-style local playback. |
| Audit CLI | `scripts/audit_echo_album.py` | Read-only, exact-manifest inventory of valid MP3/WAV/stems/lyrics/actual timing/telemetry/Director coverage. |
| Inventory healer | `scripts/heal_echo_album_inventory.py --manifest <path> [--apply]` | Dry-run by default; recovers only exact-ID, byte-valid WAV and evidence-valid timing artifacts from local duplicate exports, with backups. |
| Targeted update CLI | `scripts/update_registry_song.py --song-id <id> [--song-id <id> ...] [--apply]` | Dry-run by default; bounded exact-song validation/normalization and one transactional SQLite upsert without a whole-library rebuild. |
| Audio telemetry | `scripts/audio_telemetry.py analyze <id>` / `worker --song <id>` | Exact-ID, single-attempt analysis; no unrelated queue item may substitute for the requested song. |

`npm test` and `npm run check` validate source and registry shape. The Echo CLIs above are active local operator interfaces; download/session orchestration, measured STT alignment, and Director generation remain owned by their respective Suno, Music Viz, and Avatar Builder surfaces. The six-gate handoff contract is `docs/ECHO_ALBUM_UPDATE_CONTRACT.md`.
