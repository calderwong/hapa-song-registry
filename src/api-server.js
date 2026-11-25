const { createServer } = require('http');
const { createReadStream, statSync, readFileSync, writeFileSync, existsSync, mkdirSync } = require('fs');
const path = require('path');
const { randomBytes, timingSafeEqual } = require('crypto');
const { PeerMusic } = require('./peer-music');

const ROOT = path.resolve(__dirname, '..');
// One library per data root (HAPA_SONG_REGISTRY_DATA_ROOT): the default is this checkout's data/.
// A second root is a separately owned library (its own registry, retention store and peer keys).
const DATA_ROOT = path.resolve(process.env.HAPA_SONG_REGISTRY_DATA_ROOT || path.join(ROOT, 'data'));
const DATA_PATH = path.join(DATA_ROOT, 'registry.json');
const NODE_ID = process.env.HAPA_SONG_REGISTRY_NODE_ID || 'song-registry';
const NODE_LABEL = process.env.HAPA_SONG_REGISTRY_NODE_LABEL || NODE_ID;
const TOKEN_FILE = path.join(DATA_ROOT, 'api-token');
let peer = null;

/** The bearer for writes and peer routes, created once per data root (0600). Reads stay as before. */
function apiToken() {
  if (!existsSync(TOKEN_FILE)) { mkdirSync(DATA_ROOT, { recursive: true }); writeFileSync(TOKEN_FILE, `${randomBytes(32).toString('hex')}\n`, { mode: 0o600, flag: 'wx' }); }
  return readFileSync(TOKEN_FILE, 'utf8').trim();
}
function authorized(req) {
  const m = /^Bearer ([a-f0-9]{64})$/.exec(req.headers.authorization || '');
  if (!m || req.headers.origin) return false; // only a server-side host client (no browser origin)
  const a = Buffer.from(m[1]), b = Buffer.from(apiToken());
  return a.length === b.length && timingSafeEqual(a, b);
}
async function readBody(req, limit = 64 * 1024) {
  let n = 0; const chunks = [];
  for await (const c of req) { n += c.length; if (n > limit) throw Object.assign(Error('body too large'), { status: 413 }); chunks.push(c); }
  try { return JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}'); } catch { throw Object.assign(Error('invalid json'), { status: 400 }); }
}
const DEAR_PAPA_PLAYLIST_ID = process.env.HAPA_DEAR_PAPA_PLAYLIST_ID || '369daf97-0e07-4c49-a7a2-2a6f0b18353b';

let registryCache = null;
let registryMtimeMs = 0;

function startApiServer(options = {}) {
  const port = Number(options.port || process.env.HAPA_SONG_REGISTRY_API_PORT || 8798);
  const host = options.host || '127.0.0.1';
  const peerPort = Number(options.peerPort || process.env.HAPA_SONG_REGISTRY_PEER_PORT || 0);
  apiToken();
  if (peerPort) {
    peer = new PeerMusic({ dataRoot: DATA_ROOT, nodeId: NODE_ID, label: NODE_LABEL, peerPort, findSong });
    peer.start().catch((e) => console.error(`[peer-music] failed to start: ${e.message}`));
  }
  const server = createServer((req, res) => {
    Promise.resolve().then(() => route(req, res)).catch((error) => {
      if (!res.headersSent) sendJson(res, error.status || 500, { error: error.status ? 'request_failed' : 'internal_error', message: error.message });
    });
  });
  server.peer = () => peer;
  server.listen(port, host, () => {
    console.log(`Hapa Song Registry API listening on http://${host}:${port}`);
  });
  return server;
}

async function route(req, res) {
  const probe = new URL(req.url || '/', 'http://127.0.0.1').pathname;
  if (probe.startsWith('/api/peer/')) return peerRoute(req, res, probe);
  setCors(req, res);
  if (req.method === 'OPTIONS') {
    res.writeHead(204);
    res.end();
    return;
  }

  const url = new URL(req.url || '/', `http://${req.headers.host || '127.0.0.1'}`);
  const pathname = decodeURIComponent(url.pathname);

  if (pathname === '/api/health') {
    const registry = loadRegistry();
    sendJson(res, 200, {
      ok: true,
      service: 'hapa-song-registry',
      registryPath: DATA_PATH,
      counts: registry.counts || {},
      time: new Date().toISOString()
    });
    return;
  }

  if (pathname === '/api/songs' && req.method === 'GET') {
    const registry = loadRegistry();
    const collection = String(url.searchParams.get('collection') || '').toLowerCase();
    const query = String(url.searchParams.get('q') || '').trim().toLowerCase();
    const limit = Math.max(1, Math.min(5000, Number(url.searchParams.get('limit') || 500)));
    let songs = registry.songs || [];
    if (collection === 'dear-papa') songs = songs.filter(isDearPapaSong);
    if (query) {
      songs = songs.filter((song) => [song.title, song.tags, song.lyrics]
        .some((value) => String(value || '').toLowerCase().includes(query)));
    }
    songs = songs
      .slice()
      .sort((a, b) => Number(a.raw?._hapaPlaylistExport?.trackNumber || 0) - Number(b.raw?._hapaPlaylistExport?.trackNumber || 0) || String(a.title).localeCompare(String(b.title)))
      .slice(0, limit);
    sendJson(res, 200, {
      schemaVersion: 'hapa.song-registry.api.songs.v1',
      collection: collection || 'all',
      total: songs.length,
      songs: songs.map(compactSong)
    });
    return;
  }

  const songMatch = pathname.match(/^\/api\/songs\/([^/]+)$/);
  if (songMatch && req.method === 'GET') {
    const song = findSong(songMatch[1]);
    if (!song) return sendJson(res, 404, { error: 'song_not_found', id: songMatch[1] });
    sendJson(res, 200, compactSong(song, { detail: true }));
    return;
  }

  const audioMatch = pathname.match(/^\/api\/audio\/([^/]+)$/);
  if (audioMatch && req.method === 'GET') {
    const song = findSong(audioMatch[1]);
    if (!song || !song.localPath) return sendJson(res, 404, { error: 'audio_not_found', id: audioMatch[1] });
    serveFile(song.localPath, req, res);
    return;
  }

  const coverMatch = pathname.match(/^\/api\/covers\/([^/]+)$/);
  if (coverMatch && req.method === 'GET') {
    const song = findSong(coverMatch[1]);
    const coverPath = song?.raw?._hapaPlaylistExport?.coverPath;
    if (!coverPath) return sendJson(res, 404, { error: 'cover_not_found', id: coverMatch[1] });
    serveFile(coverPath, req, res);
    return;
  }

  sendJson(res, 404, { error: 'not_found', path: pathname });
}

/**
 * Peer music routes (docs/PEER_MUSIC.md). Bearer-only, never CORS: a host backend (Hapa Versus'
 * dev server) calls them with this library's token; browsers never hold it.
 */
async function peerRoute(req, res, pathname) {
  if (!authorized(req)) return sendJson(res, 401, { error: 'unauthorized' });
  if (!peer) return sendJson(res, 503, { error: 'peer_music_disabled', message: 'start with --peer-port' });
  if (pathname === '/api/peer/node' && req.method === 'GET') {
    return sendJson(res, 200, { schema: 'hapa.music.node.v1', nodeId: NODE_ID, label: NODE_LABEL, peer: { host: '127.0.0.1', port: peer.peerPort }, offers: peer.offers.size, acquisitions: peer.jobs.size, retained: (await peer.retained()).length });
  }
  if (pathname === '/api/peer/songs' && req.method === 'GET') {
    // a host may browse this library to let its owner choose a contribution (selection only)
    const q = String(new URL(req.url, 'http://local').searchParams.get('q') || '').trim().toLowerCase();
    const songs = (loadRegistry().songs || []).filter((s) => s.localPath && (!q || `${s.title} ${(s.authors || []).join(' ')}`.toLowerCase().includes(q))).slice(0, q ? 60 : 2000).map((s) => ({ id: s.id, title: s.title, authors: s.authors || [], duration: s.duration || null, collection: isDearPapaSong(s) ? 'dear-papa' : 'song-registry' }));
    return sendJson(res, 200, { total: songs.length, songs });
  }
  if (pathname === '/api/peer/contributions' && req.method === 'POST') {
    const b = await readBody(req);
    if (!Array.isArray(b.songIds) || !b.songIds.length || b.songIds.length > 12) return sendJson(res, 400, { error: 'choose one to twelve songs' });
    const entries = [];
    for (const id of b.songIds) entries.push(await peer.offerSong(String(id)));
    const snapshot = { schema: 'hapa.music.contribution.v1', playlistId: `contribution:${NODE_ID}:${Date.now().toString(36)}`, revision: 1, contributor: { nodeId: NODE_ID, label: NODE_LABEL, participant: b.participant || null }, createdAt: new Date().toISOString(),
      entries: entries.map((offer, i) => ({ entryId: `${NODE_ID}-${i + 1}-${offer.manifest.files[0].sha256.slice(0, 8)}`, recordingId: offer.manifest.recording.id, title: offer.manifest.recording.title, credits: offer.manifest.credits, durationSeconds: offer.manifest.recording.durationSeconds, offer })) };
    return sendJson(res, 200, snapshot);
  }
  if (pathname === '/api/peer/audio' && req.method === 'POST') {
    const b = await readBody(req, 256 * 1024);
    const { bytes, mediaType } = await peer.peerAudio(b.offer);
    return sendBytes(req, res, bytes, mediaType);
  }
  if (pathname === '/api/peer/keep' && req.method === 'POST') {
    const b = await readBody(req, 256 * 1024);
    return sendJson(res, 200, await peer.keep(b.offer, b.discovery));
  }
  const keepMatch = pathname.match(/^\/api\/peer\/keep\/(acq-[a-f0-9]{32})$/);
  if (keepMatch && req.method === 'GET') {
    const st = peer.status(keepMatch[1]);
    return st ? sendJson(res, 200, st) : sendJson(res, 404, { error: 'acquisition_not_found' });
  }
  if (pathname === '/api/peer/encounters' && req.method === 'GET') {
    const list = await peer.encounters();
    return sendJson(res, 200, { schema: 'hapa.music.encounters.v1', encounters: list.map((d) => ({ ...d, acquisition: peer.status(`acq-${String(d.assetId).replace('sha256:', '').slice(0, 32)}`) })) });
  }
  if (pathname === '/api/peer/retained' && req.method === 'GET') return sendJson(res, 200, { schema: 'hapa.music.retained-library.v1', entries: await peer.retained() });
  const retainedMatch = pathname.match(/^\/api\/peer\/retained\/(retained:[a-f0-9]{24})\/audio$/);
  if (retainedMatch && req.method === 'GET') {
    const { bytes, mediaType } = await peer.retainedAudio(retainedMatch[1]);
    return sendBytes(req, res, bytes, mediaType);
  }
  return sendJson(res, 404, { error: 'not_found', path: pathname });
}

function sendBytes(req, res, bytes, mediaType) {
  const range = parseRange(req.headers.range, bytes.length);
  const head = { 'Content-Type': mediaType, 'Accept-Ranges': 'bytes', 'Cache-Control': 'private, no-store' };
  if (range) { res.writeHead(206, { ...head, 'Content-Length': range.end - range.start + 1, 'Content-Range': `bytes ${range.start}-${range.end}/${bytes.length}` }); res.end(bytes.subarray(range.start, range.end + 1)); return; }
  res.writeHead(200, { ...head, 'Content-Length': bytes.length }); res.end(bytes);
}

function loadRegistry() {
  const info = statSync(DATA_PATH);
  if (!registryCache || info.mtimeMs !== registryMtimeMs) {
    registryCache = JSON.parse(readFileSync(DATA_PATH, 'utf8'));
    registryMtimeMs = info.mtimeMs;
  }
  return registryCache;
}

function findSong(id) {
  const registry = loadRegistry();
  const decoded = decodeURIComponent(id);
  return (registry.songs || []).find((song) => song.id === decoded || song.title === decoded);
}

function compactSong(song, options = {}) {
  const exportInfo = song.raw?._hapaPlaylistExport || {};
  const payload = {
    id: song.id,
    title: song.title,
    authors: song.authors || [],
    duration: song.duration || null,
    createdAt: song.createdAt || null,
    model: song.model || null,
    majorModelVersion: song.majorModelVersion || null,
    contentType: song.contentType || 'song',
    stemCount: song.stemCount || 0,
    tags: song.tags || '',
    localAvailable: Boolean(song.localPath),
    audioUri: song.localPath ? `/api/audio/${encodeURIComponent(song.id)}` : song.audioUrl || null,
    coverUri: exportInfo.coverPath ? `/api/covers/${encodeURIComponent(song.id)}` : song.imageUrl || null,
    lyrics: song.lyrics || '',
    source: {
      registry: 'hapa-song-registry',
      collection: isDearPapaSong(song) ? 'dear-papa' : 'song-registry',
      playlistId: playlistIdForSong(song),
      localPath: song.localPath || null
    }
  };
  if (options.detail) {
    payload.lyricTiming = song.lyricTiming || null;
    payload.promptGroupId = song.promptGroupId || null;
    payload.lyricMasterId = song.lyricMasterId || null;
    payload.facets = song.facets || {};
    payload.rawExport = exportInfo;
  }
  return payload;
}

function isDearPapaSong(song) {
  const exportInfo = song.raw?._hapaPlaylistExport || {};
  return exportInfo.kind === 'song' && String(exportInfo.songDir || '').includes(`/playlists/${DEAR_PAPA_PLAYLIST_ID}/songs/`);
}

function playlistIdForSong(song) {
  const songDir = song.raw?._hapaPlaylistExport?.songDir || '';
  const match = String(songDir).match(/\/playlists\/([^/]+)\/songs\//);
  return match ? match[1] : null;
}

function serveFile(filePath, req, res) {
  const safePath = path.resolve(filePath);
  const info = statSync(safePath);
  if (!info.isFile()) return sendJson(res, 404, { error: 'file_not_found' });
  const range = parseRange(req.headers.range, info.size);
  if (range) {
    res.writeHead(206, {
      'Content-Type': contentType(safePath),
      'Content-Length': range.end - range.start + 1,
      'Content-Range': `bytes ${range.start}-${range.end}/${info.size}`,
      'Accept-Ranges': 'bytes',
      'Cache-Control': 'private, max-age=3600'
    });
    createReadStream(safePath, { start: range.start, end: range.end }).pipe(res);
    return true;
  }
  res.writeHead(200, {
    'Content-Type': contentType(safePath),
    'Content-Length': info.size,
    'Accept-Ranges': 'bytes',
    'Cache-Control': 'private, max-age=3600'
  });
  createReadStream(safePath).pipe(res);
  return true;
}

function parseRange(rangeHeader, size) {
  if (!rangeHeader || !/^bytes=/.test(rangeHeader)) return null;
  const [startText, endText] = rangeHeader.replace(/^bytes=/, '').split('-');
  const start = startText ? Number(startText) : 0;
  const end = endText ? Number(endText) : size - 1;
  if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end < start || start >= size) return null;
  return { start, end: Math.min(end, size - 1) };
}

function contentType(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  return {
    '.mp3': 'audio/mpeg',
    '.m4a': 'audio/mp4',
    '.wav': 'audio/wav',
    '.flac': 'audio/flac',
    '.ogg': 'audio/ogg',
    '.webm': 'audio/webm',
    '.aac': 'audio/aac',
    '.jpeg': 'image/jpeg',
    '.jpg': 'image/jpeg',
    '.png': 'image/png',
    '.webp': 'image/webp',
    '.json': 'application/json; charset=utf-8'
  }[ext] || 'application/octet-stream';
}

function sendJson(res, statusCode, payload) {
  res.writeHead(statusCode, { 'Content-Type': 'application/json; charset=utf-8' });
  res.end(`${JSON.stringify(payload, null, 2)}\n`);
}

function setCors(req, res) {
  const origin = req.headers.origin || '*';
  res.setHeader('Access-Control-Allow-Origin', origin);
  res.setHeader('Vary', 'Origin');
  res.setHeader('Access-Control-Allow-Methods', 'GET,OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Range');
  res.setHeader('Access-Control-Expose-Headers', 'Content-Range, Accept-Ranges, Content-Length');
}

if (require.main === module) {
  const arg = (name) => { const i = process.argv.indexOf(name); return i >= 0 ? process.argv[i + 1] : undefined; };
  startApiServer({ port: arg('--port'), peerPort: arg('--peer-port') });
}

module.exports = { startApiServer };
