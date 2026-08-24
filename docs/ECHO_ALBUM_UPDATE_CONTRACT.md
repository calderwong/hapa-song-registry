# Echo Album update contract

Status: active operator contract (2026-08-24)

The phrase **“Update the Echo Album”** means one ordered, resumable transaction for the exact signed-in Suno playlist. It does not mean “refresh whatever metadata is easy to reach.” A song is current only when every applicable gate below has a durable success receipt; partial work remains explicitly blocked.

## Mandatory gates

1. **MP3 master:** download `song.mp3`; verify non-trivial size, a recognized audio container, successful decode/probe, positive duration, and the exact Suno song ID.
2. **WAV master:** download `song.wav` independently; verify RIFF/WAVE bytes, successful decode/probe, positive duration, and identity with the same Suno song. An MP3 renamed `.wav` does not pass.
3. **Stems:** capture the latest complete Suno stem family where Suno exposes one. Validate every selected stem as decodable audio and preserve stem IDs/types. “Source unavailable” is distinct from “download failed.”
4. **Lyrics:** persist non-empty source lyrics and source hash, or a source-declared instrumental classification. A zero-byte placeholder does not pass.
5. **Analysis:** analyze the full mix and available stems, then align lyrics to measured vocal/audio evidence. Promotable lyric timing must be non-synthetic, confidence `>= 0.60`, non-overlapping, and carry source/STT sidecars plus audio and lyric SHA-256 provenance. Pauses are valid timeline evidence; fabricated uniform timings are not.
6. **Director scripts:** generate or update the song's music-video Director script from the approved timing and audio/stem telemetry. Preflight the exact script and media graph. When an earlier gate is blocked, persist a visible blocked receipt instead of producing a legacy/default script and calling the song complete.

Every stage is idempotent and keyed by Suno song ID plus content hashes. A later stage may reuse a matching valid artifact; it may not infer success from a filename, HTTP 200, prior manifest count, or old Director project.

## Commands

Inventory the exact playlist without changing it:

```bash
python3 scripts/audit_echo_album.py \
  --manifest "$HAPA_SUNO_LIBRARY_ROOT/playlists/<playlist-id>/manifest.hapa-avatar-builder.json" \
  --registry data/registry.json \
  --builder-root "$HAPA_AVATAR_BUILDER_ROOT"
```

Upsert one already-exported song after its applicable gates are satisfied:

```bash
python3 scripts/update_registry_song.py \
  --manifest "$HAPA_SUNO_LIBRARY_ROOT/playlists/<playlist-id>/manifest.hapa-avatar-builder.json" \
  --song-id <exact-suno-song-id> \
  --apply
```

The command defaults to dry-run. `--apply` validates the exact local master, normalizes only the requested song directory, rewrites the compatibility JSON once, and transactionally upserts only that song/stem family plus the small derived SQLite indexes. Use `npm run ingest` only to bootstrap a missing database, change a global normalization/schema rule, or conduct an explicit whole-library reconciliation.

Lyric analysis remains a separate bounded worker because it invokes ffmpeg and may be expensive:

```bash
python3 scripts/analyze_lyric_timing.py --song-id <exact-suno-song-id> --workers 1
```

After analysis, rerun the targeted upsert and the audit, then generate/preflight the exact Director project in Avatar Builder.

## Why the protocol drifted

- The downloader, registry importer, timing analyzer, and Director generator were separate commands with no single completion ledger.
- The playlist downloader treated HTTP/download completion and a path in a manifest as success; an opaque payload could therefore masquerade as audio.
- Only one “master” path existed, so WAV was never a mandatory independent artifact.
- Lyrics and timing analysis were documented as optional follow-up work rather than gates.
- Director generation could proceed from metadata/default legacy state before measured analysis existed.
- `ingest_suno.py` was the only registry write interface. It scans all source collections, recomputes all derived data, rewrites the entire JSON file, deletes SQLite, and recreates every table—even for one corrected media path.

The corrective model is **manifest-scoped audit + per-song content-addressed gates + targeted registry upsert + exact Director preflight**.

## Failure and recovery behavior

- Never silently substitute a different format, song, legacy script, synthetic timing, or stale manifest path.
- Record the failed gate, exact song ID, attempted source, validation error, and retryability.
- Keep valid earlier artifacts; resume at the first failed or invalidated gate.
- Changing master audio invalidates downstream analysis and Director receipts unless their stored audio hash still matches.
- Changing lyrics invalidates lyric alignment and lyrics-dependent Director receipts unless the lyric hash still matches.
- A playlist reordering changes display order, not song identity or local custody.

## Process boundary

`audit_echo_album.py` and `update_registry_song.py` spawn no child processes, use one worker, and perform no retries. The former is read-only unless output flags are supplied. The latter writes a temporary compatibility JSON, updates SQLite in one immediate transaction, then atomically promotes the JSON. Audio/timing workers that invoke ffmpeg retain their own bounded worker and retry policies.

The 2026-08-24 measured inventory is in `docs/audits/2026-08-24-echo-album-library-inventory.md`.
