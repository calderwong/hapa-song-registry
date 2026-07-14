const { createServer } = require('http');
const { createReadStream, statSync, readFileSync } = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const DATA_PATH = path.join(ROOT, 'data', 'registry.json');
const DEAR_PAPA_PLAYLIST_ID = process.env.HAPA_DEAR_PAPA_PLAYLIST_ID || '369daf97-0e07-4c49-a7a2-2a6f0b18353b';

let registryCache = null;
let registryMtimeMs = 0;

function startApiServer(options = {}) {
  const port = Number(options.port || process.env.HAPA_SONG_REGISTRY_API_PORT || 8798);
  const host = options.host || '127.0.0.1';
  const server = createServer((req, res) => {
    try {
      route(req, res);
    } catch (error) {
      sendJson(res, 500, { error: 'internal_error', message: error.message });
    }
  });
  server.listen(port, host, () => {
    console.log(`Hapa Song Registry API listening on http://${host}:${port}`);
  });
  return server;
}

function route(req, res) {
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
  const portArgIndex = process.argv.indexOf('--port');
  const port = portArgIndex >= 0 ? process.argv[portArgIndex + 1] : undefined;
  startApiServer({ port });
}

module.exports = { startApiServer };
