# Hapa Song Registry Interfaces

The Electron workbench starts with `npm start`; `npm run api` exposes the
optional loopback API on `127.0.0.1:8798`.

| Surface | Entry | Boundary |
| --- | --- | --- |
| API | `/api/health`, `/api/songs`, `/api/songs/:id`, `/api/audio/:id`, `/api/covers/:id` | Local session/filesystem boundary; do not expose registry paths or audio on a public interface. |
| UI | Electron `src/index.html` + renderer | Song/stem browsing, timing, and DAW-style local playback. |

`npm test` and `npm run check` validate source and registry shape. Ingest, lyric analysis, and generated registry/audio outputs are explicit local operations, not documentation-time writes. A stable CLI remains a Wave 2 gap.
