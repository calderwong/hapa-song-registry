# Echo Album update contract

Status: active operator contract (2026-08-25)

The phrase **“Update the Echo Album”** means one ordered, resumable transaction for the exact signed-in Suno playlist. It does not mean “refresh whatever metadata is easy to reach.” A song is current only when every applicable gate below has a durable success receipt; partial work remains explicitly blocked.

## Mandatory gates

1. **MP3 master:** download `song.mp3`; verify non-trivial size, a recognized audio container, successful decode/probe, positive duration, and the exact Suno song ID.
2. **WAV master:** download `song.wav` independently; verify RIFF/WAVE bytes, successful decode/probe, positive duration, and identity with the same Suno song. An MP3 renamed `.wav` does not pass.
3. **Stems:** capture the latest complete Suno stem family where Suno exposes one. Validate every selected stem as decodable audio and preserve stem IDs/types. “Source unavailable” is distinct from “download failed.”
4. **Lyrics:** persist non-empty source lyrics and source hash, or a source-declared instrumental classification. A zero-byte placeholder does not pass.
5. **Analysis:** analyze the full mix and available stems, then align lyrics to measured vocal/audio evidence. Promotable lyric timing must be non-synthetic, confidence `>= 0.60`, non-overlapping, remain within the measured source duration (with only the gate's small tolerance), and carry source/STT sidecars plus audio and lyric SHA-256 provenance. The timing song ID must equal the requested Suno ID, and both hashes must still match the exact current provenance files. Pauses are valid timeline evidence; fabricated uniform timings are not.
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

Recover valid WAV/timing artifacts from duplicate local exports by exact Suno ID:

```bash
python3 scripts/heal_echo_album_inventory.py \
  --manifest "$HAPA_SUNO_LIBRARY_ROOT/playlists/<playlist-id>/manifest.hapa-avatar-builder.json" \
  --json-out /tmp/echo-heal-dry-run.json

python3 scripts/heal_echo_album_inventory.py \
  --manifest "$HAPA_SUNO_LIBRARY_ROOT/playlists/<playlist-id>/manifest.hapa-avatar-builder.json" \
  --json-out "$HAPA_SUNO_LIBRARY_ROOT/playlists/<playlist-id>/<date>-inventory-heal.json" \
  --apply
```

The healer is dry-run by default. It searches only exact-ID metadata siblings, validates WAV container bytes, validates measured timing evidence and current provenance hashes, keeps backups, and hard-links same-volume files with a copy fallback. It does not transcode MP3 into WAV and does not claim source-unavailable artifacts are repaired.

Upsert one or a bounded batch of already-exported songs after applicable gates are satisfied:

```bash
python3 scripts/update_registry_song.py \
  --manifest "$HAPA_SUNO_LIBRARY_ROOT/playlists/<playlist-id>/manifest.hapa-avatar-builder.json" \
  --song-id <exact-suno-song-id> [--song-id <another-exact-id> ...] \
  --json-out /tmp/registry-sync-receipt.json \
  --apply
```

The command defaults to dry-run. `--apply` validates each exact local master, normalizes only requested song directories, applies the strict canonical timing gate, rewrites the compatibility JSON once, and transactionally upserts only those song/stem families plus the small derived SQLite indexes. A rejected timing is removed from the target row; normalization cannot carry it around the gate. Use `npm run ingest` only to bootstrap a missing database, change a global normalization/schema rule, or conduct an explicit whole-library reconciliation.

Audio telemetry remains a separate bounded worker. Target exact IDs; do not let an old global queue item substitute for the requested song:

```bash
python3 scripts/audio_telemetry.py analyze <exact-suno-song-id>
python3 scripts/audio_telemetry.py worker --song <exact-suno-song-id> --limit 1
```

Telemetry jobs get one attempt per invocation and become visibly terminal on failure. Lyric STT/alignment is owned by Hapa Music Viz's `scripts/enrich_suno_playlist_lyrics.py`; use a single worker, exact `--song-id` values, `--stop-on-error`, and the documented CPU fallback when Metal is unstable. `--reuse-stt` may realign against changed lyrics only when the saved STT sidecar still matches the current audio.

After analysis, rerun the targeted upsert and the audit, then generate/preflight the exact Director project in Avatar Builder. Builder timing synchronization must prefer `<playlist>/lyric_timings/<exact-id>.json` and the canonical playlist manifest over project-local or alignment snapshots. Targeted Director compilation must match all exact identity aliases (`id`, `audio_id`, and Registry track ID), even when the project's display slug is legacy.

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
- Keep valid earlier artifacts; resume at the first failed or invalidated gate. Back up any canonical artifact before replacement.
- Changing master audio invalidates downstream analysis and Director receipts unless their stored audio hash still matches.
- Changing lyrics invalidates lyric alignment and lyrics-dependent Director receipts unless the lyric hash still matches.
- A playlist reordering changes display order, not song identity or local custody.

## Process boundary

`audit_echo_album.py` and `update_registry_song.py` spawn no child processes, use one worker, and perform no retries. The former is read-only unless output flags are supplied. The latter writes a temporary compatibility JSON, updates SQLite in one immediate transaction, then atomically promotes the JSON. Audio/timing workers that invoke ffmpeg retain their own bounded worker and retry policies.

The completed healing pass and remaining source-level queue are in `docs/audits/2026-08-25-echo-album-library-heal.md`.
