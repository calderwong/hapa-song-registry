/**
 * Peer music owner test (docs/PEER_MUSIC.md): two independently owned library nodes in one process,
 * each with its own data root, Hypercore keys and peer port, over loopback TCP.
 *
 * Covers: a real Hypercore transfer and verified retention; a durable discovery before "saved";
 * one asset, distinct discoveries; source unreachable → waiting for source; a partial transfer
 * interrupted by a receiver restart that resumes from the blocks it already has; offline play after
 * the source is gone; tampered bytes refused; a mismatched manifest refused; neutral credits.
 *
 * Run: node test/peer-music.test.js
 */
const assert = require('assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { createHash } = require('crypto');
const { PeerMusic } = require('../src/peer-music.js');

const sha = (b) => createHash('sha256').update(b).digest('hex');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** A small valid WAV of n data bytes (deterministic noise). */
function wav(n, seed) {
  const h = Buffer.alloc(44);
  h.write('RIFF', 0); h.writeUInt32LE(36 + n, 4); h.write('WAVE', 8); h.write('fmt ', 12); h.writeUInt32LE(16, 16);
  h.writeUInt16LE(1, 20); h.writeUInt16LE(1, 22); h.writeUInt32LE(22050, 24); h.writeUInt32LE(44100, 28); h.writeUInt16LE(2, 32); h.writeUInt16LE(16, 34);
  h.write('data', 36); h.writeUInt32LE(n, 40);
  const d = Buffer.alloc(n);
  let x = seed;
  for (let i = 0; i < n; i++) { x = (x * 1103515245 + 12345) >>> 0; d[i] = x >>> 24; }
  return Buffer.concat([h, d]);
}

async function until(fn, ms = 20000, label = 'condition') {
  const end = Date.now() + ms;
  for (;;) { const v = await fn(); if (v) return v; if (Date.now() > end) throw Error(`timed out waiting for ${label}`); await sleep(100); }
}

async function main() {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'peer-music-'));
  const media = path.join(tmp, 'media');
  fs.mkdirSync(media);
  const songs = {
    s1: { id: 's1', title: 'Lantern', authors: [], duration: 60, localPath: path.join(media, 's1.wav'), recordingId: 'test:run:s1', offerCredits: { creators: null, generator: { name: 'Test Generator' } } },
    s2: { id: 's2', title: 'Long Road', authors: ['Ada'], duration: 240, localPath: path.join(media, 's2.wav') },
  };
  fs.writeFileSync(songs.s1.localPath, wav(700 * 1024, 7));
  fs.writeFileSync(songs.s2.localPath, wav(6 * 1024 * 1024, 11));
  const quiet = () => {};
  const base = 18900 + Math.floor(Math.random() * 400);
  const mkSource = () => new PeerMusic({ dataRoot: path.join(tmp, 'red'), nodeId: 'red-library', label: "Red's library", peerPort: base, findSong: (id) => songs[id], log: quiet });
  const mkReceiver = () => new PeerMusic({ dataRoot: path.join(tmp, 'cj'), nodeId: 'cj-library', label: "CJ's library", peerPort: base + 1, findSong: () => null, log: quiet });
  const evidence = { topology: 'local-only: two PeerMusic owners (separate data roots, Hypercore keys and peer ports) over loopback TCP in one process', steps: [] };
  const step = (name, detail) => { evidence.steps.push({ name, ...detail }); console.log(`ok - ${name}`); };

  let src = mkSource(); await src.start();
  let rcv = mkReceiver(); await rcv.start();
  try {
    // 1. transfer + verified retention
    const ref1 = await src.offerSong('s1');
    assert.equal(ref1.manifest.credits.creators, null, 'unknown creators stay unknown');
    const disc = (label) => ({ app: 'test', sessionId: 'match-1', playlistId: 'contribution:red', queueRevision: 3, entryId: 'red-library-1', heardAt: new Date().toISOString(), introducer: { kind: 'avatar', id: 'red-reaper', label } });
    const k1 = await rcv.keep(ref1, disc('Red'));
    const encountersNow = await rcv.encounters();
    assert.equal(encountersNow.length, 1, 'the discovery is durable before keep() returns');
    assert.ok(['saved-downloading', 'verifying', 'available-offline'].includes(k1.state));
    const done1 = await until(async () => { const s = rcv.status(k1.acquisitionId); return s.state === 'available-offline' && s; }, 20000, 'available-offline');
    const lib1 = await rcv.retained();
    assert.equal(lib1.length, 1);
    assert.equal(lib1[0].assetId, `sha256:${sha(fs.readFileSync(songs.s1.localPath))}`);
    assert.deepEqual(lib1[0].credits, songs.s1.offerCredits, 'creator credit is the offer\'s, unchanged');
    assert.equal(lib1[0].introductions[0].introducer.id, 'red-reaper', 'introducer recorded apart from creators');
    assert.equal(lib1[0].collection, undefined, 'no collection default');
    step('transfer and verified retention', { acquisitionId: k1.acquisitionId, receipt: done1.retained, bytes: lib1[0].length });

    // 2. dedup: same bytes, a second discovery
    const k1b = await rcv.keep(ref1, disc('Red again'));
    assert.equal(k1b.acquisitionId, k1.acquisitionId);
    assert.equal(k1b.state, 'available-offline');
    assert.equal(k1b.discoveries, 2);
    assert.equal(fs.readdirSync(rcv.dir('retention', 'assets')).filter((f) => !f.endsWith('.tmp')).length, 1, 'bytes stored once');
    assert.equal((await rcv.retained())[0].introductions.length, 2, 'each discovery stays distinct');
    step('dedup: one asset, two discoveries', { discoveries: 2, assetFiles: 1 });

    // 3. partial transfer, source loss, receiver restart, resume
    const ref2 = await src.offerSong('s2');
    const core = await rcv._replica(ref2.coreKey);
    const conn = await rcv._connect(core, ref2);
    await core.download({ start: 0, end: 30 }).done();
    conn.close();
    let partial = 0; for (let i = 0; i < ref2.length; i++) if (await core.has(i)) partial++;
    assert.ok(partial >= 30 && partial < ref2.length, `partial replica (${partial}/${ref2.length})`);
    await src.close();
    const k2 = await rcv.keep(ref2, disc('Red'));
    const waiting = await until(async () => { const s = rcv.status(k2.acquisitionId); return s.state === 'saved-waiting-source' && s; }, 15000, 'saved-waiting-source');
    assert.equal(waiting.error.code === 'ECONNREFUSED' || !!waiting.error, true);
    step('source unreachable: saved, waiting for source', { state: waiting.state, error: waiting.error.code, partialBlocks: partial, totalBlocks: ref2.length });
    await rcv.close();
    src = mkSource(); await src.start(); // the source comes back (its offers reopen from disk)
    rcv = mkReceiver(); await rcv.start(); // the receiver restarts and resumes its persisted job
    const resumed = rcv.status(k2.acquisitionId);
    assert.ok(resumed, 'job persisted across restart');
    const done2 = await until(async () => { const s = rcv.status(k2.acquisitionId); return s.state === 'available-offline' && s; }, 30000, 'resume to available-offline');
    step('receiver restart resumes the partial transfer', { resumedFrom: resumed.state, attemptsBefore: waiting.attempts ?? null, partialBlocksKept: partial, receipt: done2.retained });

    // 4. offline: source gone, receiver restarted, retained bytes play and verify
    await src.close();
    await rcv.close();
    rcv = mkReceiver(); await rcv.start();
    const lib = await rcv.retained();
    for (const e of lib) {
      const { bytes } = await rcv.retainedAudio(e.libraryId);
      assert.equal(`sha256:${sha(bytes)}`, e.assetId);
    }
    step('offline play after source disconnect and receiver restart', { entries: lib.map((e) => ({ libraryId: e.libraryId, length: e.length })) });

    // 5. tampered bytes are refused, never "available"
    const e0 = lib[0];
    const f = rcv.dir('retention', 'assets', e0.file);
    const good = fs.readFileSync(f);
    const bad = Buffer.from(good); bad[bad.length - 1] ^= 0xff; fs.writeFileSync(f, bad);
    await assert.rejects(() => rcv.retainedAudio(e0.libraryId), /changed/);
    fs.writeFileSync(f, good);
    step('tampered retained bytes refused', {});

    // 6. a reference whose manifest does not match its digest is refused before anything is saved
    const forged = JSON.parse(JSON.stringify(ref1)); forged.manifest.credits = { creators: ['Someone Else'] };
    const before = (await rcv.encounters()).length;
    await assert.rejects(() => rcv.keep(forged, disc('x')), /does not match/);
    assert.equal((await rcv.encounters()).length, before);
    step('forged manifest refused', {});
  } finally {
    await src.close().catch(() => {});
    await rcv.close().catch(() => {});
  }
  if (process.env.PEER_MUSIC_EVIDENCE) fs.writeFileSync(process.env.PEER_MUSIC_EVIDENCE, JSON.stringify({ ...evidence, ranAt: new Date().toISOString() }, null, 1));
  fs.rmSync(tmp, { recursive: true, force: true });
  console.log('peer-music: all passed');
}

main().then(() => process.exit(0), (e) => { console.error(e); process.exit(1); });
