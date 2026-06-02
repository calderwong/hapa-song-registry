<!-- HAPA-CONNECTIVITY-DOC:BEGIN -->
# Hapa Connectivity

Generated: 2026-06-02T04:48:08Z

This file is a publication-safe cross-link for humans and AIs. It describes how this repo fits into the Hapa system without embedding private local paths, secrets, heavy assets, DB payloads, or generated media.

## Identity

- Node id: `hapa-song-registry`
- Repo name: `hapa-song-registry`
- Hapa system group: `nodes/coordination` (Nodes / Coordination)
- Target assembly path: `hapa-system/nodes/coordination/hapa-song-registry`
- Link mode: `local_workspace_pointer_until_remote_exists`

## Role

This node coordinates work, runtime status, agent state, or board visibility for other Hapa nodes.

## Reads From

- Hapa ecosystem docs and node manifests.
- Wiki pages or operations docs when this node needs canonical human context.
- Second Brain relation exports or memory summaries when this node needs durable recall.
- Private assets and generated media through `$HAPA_VAULT_ROOT`, not checked-in binaries.
- Append-only board events and local runtime state.

## Writes To

- Source-safe docs, schemas, manifests, or small fixtures that can pass publication preflight.
- Board events, runtime status, registry entries, or audit reports.

## Related Hapa Nodes

| Node | Relationship |
| --- | --- |
| `hapa` | Front door and ecosystem map. |
| `Hapa_Worldbuilding_Wiki` | Canonical wiki and operations knowledge. |
| `hapa_second_brain` | Durable memory, SQLite relation exports, and recall surface. |
| `hapa-overwatch-kanban` | Append-only project board and event protocol. |
| `hapa-quest-keeper` | Consolidated Quest board overview and board coverage audit. |
| `hapa-agent-registry-node` | Shares the Nodes / Coordination module group. |
| `hapa-open-tasks-node` | Shares the Nodes / Coordination module group. |
| `hapa-telemetry-node` | Shares the Nodes / Coordination module group. |

## Shared Control Surfaces

- `hapa`: front door, operator map, and ecosystem entry point.
- `Hapa_Worldbuilding_Wiki`: canonical human-readable lore, operations, and node documentation.
- `hapa_second_brain`: durable memory, relation exports, and local-first recall surface.
- `hapa-overwatch-kanban`: append-only board/event protocol for node work.
- `hapa-quest-keeper`: consolidated board overview and app coverage audit.
- `$HAPA_VAULT_ROOT`: private companion root for heavy assets, runtime DBs, generated media, and relation exports.

## Publication Boundary

- Publication strategy: `publish_source_with_vault_pointers`
- Publication wave: `wave_1_clean_no_remote_after_local_boundary_commit`
- Current assembly gate: `operator_remote_intent`

Source code, docs, schemas, and tiny fixtures are Git candidates after preflight. Runtime DBs, WAL/SHM files, local tokens, generated media, model weights, logs, app bundles, and vault exports stay out of public Git and should be represented by pointer manifests or rebuild instructions.

## Open Gates

- Choose GitHub owner, repo name, and private/public visibility before remote creation.

## Safe Next Commands

- `git status --short`
- `Apply vault pointer manifests only after vault copy and hash verification.`
- `Commit only intentional docs/source changes; keep generated data under the vault/runtime boundary.`
- `Choose GitHub owner, repo name, and private/public visibility before remote creation.`
- `Run gitleaks/history scan before public release.`
- `Do not move repos, create remotes, push, purge, copy heavy assets, or rewrite history without the matching approval gate.`

## Verification

Run the fastest local checks that exist for this repo before publication or assembly:

```bash
git status --short
npm test
npm run check
python3 -m py_compile scripts/ingest_suno.py scripts/ace_stem_queue.py scripts/audio_telemetry.py scripts/export_five_stems_demucs.py
```

<!-- HAPA-CONNECTIVITY-DOC:END -->
