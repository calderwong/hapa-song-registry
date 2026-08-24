# Hapa Song Registry Interfaces

The Electron workbench starts with `npm start`; `npm run api` exposes the
optional loopback API on `127.0.0.1:8798`.

| Surface | Entry | Boundary |
| --- | --- | --- |
| API | `/api/health`, `/api/songs`, `/api/songs/:id`, `/api/audio/:id`, `/api/covers/:id` | Local session/filesystem boundary; do not expose registry paths or audio on a public interface. |
| UI | Electron `src/index.html` + renderer | Song/stem browsing, timing, and DAW-style local playback. |
| Audit CLI | `scripts/audit_echo_album.py` | Read-only, exact-manifest inventory of valid MP3/WAV/stems/lyrics/actual timing/telemetry/Director coverage. |
| Targeted update CLI | `scripts/update_registry_song.py --song-id <id> [--apply]` | Dry-run by default; one-song validation/normalization and transactional SQLite upsert without a whole-library rebuild. |

`npm test` and `npm run check` validate source and registry shape. The two Echo CLIs above are active local operator interfaces; download/session orchestration and Director generation remain owned by their respective Suno/Avatar Builder surfaces. The six-gate handoff contract is `docs/ECHO_ALBUM_UPDATE_CONTRACT.md`.
