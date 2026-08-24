# Hapa Song Registry Agent Guide

<!-- HAPA_ECOSYSTEM_AGENT_CONTEXT_START -->
## Ecosystem stage and claim discipline

- Treat this repository's Hapa-facing work as **First Pass / Prototype Stage** unless the owning docs explicitly declare a narrower, evidence-backed maturity for the capability in scope. Never imply a general stability, compatibility, availability, support, or production-readiness guarantee.
- `Core` means important to current ecosystem operation, not production-ready. Preserve explicit local states such as released, verified, MVP, scaffold, deprecated, or archive/reference, and keep each claim bounded to its evidence.
- Use Hapa as an artist kit: apps/nodes are work surfaces or specialized paints, Cards/Decks are reusable swatches and recipes, agents are paintbrushes, and protocols keep the canvas attributable and reversible. Begin from the nearest existing app, Card, agent pattern, or protocol as a jump-off point; inspect it, adapt it, verify it, and write useful evidence back.
- Preserve origin ownership, custody, authority, privacy, licenses, upstream attribution, and lineage. Hapa presence or integration never transfers upstream ownership.
- The open invite to for-profit and nonprofit teams is exploratory. Do not imply partnership, endorsement, acceptance, compatibility, decentralization, funding, nonprofit status, commerce capability, or commercial terms without separate evidence and explicit human approval.
- Canonical guidance: `$HAPA_FRONT_DOOR_ROOT/docs/ECOSYSTEM_STAGE_AND_PARTICIPATION.md` ([public copy](https://github.com/calderwong/hapa/blob/main/docs/ECOSYSTEM_STAGE_AND_PARTICIPATION.md)).
<!-- HAPA_ECOSYSTEM_AGENT_CONTEXT_END -->

## Node Role

`hapa-song-registry` is the local music/stem registry for Hapa songs, Suno imports, lyrics, prompts, timing analysis, DAW-style playback surfaces, and the optional loopback Song Registry API. It is an Electron/Python app over local files, with `127.0.0.1` HTTP serving only when explicitly launched.

## Source Of Truth

- `README.md` defines current inputs, generated outputs, app features, and verification commands.
- `src/` owns the Electron main/preload/renderer UI, audio playback surfaces, and `src/api-server.js` loopback API.
- `scripts/` owns Suno ingest, audio telemetry, lyric timing, and stem processing helpers.
- `data/` is generated local registry state and should be treated as runtime/vault content unless explicitly sanitized.
- `test/` covers registry and analysis behavior.
- `docs/ECHO_ALBUM_UPDATE_CONTRACT.md` is the required six-gate meaning of “Update the Echo Album.” Do not report an album/song current from metadata reconciliation alone.
- `SECURITY.md` defines publication secret checks.

## Safe Edit Boundaries

- Do not commit local Suno audio, stems, generated timing caches, SQLite registries, large derivatives, or private lyric/source exports.
- Preserve local-path provenance carefully, but strip or vault-manifest private absolute paths before public release.
- Keep Electron preload boundaries narrow; renderer code should not gain broad filesystem access without a clear operator reason.
- Treat generated registry JSON/SQLite as rebuildable operational state, not canonical source code.
- Audio derivatives and telemetry belong in `hapa-vault` or Hypercore transfer batches.
- Keep the HTTP API loopback-only unless the operator explicitly asks for network exposure and auth.
- For an Echo update, validate actual bytes and exact song identity. MP3, WAV, source-available stems, lyrics/instrumental truth, measured analysis, and Director output are separate gates with explicit failures.
- Prefer `scripts/update_registry_song.py` for one exported song. Reserve the destructive full SQLite rebuild in `ingest_suno.py` for bootstrap, schema/global-normalization changes, or explicit whole-library reconciliation.

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


## New Application Build Gate

Whenever an agent picks up, resumes, or receives a handoff for a new application build task, it MUST complete this gate before implementation:

1. Re-read `$HAPA_FRONT_DOOR_ROOT/docs/HAPA_PROTOCOL_STANDARDS.md` on every pickup, resume, or handoff; a prior task review does not carry forward.
2. Confirm the intended app root and repository boundary. Every new standalone app MUST be initialized as its own Git repository before implementation files are created. If the app intentionally belongs in a monorepo, verify that the app path is tracked by that repository before implementation; do not create an accidental nested repository.
3. Inspect `git status --short --branch`, then establish or update the app README and `AGENTS.md` so Hapa standards remain visible inside the repository.
4. Record the standards review and verified repository root in the task, handoff, session note, or append-only board evidence.
