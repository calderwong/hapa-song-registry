# Hapa Song Registry

<!-- HAPA_ECOSYSTEM_CONTEXT_START -->
## Hapa ecosystem context

Unless this repository explicitly declares a narrower, evidence-backed maturity for a particular capability, treat its Hapa-facing work as **First Pass / Prototype Stage**. Interfaces and workflows may change. There is no general promise of stability, compatibility, uptime, production support, or fitness for a particular use. A label such as **Core** describes current ecosystem importance, not production readiness; a declared release, verified state, MVP, scaffold, or archive status applies only to the named surface and supporting evidence.

Use Hapa as an artist kit. Apps and nodes are work surfaces or specialized paints; Cards and Decks are reusable swatches, recipes, constraints, and remembered techniques; agents are paintbrushes that apply and combine them; Hapa protocols keep the canvas attributable, bounded, and reversible. Start from the closest existing app, Card, agent pattern, or protocol as a **jump-off point**, adapt that pre-existing wisdom to the new problem, verify the result, and preserve source ownership, custody, licenses, attribution, and lineage.

Calder welcomes **for-profit and nonprofit teams and organizations** to suggest a clearly attributed ecosystem presence, service integration, public-interest pilot, connector, Card/Deck, agent route, or future decentralized-commerce experiment. This is an open invitation to explore, not a promise of partnership, acceptance, compatibility, decentralization, funding, commerce capability, or commercial outcome. Canonical guidance: `$HAPA_FRONT_DOOR_ROOT/docs/ECOSYSTEM_STAGE_AND_PARTICIPATION.md` ([public copy](https://github.com/calderwong/hapa/blob/main/docs/ECOSYSTEM_STAGE_AND_PARTICIPATION.md)).
<!-- HAPA_ECOSYSTEM_CONTEXT_END -->

Hapa Song Registry is a local Electron desktop app for browsing, validating, and playing the downloaded Suno/Hapa music library. In the Hapa node ecosystem it acts as the music/stem registry node: it turns local Suno exports and Hapa lyric documents into searchable song, stem, lyric, prompt, timing, and DAW-workstation surfaces for later canon, media, and attribution workflows.

Global wiki link: `../Hapa_Worldbuilding_Wiki/Nodes/Existing/hapa-song-registry.md` (`[[Nodes/Existing/hapa-song-registry]]`).

## Verified current state

Verified from repository files and `data/registry.json` during the 2026-08-25 Echo Album healing pass:

- App shell: Electron + vanilla HTML/CSS/JS (`src/main.js`, `src/preload.js`, `src/index.html`, `src/renderer.js`).
- DAW/stem engine: Web Audio shared-clock multitrack engine in `src/daw-engine.js`.
- Ingestion pipeline: Python scripts under `scripts/` build and verify registry data.
- Test suite: Python `unittest` tests under `test/`.
- Current registry counts in `data/registry.json`:
  - 3,247 songs
  - 6,156 stems
  - 1,141 groups
  - 5,000 similarity links
  - 0 external lyric documents
  - 360 lyric masters
  - 977 prompt groups
  - 202 mashups
  - 1,310 songs with lyric timings
  - 1,401 songs with audio telemetry

## Inputs

- Suno telemetry export: `$HAPA_SUNO_LIBRARY_ROOT/suno_library_metadata.json`.
- Local audio files discovered below `$HAPA_SUNO_LIBRARY_ROOT`, including playlist exports such as `playlists/<playlist-id>/songs/<track>/song.mp3`.
- Optional non-Suno local masters: `data/supplemental-songs.local.json` (or `$HAPA_SONG_SUPPLEMENTAL_IMPORTS`). Each entry must declare a stable `id`, readable `localPath` or `audioUrl`, title, and source lineage. These rows are labeled `nonSunoPlaylistImport` and never claim Suno playlist membership.
- External lyric roots used by default:
  - `$HAPA_SONG_LYRICS_ROOT`
  - `$HAPA_SONG_LIBRARY_ROOT`
- Existing timing cache: `data/lyric_timings/*.json`.

## Outputs and local state

Generated/updated outputs are local runtime artifacts, not network services:

- JSON app cache: `data/registry.json`.
- SQLite registry: `data/hapa_registry.sqlite`.
- Per-song lyric timing files: `data/lyric_timings/*.json`.
- Runtime event/history log: `data/history_events.json`.
- Optional loop/mix derivatives: `data/derivatives/`.

The app runs as an Electron desktop window via `npm start`, and now also exposes an optional loopback API on `127.0.0.1:8798` via `npm run api` or Electron startup. No repository-local authentication layer was found; access is the local user/session boundary plus local filesystem permissions, so keep it loopback-only unless an operator adds auth.

## Run

```bash
cd "$HAPA_SONG_REGISTRY_ROOT"
npm install
python3 -m pip install -r requirements.txt
npm start
```

## Run local Song Registry API

```bash
cd "$HAPA_SONG_REGISTRY_ROOT"
npm run api
```

Useful loopback routes:

- `GET /api/health`
- `GET /api/songs?collection=dear-papa&limit=500`
- `GET /api/songs/:id`
- `GET /api/audio/:id` with byte-range support for real full-mix playback
- `GET /api/covers/:id`

## Rebuild telemetry registry

```bash
cd "$HAPA_SONG_REGISTRY_ROOT"
npm run ingest
npm run check
```

`npm run ingest` reads the Suno export and local lyric roots, writes `data/registry.json`, and updates `data/hapa_registry.sqlite`.

Do not use the full rebuild for one or a bounded set of exported songs. The active meaning of **“Update the Echo Album”**, including mandatory MP3, WAV, stems, lyrics, measured analysis, and Director-script gates, is defined in [`docs/ECHO_ALBUM_UPDATE_CONTRACT.md`](docs/ECHO_ALBUM_UPDATE_CONTRACT.md). Use `scripts/audit_echo_album.py` for a manifest-scoped completeness report, `scripts/heal_echo_album_inventory.py` for exact-ID local recovery, and repeatable `scripts/update_registry_song.py --song-id <id> --apply` arguments for one atomic targeted sync. These commands default to dry-run and reject invalid containers, stale provenance hashes, mismatched IDs, synthetic timing, and low-confidence timing evidence.

## Analyze lyric timings

```bash
cd "$HAPA_SONG_REGISTRY_ROOT"
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
- Serve local song audio to sibling Hapa apps through the loopback API.
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

- Registry data may contain local filesystem paths and generated music metadata. Treat `data/` outputs as local operational state unless intentionally publishing a sanitized snapshot.
- Lyric timing is generated offline from local audio. The analyzer uses purchased/generated Vocals stems when available and falls back to the full mix otherwise. These are phrase-level, audio-derived timings rather than word-level forced alignment; songs with dense mixes or ad-libbed/generated vocals may still be approximate.
- Stem playback and DAW engine behavior depend on browser/Electron Web Audio support and readable local audio paths.


## Hapa ecosystem context

<p>
  <img src="docs/assets/hapa-ecosystem-context/overview.jpg" alt="Hapa ecosystem context visual showing modular nodes, human and AI-agent interfaces, Hapa Cards, avatar-agents, Second Brain, and wiki enrichment loop" width="100%">
</p>

### Shared ecosystem pattern

Hapa is built as a constellation of modular nodes. Each node owns a focused capability, but participates in a shared protocol for provenance, handoff, cards, memory, and operations.

Every node is designed for both human operators and AI agents. The target contract is three surfaces: a UI for direct human review/control, an API for node-to-node and agent calls, and a CLI for scripted runs, audits, and handoffs. Individual repos may be at different maturity levels, but the public contract is that humans and agents can inspect, operate, and verify the node.

Hapa nodes power AI agents and avatar-agents that build new nodes and enhance existing ones. As work moves through the ecosystem, it is mined for utility, wisdom, and repeatable logic, then distilled into Hapa Cards: portable packets of skills, context, memories, and operational patterns.

Humans and AIs use Hapa Cards to discuss, ideate, prototype, and deploy increasingly complex workflows through a playable, card-collecting mechanic. Collaboration history, skills, work artifacts, and canonical decisions are stored in [hapa-second-brain](https://github.com/calderwong/hapa-second-brain), enriched into [Hapa Worldbuilding Wiki](https://github.com/calderwong/hapa-worldbuilding-wiki) entries, and converted back into cards. Avatar-agents can also be combined or specialized into purpose-built identities with their own storage, lore, canon, card decks, skills, and protocols.

### Purpose

Local registry for Hapa songs, Suno/imported audio assets, lyrics, prompts, timing analysis, and music-library metadata.

### Current status

- Status: **active music registry**.
- Local source root: `$HAPA_SONG_REGISTRY_ROOT`.
- This README is intended to be useful to both human operators and future agents: it should explain what the node is for, what it consumes, what it emits, how it connects to other Hapa nodes, and what should stay out of git.

### Inputs

- Suno library audio, lyric docs, prompt archives, timing-analysis scripts, manual metadata edits

### Outputs

- Registry JSON/SQLite records, song metadata, lyric timing artifacts, and searchable library views

### Interfaces

- Electron renderer
- Data/SQLite registry
- Scripts for lyric/audio analysis

### Related Hapa nodes

- [hapa-dev-proto](https://github.com/calderwong/hapa-dev-proto-private) — Primary local-first app; many nodes feed it cards, assets, chat, debug, or projection data.
- [Hapa_Worldbuilding_Wiki](https://github.com/calderwong/hapa-worldbuilding-wiki) — Canonical Markdown graph for lore, nodes, names, cards, systems, and provenance.
- [.Overwatch](https://github.com/calderwong/overwatch) — Operations map: inventory, source index, task inbox, protocols, and runbooks.
- [hapa-telemetry-node](https://github.com/calderwong/hapa-telemetry-node) — Discovery/monitoring hub for node health, capabilities, launchers, and relationships.
- [hapa-keys-node](https://github.com/calderwong/hapa-keys-node) — Local key vault used by authenticated nodes and tools.
- [hapa-lore-node](https://github.com/calderwong/hapa-lore-node) — Chronicle/canon service for daily progress, lore, and searchable wisdom.
- [hapa-anvil-node](https://github.com/calderwong/hapa-anvil-node) — Card standardization/evaluation/forge node for turning raw card ideas into usable artifacts.
- [hapa-janus-world-node](https://github.com/calderwong/hapa-janus-world-node) — World-state truth kernel and event tape for Janus/desktop simulation work.
- [hapa-mlx-station](https://github.com/calderwong/hapa-mlx-station) — Apple Silicon media-generation station that produces visual/audio assets for cards, wiki, and production runs.
- [hapa-lance-node](https://github.com/calderwong/hapa-lance-node) — Local indexing/projection layer for cards, wiki chunks, embeddings, and multimodal records.

### Operating contract

- Treat generated media, local databases, model weights, dependency folders, build outputs, app bundles, and secrets as runtime artifacts unless this README explicitly says otherwise.
- Prefer loopback/local operation first; expose network services only with explicit auth and operator intent.
- When this node produces artifacts for another node, record enough provenance for the receiving node or wiki page to recover the source path, command, prompt, or API request.
- Keep `README.md`, `LICENSE`, `NOTICE.md` where applicable, and repo-local screenshots current as the node evolves.

<!-- HAPA_NODE_ATLAS_DEMO:START -->
## See It In Action

<a href="https://calderwong.github.io/hapa-node-atlas/">
  <img src="https://calderwong.github.io/hapa-node-atlas/assets/atalas-hero-loop-poster.jpg" alt="Hapa Node Atlas live demo" width="360">
</a>

[Open the Hapa Node Atlas demo](https://calderwong.github.io/hapa-node-atlas/)
<!-- HAPA_NODE_ATLAS_DEMO:END -->
