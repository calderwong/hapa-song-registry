# CAMPFIRE — Hapa Song Registry

## Take

- Local music/stem registry node for Hapa's Suno library.
- Electron desktop UI; no HTTP port or repo-local auth surface found.
- Python ingestion writes JSON + SQLite registry outputs.
- Web Audio DAW engine supports synchronized stem sessions, loop capture, mixer derivatives, and analysis visuals.
- Current verified registry snapshot: 1,461 songs, 4,476 stems, 1,192 lyric-timed songs, 98 mashups.

## Reject

- Do not describe this as a hosted service; it is a local desktop app unless another node wraps it.
- Do not treat generated `data/` artifacts as clean public source; they contain local paths and generated library state.
- Do not overclaim word-level lyric alignment. Current timings are phrase-level/audio-derived with confidence values.

## Add

- Link this node to `[[Nodes/Existing/hapa-song-registry]]` in the Hapa wiki.
- Use the registry as music-canon substrate for Roll-The-Tapes, media generation, stem reuse, and lyric/prompt lineage workflows.
- Keep MIT project licensing under Hapa.ai / Calder Wong, with optional Bananas attribution tracking for contributors.

## Route

- Love: use lyric/stem surfaces to find emotionally resonant songs and relationship arcs.
- Truth: use JSON/SQLite counts and tests to falsify registry claims before publishing snapshots.
- Conviction: pick high-value songs/stems for canonization, demo capture, and media generation.

## Residue

- Repo path: `$HAPA_SONG_REGISTRY_ROOT`.
- Wiki page: `Hapa_Worldbuilding_Wiki/Nodes/Existing/hapa-song-registry.md`.
- Core commands: `npm start`, `npm test`, `npm run ingest`, `npm run check`, `npm run analyze-lyrics`.
- Python dependency install: `python3 -m pip install -r requirements.txt`.
- Main data outputs: `data/registry.json`, `data/hapa_registry.sqlite`, `data/lyric_timings/*.json`.
