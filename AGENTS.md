# Hapa Song Registry Agent Guide

## Node Role

`hapa-song-registry` is the local music/stem registry for Hapa songs, Suno imports, lyrics, prompts, timing analysis, DAW-style playback surfaces, and the optional loopback Song Registry API. It is an Electron/Python app over local files, with `127.0.0.1` HTTP serving only when explicitly launched.

## Source Of Truth

- `README.md` defines current inputs, generated outputs, app features, and verification commands.
- `src/` owns the Electron main/preload/renderer UI, audio playback surfaces, and `src/api-server.js` loopback API.
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
- Keep the HTTP API loopback-only unless the operator explicitly asks for network exposure and auth.

## Hapa Connectivity

- Reads Suno library metadata/audio, lyric roots, timing caches, prompts, and manual metadata.
- Produces searchable song/stem registry rows, lyric timing artifacts, DAW playback state, and music-library evidence.
- Related nodes: Hapa wiki, `hapa_second_brain`, `hapa-lance-node`, `hapa-anvil-node`, `hapa-mlx-station`, and Overwatch operations.
- Source code and docs can go to GitHub; heavy audio/stems/derivatives and path-bearing registries should stay in the vault.

## Completion Commit Protocol

- A source or documentation task is not complete until its intended changes are verified and recorded in a focused commit.
- Before committing, inspect the worktree and staged diff, then stage only the files intended for the task.
- Never commit credentials, runtime databases, logs, generated media, build outputs, private payloads, or workstation-specific absolute paths.
- Use a focused commit message, preserve the repository's configured identity, and never rewrite global Git identity settings.
- A commit does not authorize a push, merge, deployment, or other external action; those require the task's explicit authority.
- If required verification fails, the task is not complete: keep the failure visible and report the blocker.

## Verification

```bash
npm test
npm run check
npm run api
```

Before public release, inspect `data/`, audio paths, lyric roots, and generated derivatives for private or heavy assets.
