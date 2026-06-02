# Hapa Song Registry Agent Guide

## Node Role

`hapa-song-registry` is the local music/stem registry for Hapa songs, Suno imports, lyrics, prompts, timing analysis, and DAW-style playback surfaces. It is an Electron/Python app over local files, not a network service.

## Source Of Truth

- `README.md` defines current inputs, generated outputs, app features, and verification commands.
- `src/` owns the Electron main/preload/renderer UI and audio playback surfaces.
- `scripts/` owns Suno ingest, audio telemetry, lyric timing, and stem processing helpers.
- `data/` is generated local registry state and should be treated as runtime/vault content unless explicitly sanitized.
- `test/` covers registry and analysis behavior.
- `SECURITY.md` defines publication secret checks.

## Safe Edit Boundaries

- Do not commit local Suno audio, stems, generated timing caches, SQLite registries, large derivatives, or private lyric/source exports.
- Preserve local-path provenance carefully, but strip or vault-manifest private absolute paths before public release.
- Keep Electron preload boundaries narrow; renderer code should not gain broad filesystem access without a clear operator reason.
- Treat generated registry JSON/SQLite as rebuildable operational state, not canonical source code.
- Audio derivatives and telemetry belong in `hapa-vault` or Hypercore transfer batches.

## Hapa Connectivity

- Reads Suno library metadata/audio, lyric roots, timing caches, prompts, and manual metadata.
- Produces searchable song/stem registry rows, lyric timing artifacts, DAW playback state, and music-library evidence.
- Related nodes: Hapa wiki, `hapa_second_brain`, `hapa-lance-node`, `hapa-anvil-node`, `hapa-mlx-station`, and Overwatch operations.
- Source code and docs can go to GitHub; heavy audio/stems/derivatives and path-bearing registries should stay in the vault.

## Verification

```bash
npm test
npm run check
```

Before public release, inspect `data/`, audio paths, lyric roots, and generated derivatives for private or heavy assets.
