/**
 * Peer music: selected offers, Hypercore delivery and verified retention for this library.
 *
 * The Song Registry is the music owner. A game (Hapa Versus) never holds music bytes or transfer
 * state; it asks this owner — over its loopback API — to offer a selected contribution, to stream
 * a peer's offered recording for listening, and to Keep one. Contract: docs/PEER_MUSIC.md.
 *
 *  - An offer is one Hypercore per exact asset: block 0 is the canonical offer manifest (recording
 *    identity, explicit credits, file descriptor with SHA-256/length/media type, capabilities);
 *    blocks 1..n are the bytes. A replaced file is a different asset and a different offer.
 *  - Only offered cores are served (a connection names one core key; anything else is refused).
 *    The full library is never replicated.
 *  - Keep writes the discovery durably (fsync) before reporting "saved", then runs one idempotent
 *    acquisition per asset: bounded download of the manifest's blocks, length + SHA-256 + media
 *    check, atomic commit of the bytes and of library membership. Jobs persist and resume after a
 *    restart; identical bytes are stored once while every discovery stays distinct.
 *  - Credits are the offer's own; unknown fields stay unknown. No local collection defaults.
 */
const fs = require('fs');
const fsp = require('fs/promises');
const path = require('path');
const net = require('net');
const { createHash, randomUUID } = require('crypto');
const Hypercore = require('hypercore');

const BLOCK = 64 * 1024;
const OFFER_SCHEMA = 'hapa.music.offer.v1';
const MAX_ASSET = 160 * 1024 * 1024;
const STATES = ['saving', 'saved-downloading', 'saved-waiting-source', 'saved-paused', 'saved-reference-only', 'verifying', 'available-offline', 'download-failed-reference-saved'];
const sha256 = (b) => createHash('sha256').update(b).digest('hex');
const MEDIA = { '.mp3': 'audio/mpeg', '.wav': 'audio/wav', '.m4a': 'audio/mp4', '.flac': 'audio/flac', '.ogg': 'audio/ogg' };
const EXT = Object.fromEntries(Object.entries(MEDIA).map(([e, m]) => [m, e]));

/** Canonical JSON: sorted keys, no whitespace (the digest and the manifest bytes agree). */
function canonical(v) {
  if (Array.isArray(v)) return `[${v.map(canonical).join(',')}]`;
  if (v && typeof v === 'object') return `{${Object.keys(v).sort().filter((k) => v[k] !== undefined).map((k) => `${JSON.stringify(k)}:${canonical(v[k])}`).join(',')}}`;
  return JSON.stringify(v);
}

/** Bounded media check for the formats this owner plays: a header and frame/RIFF structure, not a full decode. */
function mediaCheck(bytes, mediaType) {
  if (mediaType === 'audio/wav') return bytes.length > 44 && bytes.toString('ascii', 0, 4) === 'RIFF' && bytes.toString('ascii', 8, 12) === 'WAVE' && bytes.indexOf(Buffer.from('fmt ')) > 0 && bytes.indexOf(Buffer.from('data')) > 0;
  if (mediaType === 'audio/mpeg') {
    let i = 0;
    if (bytes.toString('ascii', 0, 3) === 'ID3') i = 10 + ((bytes[6] & 0x7f) << 21 | (bytes[7] & 0x7f) << 14 | (bytes[8] & 0x7f) << 7 | (bytes[9] & 0x7f));
    for (const j of [i, i + 1, i + 2]) if (bytes[j] === 0xff && (bytes[j + 1] & 0xe0) === 0xe0) return true;
    return false;
  }
  return false;
}

async function writeAtomic(file, data) {
  const tmp = `${file}.${process.pid}.${Date.now()}.tmp`;
  const fh = await fsp.open(tmp, 'w', 0o600);
  try { await fh.writeFile(data); await fh.sync(); } finally { await fh.close(); }
  await fsp.rename(tmp, file);
}

async function appendDurable(file, line) {
  const fh = await fsp.open(file, 'a', 0o600);
  try { await fh.appendFile(`${line}\n`); await fh.sync(); } finally { await fh.close(); }
}

class PeerMusic {
  /**
   * @param {{ dataRoot: string, nodeId: string, label?: string, peerHost?: string, peerPort: number, findSong: (id: string) => any, log?: (s: string) => void }} o
   */
  constructor(o) {
    this.root = path.join(o.dataRoot, 'peer-music');
    this.nodeId = o.nodeId;
    this.label = o.label || o.nodeId;
    this.peerHost = o.peerHost || '127.0.0.1';
    this.peerPort = o.peerPort;
    this.findSong = o.findSong;
    this.log = o.log || ((s) => console.log(`[peer-music ${this.nodeId}] ${s}`));
    this.offers = new Map(); // coreKey hex → { offerId, core, manifest }
    this.remote = new Map(); // coreKey hex → Hypercore (receiver replicas)
    this.jobs = new Map(); // acquisitionId → job
    this.running = new Map(); // acquisitionId → Promise
    this.audioCache = new Map(); // coreKey → Buffer (listening only; never "available offline")
    this.closed = false;
  }

  dir(...p) { return path.join(this.root, ...p); }

  async start() {
    for (const d of ['offers', 'remote', 'retention/jobs', 'retention/assets']) await fsp.mkdir(this.dir(d), { recursive: true, mode: 0o700 });
    // re-open every offer this node made before (so a restart keeps serving them)
    for (const f of await fsp.readdir(this.dir('offers')).catch(() => [])) {
      if (!f.endsWith('.json')) continue;
      const rec = JSON.parse(await fsp.readFile(this.dir('offers', f), 'utf8'));
      try { await this._openOffer(rec.offerId); } catch (e) { this.log(`offer ${rec.offerId} unavailable: ${e.message}`); }
    }
    this.server = net.createServer((socket) => this._serve(socket));
    await new Promise((resolve, reject) => { this.server.once('error', reject); this.server.listen(this.peerPort, this.peerHost, resolve); });
    // resume unfinished acquisitions after a restart
    for (const f of await fsp.readdir(this.dir('retention/jobs')).catch(() => [])) {
      if (!f.endsWith('.json')) continue;
      const job = JSON.parse(await fsp.readFile(this.dir('retention/jobs', f), 'utf8'));
      this.jobs.set(job.acquisitionId, job);
      if (!['available-offline', 'saved-reference-only', 'download-failed-reference-saved', 'saved-paused'].includes(job.state)) this._run(job.acquisitionId);
    }
    this.log(`serving offers on ${this.peerHost}:${this.peerPort}; ${this.offers.size} offers, ${this.jobs.size} acquisitions`);
  }

  async close() {
    this.closed = true;
    await new Promise((r) => (this.server ? this.server.close(() => r()) : r()));
    for (const s of this.sockets ?? []) s.destroy();
    for (const { core } of this.offers.values()) await core.close().catch(() => {});
    for (const core of this.remote.values()) await core.close().catch(() => {});
  }

  // --- source side ----------------------------------------------------------------------------

  async _openOffer(offerId) {
    const core = new Hypercore(this.dir('offers', offerId));
    await core.ready();
    if (!core.length) throw Error('empty offer core');
    const manifest = JSON.parse((await core.get(0)).toString('utf8'));
    const key = core.key.toString('hex');
    this.offers.set(key, { offerId, core, manifest });
    return { key, core, manifest };
  }

  /**
   * Offer one registry song's exact current bytes. Repeating with unchanged bytes returns the same
   * offer; changed bytes produce a new offer (never a silent replacement).
   */
  async offerSong(songId) {
    const song = this.findSong(songId);
    if (!song || !song.localPath) throw Object.assign(Error('song has no local audio to offer'), { status: 404 });
    const mediaType = MEDIA[path.extname(song.localPath).toLowerCase()];
    if (!mediaType) throw Object.assign(Error('unsupported audio format for peer offers'), { status: 415 });
    const bytes = await fsp.readFile(song.localPath);
    if (bytes.length > MAX_ASSET) throw Object.assign(Error('asset exceeds the offer limit'), { status: 413 });
    const digest = sha256(bytes);
    const offerId = sha256(`${this.nodeId}\n${song.id}\n${digest}`).slice(0, 32);
    const existing = [...this.offers.values()].find((o) => o.offerId === offerId);
    if (existing) return this._offerRef(existing.core, existing.manifest);
    const core = new Hypercore(this.dir('offers', offerId));
    await core.ready();
    const blocks = Math.ceil(bytes.length / BLOCK);
    const credits = song.offerCredits || {
      creators: (song.authors || []).length ? song.authors : null,
      source: song.sourceCredit || null,
    };
    const manifest = {
      schema: OFFER_SCHEMA,
      recording: { id: song.recordingId || `hapa-song-registry:${this.nodeId}:${song.id}`, originId: song.id, title: song.title || null, version: song.version || null, durationSeconds: song.duration || null },
      credits,
      files: [{ assetId: `sha256:${digest}`, sha256: digest, length: bytes.length, mediaType, role: 'audio', blockSize: BLOCK, firstBlock: 1, blocks }],
      issuer: { nodeId: this.nodeId, label: this.label, coreKey: core.key.toString('hex') },
      capabilities: { stream: true, retain: song.offerRetain !== false, reshare: false, export: true },
      createdAt: new Date().toISOString(),
    };
    if (!core.length) {
      await core.append(Buffer.from(canonical(manifest)));
      for (let i = 0; i < blocks; i++) await core.append(bytes.subarray(i * BLOCK, (i + 1) * BLOCK));
    }
    const stored = JSON.parse((await core.get(0)).toString('utf8'));
    await writeAtomic(this.dir('offers', `${offerId}.json`), JSON.stringify({ offerId, songId: song.id, coreKey: core.key.toString('hex'), sha256: digest, createdAt: stored.createdAt }));
    this.offers.set(core.key.toString('hex'), { offerId, core, manifest: stored });
    return this._offerRef(core, stored);
  }

  _offerRef(core, manifest) {
    const block0 = Buffer.from(canonical(manifest));
    return { schema: OFFER_SCHEMA, coreKey: core.key.toString('hex'), length: 1 + manifest.files[0].blocks, manifestDigest: sha256(block0), manifest, peer: { host: this.peerHost, port: this.peerPort, nodeId: this.nodeId } };
  }

  /** The exact bytes of one of this node's own offers (the source's own listening path). */
  async ownOfferBytes(coreKey) {
    const o = this.offers.get(coreKey);
    if (!o) throw Object.assign(Error('not an offer of this node'), { status: 404 });
    return this._assemble(o.core, o.manifest);
  }

  /** Serve exactly one offered core per connection; the first 65 bytes name it. */
  _serve(socket) {
    (this.sockets ??= new Set()).add(socket);
    socket.once('close', () => this.sockets.delete(socket));
    socket.setTimeout(30000, () => socket.destroy());
    let head = Buffer.alloc(0);
    const onData = (chunk) => {
      head = Buffer.concat([head, chunk]);
      if (head.length < 65) return;
      socket.off('data', onData);
      const key = head.subarray(0, 64).toString('ascii');
      const offer = /^[a-f0-9]{64}$/.test(key) && head[64] === 10 ? this.offers.get(key) : null;
      if (!offer) { socket.destroy(); return; }
      socket.setTimeout(0);
      const stream = offer.core.replicate(false);
      if (head.length > 65) stream.write(head.subarray(65));
      socket.pipe(stream).pipe(socket);
      stream.on('error', () => socket.destroy());
      socket.on('error', () => stream.destroy());
    };
    socket.on('data', onData);
  }

  // --- receiver side --------------------------------------------------------------------------

  _validRef(ref) {
    if (!ref || ref.schema !== OFFER_SCHEMA || !/^[a-f0-9]{64}$/.test(ref.coreKey || '') || !Number.isSafeInteger(ref.length) || ref.length < 2 || !/^[a-f0-9]{64}$/.test(ref.manifestDigest || '')) throw Object.assign(Error('invalid offer reference'), { status: 400 });
    if (!ref.peer || ref.peer.host !== '127.0.0.1' || !Number.isInteger(ref.peer.port)) throw Object.assign(Error('this build only connects to loopback peers'), { status: 400 });
    return ref;
  }

  async _replica(coreKey) {
    let core = this.remote.get(coreKey);
    if (!core) { core = new Hypercore(this.dir('remote', coreKey), Buffer.from(coreKey, 'hex')); await core.ready(); this.remote.set(coreKey, core); }
    return core;
  }

  /** Connect to the source and keep the replication alive until `done` resolves (or it drops). */
  _connect(core, ref) {
    return new Promise((resolve, reject) => {
      const socket = net.connect(ref.peer.port, ref.peer.host);
      socket.setTimeout(8000, () => socket.destroy(Object.assign(Error('source unreachable'), { code: 'ETIMEDOUT' })));
      socket.once('connect', () => {
        socket.setTimeout(0);
        socket.write(`${ref.coreKey}\n`);
        const stream = core.replicate(true);
        socket.pipe(stream).pipe(socket);
        stream.on('error', () => {});
        resolve({ close: () => { stream.destroy(); socket.destroy(); }, closed: new Promise((r) => socket.once('close', r)) });
      });
      socket.once('error', reject);
    });
  }

  /** Download the manifest's blocks (bounded, never an open-ended range), verify, and return the bytes. */
  async _fetch(ref, { onProgress } = {}) {
    const core = await this._replica(ref.coreKey);
    const have = async () => { let n = 0; for (let i = 0; i < ref.length; i++) if (await core.has(i)) n++; return n; };
    if ((await have()) < ref.length) {
      const conn = await this._connect(core, ref);
      try {
        const range = core.download({ start: 0, end: ref.length });
        let last = -1;
        const tick = setInterval(async () => { const n = await have(); if (n !== last) { last = n; onProgress?.(n, ref.length); } }, 250);
        try { await Promise.race([range.done(), conn.closed.then(() => { throw Object.assign(Error('source disconnected'), { code: 'ECONNRESET' }); })]); }
        finally { clearInterval(tick); }
      } finally { conn.close(); }
    }
    onProgress?.(ref.length, ref.length);
    const block0 = await core.get(0, { wait: false });
    if (!block0 || sha256(block0) !== ref.manifestDigest) throw Object.assign(Error('offer manifest does not match the reference'), { code: 'EMANIFEST' });
    const manifest = JSON.parse(block0.toString('utf8'));
    return { core, manifest };
  }

  async _assemble(core, manifest) {
    const f = manifest.files[0];
    const parts = [];
    for (let i = 0; i < f.blocks; i++) parts.push(await core.get(f.firstBlock + i, { wait: false }));
    if (parts.some((p) => !p)) throw Object.assign(Error('blocks missing'), { code: 'EINCOMPLETE' });
    const bytes = Buffer.concat(parts);
    if (bytes.length !== f.length || sha256(bytes) !== f.sha256) throw Object.assign(Error('asset bytes do not match the offer'), { code: 'EDIGEST' });
    return bytes;
  }

  /** Listening: the peer's exact offered bytes, via this owner (cached in memory; not retention). */
  async peerAudio(ref) {
    this._validRef(ref);
    const cached = this.audioCache.get(ref.coreKey);
    if (cached) return cached;
    const own = this.offers.get(ref.coreKey);
    const value = own ? { bytes: await this._assemble(own.core, own.manifest), mediaType: own.manifest.files[0].mediaType }
      : await this._fetch(ref).then(async ({ core, manifest }) => ({ bytes: await this._assemble(core, manifest), mediaType: manifest.files[0].mediaType }));
    this.audioCache.set(ref.coreKey, value);
    while (this.audioCache.size > 4) this.audioCache.delete(this.audioCache.keys().next().value);
    return value;
  }

  // --- Keep and retention ---------------------------------------------------------------------

  /**
   * Keep: one durable discovery (saved before this resolves) and one idempotent acquisition per
   * asset. Returns the public state; the transfer continues in the background.
   */
  async keep(ref, discovery) {
    this._validRef(ref);
    const asset = ref.manifest?.files?.[0];
    if (!asset || !/^[a-f0-9]{64}$/.test(asset.sha256)) throw Object.assign(Error('offer reference lacks its asset descriptor'), { status: 400 });
    if (sha256(Buffer.from(canonical(ref.manifest))) !== ref.manifestDigest) throw Object.assign(Error('offer manifest does not match its digest'), { status: 400 });
    const d = discovery || {};
    const discoveryRec = {
      schema: 'hapa.music.discovery.v1', discoveryId: randomUUID(), savedAt: new Date().toISOString(),
      recordingId: ref.manifest.recording.id, assetId: asset.assetId, manifestDigest: ref.manifestDigest, coreKey: ref.coreKey,
      title: ref.manifest.recording.title, credits: ref.manifest.credits,
      introducer: d.introducer ? { kind: String(d.introducer.kind || 'participant').slice(0, 20), id: String(d.introducer.id || '').slice(0, 80), label: String(d.introducer.label || '').slice(0, 80) } : null,
      encounter: { app: String(d.app || 'unknown').slice(0, 40), sessionId: String(d.sessionId || '').slice(0, 120), playlistId: d.playlistId ? String(d.playlistId).slice(0, 120) : null, queueRevision: d.queueRevision ?? null, entryId: d.entryId ? String(d.entryId).slice(0, 80) : null, heardAt: d.heardAt || null, heard: !!d.heardAt },
      source: { nodeId: ref.manifest.issuer.nodeId, label: ref.manifest.issuer.label },
    };
    // the same encounter again (a repeated click or a retry) reuses its discovery: idempotent per
    // encounter; a different introducer or session of the same bytes is a distinct discovery
    const sameEncounter = (x) => x.assetId === asset.assetId && x.encounter?.app === discoveryRec.encounter.app && x.encounter?.sessionId === discoveryRec.encounter.sessionId
      && x.encounter?.entryId === discoveryRec.encounter.entryId && (x.introducer?.id ?? null) === (discoveryRec.introducer?.id ?? null);
    const prior = discoveryRec.encounter.sessionId ? (await this.encounters()).find(sameEncounter) : null;
    if (prior) discoveryRec.discoveryId = prior.discoveryId;
    else await appendDurable(this.dir('retention', 'discoveries.ndjson'), JSON.stringify(discoveryRec));
    const acquisitionId = `acq-${asset.sha256.slice(0, 32)}`;
    let job = this.jobs.get(acquisitionId);
    if (!job) {
      job = { schema: 'hapa.music.acquisition.v1', acquisitionId, assetId: asset.assetId, sha256: asset.sha256, ref: { ...ref }, state: ref.manifest.capabilities?.retain === false ? 'saved-reference-only' : 'saved-downloading', discoveries: [], providers: [ref.peer], receivedBlocks: 0, totalBlocks: ref.length, attempts: 0, createdAt: discoveryRec.savedAt, updatedAt: discoveryRec.savedAt, error: null };
      this.jobs.set(acquisitionId, job);
    } else if (job.ref.coreKey !== ref.coreKey && !job.providers.some((p) => p.port === ref.peer.port)) {
      job.providers.push(ref.peer); // another provider offering the same verified bytes
    }
    if (!job.discoveries.includes(discoveryRec.discoveryId)) job.discoveries.push(discoveryRec.discoveryId);
    if (job.state === 'download-failed-reference-saved' || job.state === 'saved-paused') { job.state = 'saved-downloading'; job.attempts = 0; }
    await this._saveJob(job);
    if (job.state === 'available-offline') await this._refreshIntroductions(asset.assetId); // same bytes, one more discovery
    else if (job.state !== 'saved-reference-only') this._run(acquisitionId);
    return this.status(acquisitionId, discoveryRec.discoveryId);
  }

  status(acquisitionId, discoveryId = null) {
    const j = this.jobs.get(acquisitionId);
    if (!j) return null;
    return { acquisitionId, discoveryId, state: j.state, receivedBlocks: j.receivedBlocks, totalBlocks: j.totalBlocks, discoveries: j.discoveries.length, error: j.error, retained: j.retained || null, updatedAt: j.updatedAt };
  }

  async _saveJob(job) { job.updatedAt = new Date().toISOString(); await writeAtomic(this.dir('retention', 'jobs', `${job.acquisitionId}.json`), JSON.stringify(job, null, 1)); }

  _run(acquisitionId) {
    if (this.running.has(acquisitionId)) return this.running.get(acquisitionId);
    const p = this._acquire(acquisitionId).finally(() => this.running.delete(acquisitionId));
    this.running.set(acquisitionId, p);
    return p;
  }

  async _acquire(acquisitionId) {
    const job = this.jobs.get(acquisitionId);
    const set = async (state, extra = {}) => { Object.assign(job, { state, ...extra }); await this._saveJob(job); };
    while (!this.closed) {
      const providers = job.providers.length ? job.providers : [job.ref.peer];
      let fetched = null, lastErr = null;
      for (const peer of providers) {
        try {
          if (job.state !== 'saved-downloading') await set('saved-downloading');
          fetched = await this._fetch({ ...job.ref, peer }, { onProgress: (n, total) => { job.receivedBlocks = n; job.totalBlocks = total; } });
          break;
        } catch (e) { lastErr = e; }
      }
      if (fetched) {
        await set('verifying', { receivedBlocks: job.totalBlocks });
        try {
          const bytes = await this._assemble(fetched.core, fetched.manifest);
          const f = fetched.manifest.files[0];
          if (!mediaCheck(bytes, f.mediaType)) throw Object.assign(Error(`not a playable ${f.mediaType} file`), { code: 'EMEDIA' });
          const assetFile = this.dir('retention', 'assets', `${f.sha256}${EXT[f.mediaType] || '.bin'}`);
          if (!fs.existsSync(assetFile) || sha256(await fsp.readFile(assetFile)) !== f.sha256) await writeAtomic(assetFile, bytes);
          const receipt = await this._commitMembership(job, fetched.manifest, assetFile);
          await set('available-offline', { retained: receipt, error: null });
          this.log(`retained ${fetched.manifest.recording.title || f.assetId} (${bytes.length} bytes)`);
          return;
        } catch (e) {
          // wrong bytes never become "available offline"; the saved reference stays
          await set('download-failed-reference-saved', { error: { code: e.code || 'EVERIFY', message: e.message } });
          return;
        }
      }
      job.attempts++;
      const code = lastErr?.code || 'ESOURCE';
      if (code === 'EMANIFEST' || job.attempts >= 20) { await set('download-failed-reference-saved', { error: { code, message: lastErr?.message || 'source unavailable' } }); return; }
      await set('saved-waiting-source', { error: { code, message: lastErr?.message || 'source unavailable' } });
      await new Promise((r) => setTimeout(r, Math.min(60000, 2000 * 2 ** Math.min(job.attempts, 5))));
      if (this.closed) return;
    }
  }

  /** Library membership: neutral import of the offer's credits, recoverable and idempotent. */
  async _commitMembership(job, manifest, assetFile) {
    const file = this.dir('retention', 'library.json');
    const lib = fs.existsSync(file) ? JSON.parse(await fsp.readFile(file, 'utf8')) : { schema: 'hapa.music.retained-library.v1', entries: [] };
    let entry = lib.entries.find((e) => e.assetId === manifest.files[0].assetId);
    const discoveries = (await this.encounters()).filter((d) => d.assetId === manifest.files[0].assetId).map((d) => ({ discoveryId: d.discoveryId, introducer: d.introducer, encounter: d.encounter }));
    if (!entry) {
      entry = { libraryId: `retained:${manifest.files[0].sha256.slice(0, 24)}`, recordingId: manifest.recording.id, assetId: manifest.files[0].assetId, title: manifest.recording.title, version: manifest.recording.version, durationSeconds: manifest.recording.durationSeconds,
        credits: manifest.credits, source: { issuer: manifest.issuer, originId: manifest.recording.originId, manifestDigest: job.ref.manifestDigest, offeredCapabilities: manifest.capabilities },
        file: path.basename(assetFile), mediaType: manifest.files[0].mediaType, length: manifest.files[0].length, retainedAt: new Date().toISOString(), receiptId: randomUUID() };
      lib.entries.push(entry);
    }
    entry.introductions = discoveries;
    await writeAtomic(file, JSON.stringify(lib, null, 1));
    return { libraryId: entry.libraryId, receiptId: entry.receiptId, retainedAt: entry.retainedAt, file: entry.file };
  }

  async _refreshIntroductions(assetId) {
    const file = this.dir('retention', 'library.json');
    if (!fs.existsSync(file)) return;
    const lib = JSON.parse(await fsp.readFile(file, 'utf8'));
    const entry = lib.entries.find((e) => e.assetId === assetId);
    if (!entry) return;
    entry.introductions = (await this.encounters()).filter((d) => d.assetId === assetId).map((d) => ({ discoveryId: d.discoveryId, introducer: d.introducer, encounter: d.encounter }));
    await writeAtomic(file, JSON.stringify(lib, null, 1));
  }

  async encounters() {
    const file = this.dir('retention', 'discoveries.ndjson');
    if (!fs.existsSync(file)) return [];
    return (await fsp.readFile(file, 'utf8')).split('\n').filter(Boolean).map((l) => JSON.parse(l));
  }

  async retained() {
    const file = this.dir('retention', 'library.json');
    return fs.existsSync(file) ? JSON.parse(await fsp.readFile(file, 'utf8')).entries : [];
  }

  /** A retained recording's bytes, re-verified against its committed digest on every read. */
  async retainedAudio(libraryId) {
    const entry = (await this.retained()).find((e) => e.libraryId === libraryId);
    if (!entry) throw Object.assign(Error('not in this library'), { status: 404 });
    const bytes = await fsp.readFile(this.dir('retention', 'assets', entry.file));
    if (`sha256:${sha256(bytes)}` !== entry.assetId) throw Object.assign(Error('retained bytes changed'), { status: 500 });
    return { bytes, mediaType: entry.mediaType };
  }
}

module.exports = { PeerMusic, STATES, canonical, mediaCheck, OFFER_SCHEMA };
