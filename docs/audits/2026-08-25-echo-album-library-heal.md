# Echo Album library inventory

## Healing result

The 2026-08-24/26 pass started at 176 MP3, 5 WAV, 124 complete source-available stem families, 122 timing-complete songs (108 measured plus 14 instrumentals), and 55 audio-telemetry records. Exact-ID local recovery restored 144 valid WAV masters and 15 archived timing/STT pairs; bounded telemetry then completed all 176 songs. Measured STT and strict re-alignment brought the final timing state to 169/176 (155 measured plus 14 instrumentals). The registry was updated in exact-ID batches and verified without a whole-library rebuild.

No MP3 was renamed or transcoded into a WAV. No low-confidence, stale-hash, synthetic, or wrong-ID timing was accepted. The remaining queues below require either an independent Suno source artifact or better lyric/audio evidence.

Closeout (2026-08-26): Avatar Builder synchronized 48 exact projects/store cards from canonical playlist timing and successfully compiled/preflighted 23 newly eligible targeted Director graphs. The targeted compiler now resolves legacy project slugs through exact Suno/Registry identity aliases, and the timing synchronizer gives the canonical playlist manifest and timing root precedence over snapshots. A final duration-bound check correctly rejected Ghosts Watching T because its last timed line exceeds the source duration; it remains a visible healing item instead of being silently promoted.

Generated: `2026-08-26T21:32:12Z`

This is a read-only, manifest-scoped audit. A path only counts when its bytes and evidence pass the stated gate.

## Counts

- `songs`: **176**
- `mp3Complete`: **176**
- `mp3Missing`: **0**
- `wavComplete`: **149**
- `wavMissing`: **27**
- `manifestPathsCurrent`: **176**
- `manifestPathsStaleOrInvalid`: **0**
- `stemSourceAvailable`: **124**
- `stemsComplete`: **124**
- `stemsIncompleteWhereAvailable`: **0**
- `stemsUnavailableAtSource`: **52**
- `instrumentals`: **14**
- `lyricsSourcePresent`: **162**
- `lyricsSourceMissing`: **14**
- `lyricsComplete`: **176**
- `lyricsMissingRequired`: **0**
- `actualTimingComplete`: **169**
- `actualTimingMeasured`: **155**
- `timingNotRequiredInstrumental`: **14**
- `actualTimingMissingRequired`: **7**
- `stemAnalysisComplete`: **176**
- `directorProjectsPresent`: **176**
- `directorScriptsComplete`: **144**
- `directorScriptsMissing`: **32**

## Healing queues

### Missing/invalid MP3 (0)

- None

### Missing/invalid WAV (27)

- Brave Tongues (`d6409d3a-96ca-4681-bb72-601d1bdb8bf8`)
- Miss Infinity (`e32a2dff-2f78-4589-a5d3-2358636a369a`)
- Gladiator (`5b4c7fff-82d8-431f-b796-8569c652978c`)
- Nothing But Geometry (`4294c439-5d08-4be1-8965-b4a5659c3a69`)
- Zerbini (`43b0882c-84f0-4682-9802-2125aed8f8b5`)
- LitRPG Life (`4b9f48b5-3ca9-416e-b88e-75fd223a1dca`)
- Emma's Update (`804c1216-d884-4aa7-aa73-13a5393d25e7`)
- Fast Movers (`3bc5de6f-9be1-4bf4-a2f1-5c57627258d5`)
- Strangers on That Hill (`92688ea3-f7f3-4113-a66c-e607cb5a9207`)
- Dancing with the Wind (`1a64293b-ece4-4f4c-b768-5e38d654146f`)
- Captain and Sailor (`71dc2eec-daf1-4f05-be46-7b6ec32c14a2`)
- Pocket Full of Butterflies (`cf644b3a-2ebb-4ec6-b477-66d1298afc6f`)
- on your left tonight (`4049f3ce-068f-46f4-8561-3946af6ad49a`)
- Whatever It Is (`77fbe70d-e1cd-4af0-9c95-b6d5becc8526`)
- Between the Beats (`6f81ec52-83bf-42db-b370-a34baac1ba67`)
- A Name I Would Trade (`5e807d33-7197-4fe1-ba20-02427b202bcc`)
- Luna di Clara (`61be6ae2-ac25-4b26-a919-de2d073216bd`)
- Sea Lion's Breath (`a3952912-85ec-483b-88c4-d6fa9f255a31`)
- Sun Hidden in the Dark (`b94c932c-5ef5-43fa-8340-ae2f1bcb401c`)
- Miss Blue (`59817a86-8ba2-423c-b62b-f4f95a0af76b`)
- Red Sunset (`6248f6d8-b903-4571-8010-9bda562b7cc3`)
- Ghosts Watching T (`2e4570e6-e0ae-480c-af61-386390358a24`)
- Colors After the Sea (`069ed813-a8a6-4c19-bf76-2bbb68033a5d`)
- Red Riding for a Sea of (`c6e140ef-b644-46b8-a037-f250a2ea5b86`)
- Pocket Full of Butterflies (`7852023d-3b30-487a-a487-3987842bcd0e`)
- Pocket Full of Butterflies (`a5efeefd-6e77-45e3-8341-38453d66ee32`)
- Rarely Him (`ef59c25c-465b-4de5-9604-00203532071c`)

### Stale/invalid declared master path (0)

- None

### Incomplete stems where Suno exposes stems (0)

- None

### Required lyrics missing (0)

- None

### Required actual timing missing or rejected (7)

- For the Throat (`253247b8-caac-4c26-9a9b-463b7ccf59ce`) — confidence-below-0.60
- Trees Talk the Walk (`fcf3d450-f927-4826-baa7-689c2e6346ed`) — confidence-below-0.60, unadjudicated-alignment-warning
- Tired Eyes (`88620520-2d50-4ae5-826b-81c3132ffff2`) — confidence-below-0.60
- False Friends & Strange Fellows (`e08d22b7-a274-4f11-be23-1316ca87da0b`) — confidence-below-0.60, unadjudicated-alignment-warning
- on your left tonight (`4049f3ce-068f-46f4-8561-3946af6ad49a`) — confidence-below-0.60, unadjudicated-alignment-warning
- Ghosts Watching T (`2e4570e6-e0ae-480c-af61-386390358a24`) — invalid-line-interval (timing exceeds source duration)
- 🎵 “Gangsta in the Broadlight: The Gospel of Conviction” (ft. EmUhhim?)) (`45d3de8e-8447-4e7d-ab53-99e839a2afa8`) — confidence-below-0.60

### Stem/audio analysis missing (0)

- None

### Director script not complete under the six-gate protocol (32)

- Brave Tongues (`d6409d3a-96ca-4681-bb72-601d1bdb8bf8`)
- Miss Infinity (`e32a2dff-2f78-4589-a5d3-2358636a369a`)
- Gladiator (`5b4c7fff-82d8-431f-b796-8569c652978c`)
- For the Throat (`253247b8-caac-4c26-9a9b-463b7ccf59ce`)
- Nothing But Geometry (`4294c439-5d08-4be1-8965-b4a5659c3a69`)
- Trees Talk the Walk (`fcf3d450-f927-4826-baa7-689c2e6346ed`)
- Zerbini (`43b0882c-84f0-4682-9802-2125aed8f8b5`)
- LitRPG Life (`4b9f48b5-3ca9-416e-b88e-75fd223a1dca`)
- Emma's Update (`804c1216-d884-4aa7-aa73-13a5393d25e7`)
- Tired Eyes (`88620520-2d50-4ae5-826b-81c3132ffff2`)
- Fast Movers (`3bc5de6f-9be1-4bf4-a2f1-5c57627258d5`)
- False Friends & Strange Fellows (`e08d22b7-a274-4f11-be23-1316ca87da0b`)
- Strangers on That Hill (`92688ea3-f7f3-4113-a66c-e607cb5a9207`)
- Dancing with the Wind (`1a64293b-ece4-4f4c-b768-5e38d654146f`)
- Captain and Sailor (`71dc2eec-daf1-4f05-be46-7b6ec32c14a2`)
- Pocket Full of Butterflies (`cf644b3a-2ebb-4ec6-b477-66d1298afc6f`)
- on your left tonight (`4049f3ce-068f-46f4-8561-3946af6ad49a`)
- Whatever It Is (`77fbe70d-e1cd-4af0-9c95-b6d5becc8526`)
- Between the Beats (`6f81ec52-83bf-42db-b370-a34baac1ba67`)
- A Name I Would Trade (`5e807d33-7197-4fe1-ba20-02427b202bcc`)
- Luna di Clara (`61be6ae2-ac25-4b26-a919-de2d073216bd`)
- Sea Lion's Breath (`a3952912-85ec-483b-88c4-d6fa9f255a31`)
- Sun Hidden in the Dark (`b94c932c-5ef5-43fa-8340-ae2f1bcb401c`)
- Miss Blue (`59817a86-8ba2-423c-b62b-f4f95a0af76b`)
- Red Sunset (`6248f6d8-b903-4571-8010-9bda562b7cc3`)
- Ghosts Watching T (`2e4570e6-e0ae-480c-af61-386390358a24`)
- Colors After the Sea (`069ed813-a8a6-4c19-bf76-2bbb68033a5d`)
- Red Riding for a Sea of (`c6e140ef-b644-46b8-a037-f250a2ea5b86`)
- 🎵 “Gangsta in the Broadlight: The Gospel of Conviction” (ft. EmUhhim?)) (`45d3de8e-8447-4e7d-ab53-99e839a2afa8`)
- Pocket Full of Butterflies (`7852023d-3b30-487a-a487-3987842bcd0e`)
- Pocket Full of Butterflies (`a5efeefd-6e77-45e3-8341-38453d66ee32`)
- Rarely Him (`ef59c25c-465b-4de5-9604-00203532071c`)

## Healing order

1. Reconcile the signed-in Suno playlist and freeze the exact manifest song IDs.
2. Fetch MP3 and WAV independently; validate container bytes and decodability before promotion.
3. Fetch the latest complete stem family where Suno exposes stems; report source-unavailable separately.
4. Persist non-empty lyrics (or a source-declared instrumental classification).
5. Run stem/audio telemetry and STT lyric alignment; promote only actual, hashed, non-overlapping timings.
6. Generate and preflight director scripts only after gates 1–5 are satisfied; leave explicit blocked receipts otherwise.

## Measured healing plan

- **Wave 0 — manifest truth:** repair stale declared paths by exact song ID and rerun this byte-level audit. Never count a declared path without validating its current bytes.
- **Wave 1 — lossless custody:** obtain and validate the 27 missing WAV masters through the signed-in Suno download surface in bounded, resumable batches.
- **Wave 2 — analysis:** produce actual timing for 7 vocal songs and complete audio/stem telemetry for 0 songs. Preserve the 52 source-unavailable stem cases as explicit states; the 124 source-available stem families already pass.
- **Wave 3 — Director:** regenerate/preflight only exact IDs whose prior gates now pass. Today 144 pass the full protocol and 32 remain blocked by one or more upstream gates.
- **Checkpoint each batch:** persist exact IDs, hashes, validation results, failed gate/retryability, and a fresh audit diff. Resume at the first invalid gate rather than rebuilding the whole registry.
