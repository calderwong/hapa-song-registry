# Peer music: selected offers, listening and Keep

**Stage:** First Pass / Prototype. Built 24 November 2026 for Hapa Versus' shared table
(`hapa-verseUs-prototype/docs/integrations/IMPLEMENTATION_CHECKPOINT.md`).

**Scope:** loopback only (`127.0.0.1`). It is proven between two local Song Registry processes, not
between machines.

The Song Registry stays the music owner. A game host (Versus) never holds music bytes or transfer
state. Over the bearer API, the host asks this owner to:
- offer a selection;
- stream a peer's offer for listening;
- keep a song.

## Running a node

```bash
node src/api-server.js --port 8811 --peer-port 8812
```

| Environment variable | Default | Meaning |
| --- | --- | --- |
| `HAPA_SONG_REGISTRY_DATA_ROOT` | `data/` | Registry and `peer-music/` state |
| `HAPA_SONG_REGISTRY_NODE_ID` | (none) | The node's identity in offers |
| `HAPA_SONG_REGISTRY_NODE_LABEL` | (none) | The node's display label |

- The bearer token lives in `<data root>/api-token` (mode 0600, created on first start). Every
  `/api/peer/*` route requires `Authorization: Bearer …` and refuses browser `Origin` requests.
- A host adds the token server-side (Versus does this in its Vite proxy).
- `data/api-token` and `data/peer-music/` are ignored by git.

## Routes (`/api/peer/…`)

| Route | Meaning |
| --- | --- |
| `GET node` | Node identity, peer port and counts |
| `GET songs?q=` | Browse local songs that have audio, so the owner can choose a contribution |
| `POST contributions {songIds (1–12), participant}` | A snapshot: `playlistId`, `revision`, `contributor`, `entries[{entryId, recordingId, title, credits, durationSeconds, offer}]` |
| `POST audio {offer}` | The exact offered bytes for listening: this node's own offer, or a peer's fetched over Hypercore. Range supported. |
| `POST keep {offer, discovery}` | Save the discovery durably, then start or join the acquisition for this asset |
| `GET keep/:acquisitionId` | The acquisition state |
| `GET encounters` | Discoveries (Songs encountered), with their acquisition state |
| `GET retained` | The retained library |
| `GET retained/:libraryId/audio` | Retained bytes, re-verified on every read |

## Offers

- An offer is one Hypercore per exact asset:
  - block 0 is the canonical manifest (`hapa.music.offer.v1`);
  - blocks 1..n are the bytes, in 64 KiB blocks.
- The manifest holds:
  - the recording identity;
  - the credits, as given by the registry entry (`offerCredits`, else `authors`), with unknown kept as `null`;
  - one file descriptor (`assetId sha256:…`, length, media type);
  - the issuer;
  - capabilities (`stream`, `retain`, `reshare:false`, `export`).
- Changed bytes are a new offer, never a silent replacement.
- The peer port serves only cores this node offered. A connection names one core key in its first
  65 bytes; the full library is never replicated.

## Keep

1. The discovery is appended to `retention/discoveries.ndjson` with fsync **before** `keep`
   returns. That is when the host may say "Saved". It records the introducer, kept apart from the
   creators, and the encounter (`app`, `sessionId`, `playlistId`, `queueRevision`, `entryId`,
   `heardAt`).
2. There is one acquisition per asset, `acq-<sha256[:32]>`. Identical bytes are stored once, and
   every discovery stays distinct.
3. The download is bounded to the manifest's blocks. Verification checks the manifest digest,
   length, SHA-256 and the media header. The bytes are written atomically to
   `retention/assets/<sha256>.<ext>`.
4. Library membership is committed to `retention/library.json`, with the offer's credits imported
   unchanged and no collection default. This commit is the receipt.

States:

| State | Meaning |
| --- | --- |
| `saved-downloading` | Saved; the transfer is running |
| `saved-waiting-source` | Saved; the source is unreachable, retried with backoff for 20 attempts |
| `saved-reference-only` | Saved; the offer does not permit retention |
| `verifying` | Bytes received; checks running |
| `available-offline` | Verified bytes **and** a committed library receipt |
| `download-failed-reference-saved` | The transfer or verification failed; the reference is kept |

Jobs persist in `retention/jobs/` and resume on start. Blocks already received stay in the replica,
so a restart continues from them.

## Not in this pass

- Export and re-share (offers carry `reshare:false`).
- Retained entries in the Electron UI.
- Non-loopback peers.
- Pruning of listening replicas: a heard peer offer stays in `peer-music/remote/` as a cache until pruned.

## Test

```bash
node test/peer-music.test.js
```

`npm test` also runs it, through `test/test_peer_music.py`. It covers:
- transfer and verified retention, with neutral credits;
- deduplication;
- waiting for an unreachable source;
- receiver restart with a resumed partial transfer;
- offline play;
- refusal of tampered bytes and of a forged manifest.
