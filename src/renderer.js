const state = {
  registry: null,
  songs: [],
  filtered: [],
  current: null,
  queue: [],
  audioCtx: null,
  analyser: null,
  source: null,
  stems: new Map(),
  stemAnalysers: new Map(),
  raf: null,
  events: [],
  meta: new Map(),
  loops: [],
  derivatives: [],
  masters: new Map(),
  selectedMixer: new Map(),
  loopPointer: null,
  endLoopMarker: null,
  stemAnalysis: new Map(),
  stemMuteState: new Map(),
  stemSoloState: new Set(),
  stemSessionPlaying: false,
  loopStopTimer: null,
  dawEngine: null,
  dawSessionSongId: null,
  dawIncludeMain: false,
  dawStatusRaf: null,
  dawVisualRaf: null,
  dawSpectrogramHistory: new Map(),
  audioTelemetryRuns: new Map(),
  audioTelemetryQueue: null,
  uiFeedbackInstalled: false,
};

const $ = (id) => document.getElementById(id);
const uiAudio = {
  ctx: null,
  muted: localStorage.getItem('hapa-song-registry-muted') === 'true',
  master: null,
  compressor: null,
};
const fmt = (seconds) => {
  seconds = Number(seconds || 0);
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60).toString().padStart(2, '0');
  return `${m}:${s}`;
};
const uniq = (arr) => [...new Set((arr || []).filter(Boolean))].sort((a, b) => String(a).localeCompare(String(b)));
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const clamp = (n, min, max) => Math.max(min, Math.min(max, Number(n || 0)));
const idFor = (prefix) => `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
const rawMetric = (item, key) => Number(item?.raw?.[key] || item?.[key] || 0);

function getUiAudioContext() {
  if (!uiAudio.ctx) uiAudio.ctx = new (window.AudioContext || window.webkitAudioContext)();
  return uiAudio.ctx;
}

function getUiOutput(ctx) {
  if (!uiAudio.master || !uiAudio.compressor) {
    uiAudio.master = ctx.createGain();
    uiAudio.compressor = ctx.createDynamicsCompressor();
    uiAudio.compressor.threshold.setValueAtTime(-26, ctx.currentTime);
    uiAudio.compressor.knee.setValueAtTime(18, ctx.currentTime);
    uiAudio.compressor.ratio.setValueAtTime(5, ctx.currentTime);
    uiAudio.compressor.attack.setValueAtTime(0.003, ctx.currentTime);
    uiAudio.compressor.release.setValueAtTime(0.11, ctx.currentTime);
    uiAudio.master.gain.setValueAtTime(0.72, ctx.currentTime);
    uiAudio.master.connect(uiAudio.compressor);
    uiAudio.compressor.connect(ctx.destination);
  }
  return uiAudio.master;
}

function playUiTone(type, startFreq, endFreq, duration, startGain = 0.032) {
  if (uiAudio.muted) return;
  try {
    const ctx = getUiAudioContext();
    if (ctx.state === 'suspended') ctx.resume();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = type;
    osc.frequency.setValueAtTime(startFreq, ctx.currentTime);
    osc.frequency.exponentialRampToValueAtTime(Math.max(1, endFreq), ctx.currentTime + duration);
    gain.gain.setValueAtTime(startGain, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + duration);
    osc.connect(gain);
    gain.connect(getUiOutput(ctx));
    osc.start(ctx.currentTime);
    osc.stop(ctx.currentTime + duration);
  } catch (err) {
    console.debug('UI audio unavailable', err);
  }
}

function playUiSound(kind = 'click') {
  if (kind === 'hover') return playUiTone('sine', 760, 1120, 0.045, 0.02);
  if (kind === 'open') return playUiTone('triangle', 420, 680, 0.09, 0.026);
  if (kind === 'select') return playUiTone('sawtooth', 860, 520, 0.085, 0.032);
  return playUiTone('square', 560, 280, 0.07, 0.034);
}

function syncSoundToggle() {
  const btn = $('soundToggle');
  if (!btn) return;
  btn.textContent = uiAudio.muted ? 'SFX OFF' : 'SFX ON';
  btn.setAttribute('aria-pressed', String(!uiAudio.muted));
  btn.classList.toggle('muted', uiAudio.muted);
}

function closestUi(event, selector) {
  const target = event.target;
  return target instanceof Element ? target.closest(selector) : null;
}

function installUiFeedback() {
  if (state.uiFeedbackInstalled) return;
  state.uiFeedbackInstalled = true;
  syncSoundToggle();

  let lastHovered = null;
  document.addEventListener('pointerover', (event) => {
    const target = closestUi(event, 'button, select, .song-card, .mini-card, .node, .relation, .tab, .facet, .loop-card');
    if (!target || target === lastHovered) return;
    lastHovered = target;
    playUiSound('hover');
  }, true);

  document.addEventListener('pointerout', (event) => {
    if (!event.relatedTarget || !(event.relatedTarget instanceof Node) || !lastHovered?.contains(event.relatedTarget)) lastHovered = null;
  }, true);

  document.addEventListener('click', (event) => {
    if (closestUi(event, 'button, .song-card, .mini-card, .node, .relation, .tab, .facet, .loop-card')) playUiSound('click');
  }, true);

  document.addEventListener('pointerdown', (event) => {
    if (closestUi(event, 'select')) playUiSound('open');
  }, true);

  document.addEventListener('change', (event) => {
    if (closestUi(event, 'select, input[type="checkbox"]')) playUiSound('select');
  }, true);

  $('soundToggle')?.addEventListener('click', () => {
    uiAudio.muted = !uiAudio.muted;
    localStorage.setItem('hapa-song-registry-muted', String(uiAudio.muted));
    syncSoundToggle();
  });
}

function virtualExternalLyricSongs() {
  const existingIds = new Set((state.registry?.songs || []).map((s) => s.id));
  const docsById = new Map((state.registry?.externalLyrics || []).map((doc) => [doc.id, doc]));
  const virtuals = [];
  for (const master of state.registry?.lyricMasters || []) {
    const hasSongVariation = (master.variations || []).some((v) => v.kind === 'song' && existingIds.has(v.id));
    if (hasSongVariation) continue;
    for (const variation of master.variations || []) {
      if (variation.kind !== 'external_lyric') continue;
      const doc = docsById.get(variation.id) || variation;
      virtuals.push({
        id: doc.id,
        title: doc.title || master.sourceTitle || 'External lyrics',
        kind: 'external_lyric',
        sourcePath: doc.path,
        localPath: null,
        audioUrl: null,
        imageUrl: '',
        duration: 0,
        model: 'lyrics-only',
        lyrics: doc.lyrics || master.lyrics || '',
        prompt: doc.lyrics || master.lyrics || '',
        tags: 'external lyrics no music',
        facets: { themes: ['lyrics-only'], instruments: ['none'], mood: ['unspecified'], message: ['unspecified'] },
        stemCount: 0,
        stemTypes: [],
        lyricMasterId: master.id,
        authors: master.authors || state.registry.defaultAuthors || [],
        raw: { external_lyric: true, path: doc.path },
      });
    }
  }
  return virtuals;
}

function hasMusic(item) {
  return Boolean(item?.localPath || item?.audioUrl);
}

function stemCountFor(item) {
  if (!item) return 0;
  return allStemsForMaster(item.id).length || Number(item?.stemCount || stemsForVariation(item.id).length || 0);
}

function variationCountFor(item) {
  return masterInfoFor(item?.id).variations.length;
}

function songForId(id) {
  return state.songs.find((s) => s.id === id);
}

function stemsForVariation(id) {
  return (state.registry.stems || []).filter((s) => s.parentId === id && s.localPath);
}

function allStemsForMaster(id) {
  const master = masterInfoFor(id);
  const ids = new Set([id, ...(master.variations || [])]);
  return (state.registry.stems || []).filter((s) => ids.has(s.parentId) && s.localPath);
}

function stemPlayable(stem) {
  return Boolean(stem?.localPath);
}

function bpmFor(song = state.current) {
  return Number(song?.settings?.bpm || song?.raw?.bpm || 120);
}

function countsToSeconds(counts, song = state.current) {
  return (60 / Math.max(1, bpmFor(song))) * Number(counts || 0);
}

function ensureDawEngine() {
  if (!state.dawEngine) {
    state.dawEngine = new window.HapaDawEngine();
    state.audioCtx = state.dawEngine.ctx;
  }
  return state.dawEngine;
}

async function loadDawSessionForCurrent(song = state.current) {
  if (!song || !window.HapaDawEngine) return null;
  const engine = ensureDawEngine();
  engine.pause();
  engine.clearTracks();
  state.dawSpectrogramHistory.clear();
  state.dawSessionSongId = song.id;
  const loadErrors = [];
  const specs = [];
  if (hasMusic(song) && song.localPath) {
    specs.push({ id: `song:${song.id}`, type: 'main', title: displayTitle(song), path: song.localPath, url: await window.hapa.fileUrl(song.localPath), volume: $('muteMain')?.checked ? 0 : 1 });
  }
  for (const stem of stemsForVariation(song.id)) {
    specs.push({ id: stem.id, type: 'stem', title: displayTitle(stem, 'stem'), path: stem.localPath, url: await window.hapa.fileUrl(stem.localPath), volume: 0.95 });
  }
  for (const spec of specs) {
    try { await engine.loadTrack(spec); }
    catch (err) { loadErrors.push(`${spec.title}: ${err.message}`); }
  }
  if (loadErrors.length) toast(`DAW loaded with ${loadErrors.length} audio decode warning(s).`);
  applyStemMixState();
  return engine;
}

async function decodeStemAudio(stem) {
  if (state.dawEngine?.tracks?.has(stem.id)) return state.dawEngine.tracks.get(stem.id).buffer;
  if (!state.audioCtx) state.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  const url = await window.hapa.fileUrl(stem.localPath);
  const response = await fetch(url);
  const bytes = await response.arrayBuffer();
  return state.audioCtx.decodeAudioData(bytes.slice(0));
}

function computeWaveformPeaks(buffer, buckets = 360) {
  const channel = buffer.getChannelData(0);
  const step = Math.max(1, Math.floor(channel.length / buckets));
  const peaks = [];
  for (let i = 0; i < buckets; i++) {
    let min = 0, max = 0;
    const start = i * step;
    const end = Math.min(channel.length, start + step);
    for (let j = start; j < end; j++) {
      const sample = channel[j] || 0;
      if (sample < min) min = sample;
      if (sample > max) max = sample;
    }
    peaks.push({ min, max });
  }
  return peaks;
}

function fftMagnitudes(samples) {
  const n = samples.length;
  const re = samples.slice();
  const im = new Array(n).fill(0);
  for (let i = 1, j = 0; i < n; i++) {
    let bit = n >> 1;
    for (; j & bit; bit >>= 1) j ^= bit;
    j ^= bit;
    if (i < j) { [re[i], re[j]] = [re[j], re[i]]; [im[i], im[j]] = [im[j], im[i]]; }
  }
  for (let len = 2; len <= n; len <<= 1) {
    const ang = -2 * Math.PI / len;
    const wLenRe = Math.cos(ang), wLenIm = Math.sin(ang);
    for (let i = 0; i < n; i += len) {
      let wRe = 1, wIm = 0;
      for (let j = 0; j < len / 2; j++) {
        const uRe = re[i + j], uIm = im[i + j];
        const vRe = re[i + j + len / 2] * wRe - im[i + j + len / 2] * wIm;
        const vIm = re[i + j + len / 2] * wIm + im[i + j + len / 2] * wRe;
        re[i + j] = uRe + vRe; im[i + j] = uIm + vIm;
        re[i + j + len / 2] = uRe - vRe; im[i + j + len / 2] = uIm - vIm;
        const nextRe = wRe * wLenRe - wIm * wLenIm;
        wIm = wRe * wLenIm + wIm * wLenRe;
        wRe = nextRe;
      }
    }
  }
  return re.slice(0, n / 2).map((x, i) => Math.sqrt(x * x + im[i] * im[i]) / (n / 2));
}

function computeSpectrogramFrames(buffer, frameCount = 80, binCount = 48) {
  const channel = buffer.getChannelData(0);
  const fftSize = 1024;
  const hop = Math.max(1, Math.floor((channel.length - fftSize) / Math.max(1, frameCount - 1)));
  const frames = [];
  for (let frame = 0; frame < frameCount; frame++) {
    const offset = frame * hop;
    const windowed = new Array(fftSize);
    for (let n = 0; n < fftSize; n++) {
      const hann = 0.5 * (1 - Math.cos((2 * Math.PI * n) / (fftSize - 1)));
      windowed[n] = (channel[offset + n] || 0) * hann;
    }
    const mags = fftMagnitudes(windowed);
    const grouped = [];
    for (let bin = 0; bin < binCount; bin++) {
      const start = Math.floor((bin / binCount) * mags.length);
      const end = Math.max(start + 1, Math.floor(((bin + 1) / binCount) * mags.length));
      const avg = mags.slice(start, end).reduce((a, b) => a + b, 0) / (end - start);
      grouped.push(Math.min(1, Math.log10(1 + avg * 24)));
    }
    frames.push(grouped);
  }
  return frames;
}

async function analyzeStemAudio(stem) {
  if (state.stemAnalysis.has(stem.id)) return state.stemAnalysis.get(stem.id);
  const pending = (async () => {
    if (state.dawEngine?.tracks?.has(stem.id)) return state.dawEngine.getTrackAnalysis(stem.id);
    const buffer = await decodeStemAudio(stem);
    const waveform = computeWaveformPeaks(buffer);
    const spectrogram = computeSpectrogramFrames(buffer);
    const fft = spectrogram.reduce((acc, frame) => frame.map((v, i) => Math.max(v, acc[i] || 0)), []);
    return { waveform, spectrogram, fft, duration: buffer.duration, sampleRate: buffer.sampleRate, real: true };
  })().catch((err) => {
    console.warn('Stem analysis failed', stem.id, err);
    return { waveform: [], spectrogram: [], fft: [], error: err.message, real: false };
  });
  state.stemAnalysis.set(stem.id, pending);
  const analysis = await pending;
  state.stemAnalysis.set(stem.id, analysis);
  return analysis;
}

async function init() {
  state.registry = await window.hapa.loadRegistry();
  state.songs = [...(state.registry.songs || []), ...virtualExternalLyricSongs()];
  state.events = state.registry.historyEvents || [];
  applyHistory();
  buildMasters();
  hydrateFilters();
  wireEvents();
  renderStats();
  applyFilters();
  if (state.filtered[0]) selectSong(state.filtered[0].id, false);
  renderLoopDock();
  drawIdle();
}

function applyHistory() {
  state.meta.clear();
  state.loops = [];
  state.derivatives = [];
  for (const event of state.events) applyEvent(event, false);
}

function metaFor(targetType, targetId) {
  const key = `${targetType}:${targetId}`;
  if (!state.meta.has(key)) state.meta.set(key, { likes: 0, plays: 0, rating: 0, title: null, notes: '' });
  return state.meta.get(key);
}

function applyEvent(event, render = true) {
  if (!event) return;
  const type = event.type || '';
  const targetType = event.targetType || (type.startsWith('stem.') ? 'stem' : type.startsWith('loop.') ? 'loop' : 'song');
  const targetId = event.targetId || event.songId || event.stemId || event.loopId || event.derivativeId;
  if (type === 'loop.created') {
    const loop = { ...event, id: event.loopId || targetId || idFor('loop') };
    const idx = state.loops.findIndex((x) => x.id === loop.id);
    if (idx >= 0) state.loops[idx] = { ...state.loops[idx], ...loop };
    else state.loops.push(loop);
  } else if (type === 'derivative.created') {
    state.derivatives.push({ ...event, id: event.derivativeId || targetId || idFor('derivative') });
  }
  if (targetId) {
    const meta = metaFor(targetType, targetId);
    if (type.endsWith('.renamed')) meta.title = event.title || event.newTitle || meta.title;
    if (type.endsWith('.liked')) meta.likes += event.value === false ? -1 : 1;
    if (type.endsWith('.played')) meta.plays += Number(event.count || 1);
    if (type.endsWith('.rated')) meta.rating = Number(event.rating || event.value || 0);
    if (type.endsWith('.noted')) meta.notes = event.notes || '';
  }
  if (render) refreshAll();
}

async function appendEvent(event) {
  const saved = await window.hapa.appendHistory(event);
  state.events.push(saved);
  applyEvent(saved, true);
  toast('Saved to append-only history.');
  return saved;
}

function displayTitle(item, targetType = 'song') {
  if (!item) return '';
  return metaFor(targetType, item.id).title || item.title || item.id;
}

function engagementFor(item, targetType = 'song') {
  const meta = metaFor(targetType, item.id);
  return {
    likes: Math.max(0, rawMetric(item, 'upvote_count') + meta.likes),
    plays: Math.max(0, rawMetric(item, 'play_count') + meta.plays),
    rating: meta.rating,
  };
}

function engagementScore(item, targetType = 'song') {
  const e = engagementFor(item, targetType);
  return e.plays + e.likes * 10 + e.rating * 20;
}

function buildMasters() {
  state.masters.clear();
  const songIds = new Set(state.songs.map((s) => s.id));
  for (const master of state.registry.lyricMasters || []) {
    const ids = (master.variations || []).map((v) => v.id).filter((id) => songIds.has(id));
    if (!ids.length) continue;
    const firstSong = ids.find((id) => (state.registry.songs || []).some((s) => s.id === id)) || ids[0];
    state.masters.set(firstSong, { masterId: firstSong, key: master.id, variations: ids, lyricMaster: master });
  }
  const grouped = new Set([...state.masters.values()].flatMap((info) => info.variations));
  for (const song of state.songs) {
    if (!grouped.has(song.id) && !state.masters.has(song.id)) state.masters.set(song.id, { masterId: song.id, key: song.lyricMasterId || song.id, variations: [song.id] });
  }
}

function masterInfoFor(songId) {
  for (const info of state.masters.values()) if (info.variations.includes(songId)) return info;
  return { masterId: songId, variations: [songId] };
}

function promptGroupForSong(songId) {
  return (state.registry.promptGroups || []).find((g) => (g.songIds || []).includes(songId)) || null;
}

function promptGroupsForMaster(songId) {
  const master = masterInfoFor(songId);
  return (state.registry.promptGroups || []).filter((g) => g.lyricMasterId === master.key || g.lyricMasterId === master.lyricMaster?.id || (g.songIds || []).some((id) => master.variations.includes(id)));
}

function promptGroupLabel(group) {
  if (!group) return 'Ungrouped prompt';
  const style = String(group.stylePrompt || '').split('\n').find(Boolean) || 'Untitled prompt';
  return `${style.slice(0, 64)}${style.length > 64 ? '…' : ''} (${group.songCount || (group.songIds || []).length})`;
}

function contentTypeFor(song) {
  return song?.contentType || (song?.isMashup ? 'mashup' : 'song');
}

function isMashup(song) {
  return Boolean(song?.isMashup || contentTypeFor(song) === 'mashup');
}

function hydrateFilters() {
  const facets = state.registry.facets || {};
  fillSelect('themeFilter', (facets.themes || []).map((x) => x.name));
  fillSelect('instrumentFilter', (facets.instruments || []).map((x) => x.name));
  fillSelect('moodFilter', (facets.mood || []).map((x) => x.name));
  fillSelect('messageFilter', (facets.message || []).map((x) => x.name));
  fillSelect('modelFilter', (facets.models || []).map((x) => x.name));
  fillSelect('promptGroupFilter', (state.registry.promptGroups || []).map((g) => ({ value: g.id, label: promptGroupLabel(g) })));
}
function fillSelect(id, values) {
  const select = $(id);
  uniq(values.map((v) => typeof v === 'string' ? v : v.value)).forEach((v) => {
    const raw = values.find((item) => (typeof item === 'string' ? item : item.value) === v);
    const opt = document.createElement('option'); opt.value = v; opt.textContent = typeof raw === 'string' ? raw : (raw.label || raw.value);
    select.appendChild(opt);
  });
}

function wireEvents() {
  ['search', 'sort', 'themeFilter', 'instrumentFilter', 'moodFilter', 'messageFilter', 'modelFilter', 'promptGroupFilter', 'contentTypeFilter', 'audioFilter', 'variationMin', 'variationMax', 'hasStems', 'uniqueMasters', 'likedOnly'].forEach((id) => {
    $(id).addEventListener(['search', 'variationMin', 'variationMax'].includes(id) ? 'input' : 'change', applyFilters);
  });
  $('play').addEventListener('click', togglePlay);
  $('prev').addEventListener('click', () => playAdjacent(-1));
  $('next').addEventListener('click', () => playAdjacent(1));
  $('muteMain').addEventListener('change', () => { $('mainAudio').muted = $('muteMain').checked; if (state.dawEngine?.tracks?.has(`song:${state.current?.id}`)) state.dawEngine.setTrackMute(`song:${state.current.id}`, $('muteMain').checked || !state.dawIncludeMain); });
  $('seek').addEventListener('input', () => {
    const a = $('mainAudio');
    if (a.duration) {
      a.currentTime = (Number($('seek').value) / 1000) * a.duration;
      syncStemsToMain();
    }
  });
  $('mainAudio').addEventListener('timeupdate', onTime);
  $('mainAudio').addEventListener('play', () => { state.current && recordPlay('song', state.current.id); playStemSession($('mainAudio').currentTime || 0, { includeMain: false }); });
  $('mainAudio').addEventListener('pause', () => { if (!state.stemSessionPlaying) return; if (state.dawEngine) state.dawEngine.pause(); for (const item of state.stems.values()) item.audio.pause(); state.stemSessionPlaying = false; });
  $('mainAudio').addEventListener('seeked', () => syncStemsToMain());
  $('mainAudio').addEventListener('ended', () => playAdjacent(1));
  $('addFiltered').addEventListener('click', () => { state.queue = state.filtered.map((s) => s.id); renderQueue(); });
  $('clearQueue').addEventListener('click', () => { state.queue = []; renderQueue(); });
  $('openData').addEventListener('click', () => window.hapa.openDataFolder());
  $('showFile').addEventListener('click', () => state.current?.localPath && window.hapa.showInFolder(state.current.localPath));
  $('closeTimelinePage').addEventListener('click', closeTimelinePage);
  $('timelinePage').addEventListener('click', (e) => { if (e.target.id === 'timelinePage') closeTimelinePage(); });
  $('closeStemLabPage').addEventListener('click', closeStemLabPage);
  $('stemLabPage').addEventListener('click', (e) => { if (e.target.id === 'stemLabPage') closeStemLabPage(); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { closeTimelinePage(); closeStemLabPage(); } });
  document.querySelectorAll('.tab').forEach((btn) => btn.addEventListener('click', () => switchTab(btn.dataset.tab)));
  installUiFeedback();
}

function renderStats() {
  const stemCount = (state.registry.stems || []).length;
  $('stats').innerHTML = [
    ['Songs', state.songs.length], ['Stems', stemCount],
    ['Masters', state.masters.size], ['Prompt groups', (state.registry.promptGroups || []).length],
    ['Mashups', (state.registry.counts || {}).mashups || state.songs.filter(isMashup).length], ['Audio telemetry', (state.registry.counts || {}).audioTelemetry || state.songs.filter((s) => s.audioTelemetry).length], ['Loops', state.loops.length],
  ].map(([label, val]) => `<div class="stat"><b>${Number(val).toLocaleString()}</b><span>${label}</span></div>`).join('');
}

function applyFilters() {
  const q = $('search').value.trim().toLowerCase();
  const theme = $('themeFilter').value, inst = $('instrumentFilter').value, mood = $('moodFilter').value, msg = $('messageFilter').value, model = $('modelFilter').value;
  const promptGroup = $('promptGroupFilter').value;
  const contentMode = $('contentTypeFilter').value;
  const audioMode = $('audioFilter').value;
  const minVariations = $('variationMin').value === '' ? null : Number($('variationMin').value);
  const maxVariations = $('variationMax').value === '' ? null : Number($('variationMax').value);
  const hasStems = $('hasStems').checked;
  const likedOnly = $('likedOnly').checked;
  const base = state.songs.filter((s) => {
    const stemText = allStemsForMaster(s.id).map((st) => `${displayTitle(st, 'stem')} ${st.stemType}`).join(' ');
    const pg = promptGroupForSong(s.id);
    const promptGroupText = `${pg?.stylePrompt || ''} ${(promptGroupsForMaster(s.id) || []).map(promptGroupLabel).join(' ')}`;
    const hay = `${displayTitle(s)} ${s.prompt || ''} ${s.stylePrompt || ''} ${promptGroupText} ${s.lyrics || ''} ${s.tags || ''} ${s.model || ''} ${contentTypeFor(s)} ${stemText}`.toLowerCase();
    const e = engagementFor(s, 'song');
    const stems = stemCountFor(s);
    const variations = variationCountFor(s);
    return (!q || hay.includes(q)) &&
      (!theme || (s.facets?.themes || []).includes(theme)) &&
      (!inst || (s.facets?.instruments || []).includes(inst)) &&
      (!mood || (s.facets?.mood || []).includes(mood)) &&
      (!msg || (s.facets?.message || []).includes(msg)) &&
      (!model || s.model === model) &&
      (!promptGroup || s.promptGroupId === promptGroup || (promptGroupForSong(s.id)?.id === promptGroup)) &&
      (!(contentMode === 'mashup') || isMashup(s)) &&
      (!(contentMode === 'non_mashup') || !isMashup(s)) &&
      (!hasStems || stems > 0) &&
      (!(audioMode === 'has_music') || hasMusic(s)) &&
      (!(audioMode === 'no_music') || !hasMusic(s)) &&
      (!(audioMode === 'has_stems') || stems > 0) &&
      (!(audioMode === 'no_stems') || stems === 0) &&
      (minVariations === null || variations >= minVariations) &&
      (maxVariations === null || variations <= maxVariations) &&
      (!likedOnly || e.likes > 0 || e.rating > 0);
  });
  state.filtered = $('uniqueMasters').checked ? uniqueMasterSongs(base) : base;
  sortSongs();
  renderSongList();
}

function uniqueMasterSongs(pool) {
  const ids = new Set(pool.map((s) => s.id));
  const rows = [];
  for (const info of state.masters.values()) {
    const firstMatching = info.variations.map((id) => state.songs.find((s) => s.id === id)).find((s) => s && ids.has(s.id));
    if (!firstMatching) continue;
    const master = state.songs.find((s) => s.id === info.masterId) || firstMatching;
    rows.push(ids.has(master.id) ? master : firstMatching);
  }
  return rows;
}

function sortSongs() {
  const mode = $('sort').value;
  const cmp = {
    created_desc: (a, b) => String(b.createdAt || '').localeCompare(String(a.createdAt || '')),
    created_asc: (a, b) => String(a.createdAt || '').localeCompare(String(b.createdAt || '')),
    title_asc: (a, b) => displayTitle(a).localeCompare(displayTitle(b)),
    duration_desc: (a, b) => (b.duration || 0) - (a.duration || 0),
    stems_desc: (a, b) => stemCountFor(b) - stemCountFor(a),
    variations_desc: (a, b) => variationCountFor(b) - variationCountFor(a),
    variations_asc: (a, b) => variationCountFor(a) - variationCountFor(b),
    engagement_desc: (a, b) => engagementScore(b, 'song') - engagementScore(a, 'song'),
    rating_desc: (a, b) => engagementFor(b, 'song').rating - engagementFor(a, 'song').rating,
    model_asc: (a, b) => String(a.model || '').localeCompare(String(b.model || '')),
  }[mode];
  state.filtered.sort(cmp);
}

function renderSongList() {
  $('resultCount').textContent = `${state.filtered.length.toLocaleString()} ${$('uniqueMasters').checked ? 'lyric masters' : 'songs'}`;
  const list = $('songList');
  const rows = state.filtered.slice(0, 700).map((s) => {
    const master = masterInfoFor(s.id);
    const pg = promptGroupForSong(s.id);
    const e = engagementFor(s, 'song');
    return `<div class="song-card ${state.current?.id === s.id ? 'active' : ''}" data-id="${s.id}">
      <h3>${esc(displayTitle(s))}</h3>
      <p>${esc(s.model || 'unknown')} • ${esc(contentTypeFor(s))} • ${hasMusic(s) ? fmt(s.duration) : 'lyrics only'} • ${stemCountFor(s)} stems • ${variationCountFor(s)} variations • ${promptGroupsForMaster(s.id).length} prompt groups</p>
      <div class="badges">${pg ? `<span class="badge gold">prompt: ${esc(promptGroupLabel(pg))}</span>` : ''}${isMashup(s) ? '<span class="badge hot">mashup</span>' : ''}${[...(s.facets?.mood || []).slice(0, 2), ...(s.facets?.themes || []).slice(0, 2)].map((x) => `<span class="badge">${esc(x)}</span>`).join('')}${stemCountFor(s) ? '<span class="badge hot">stems</span>' : '<span class="badge">no stems</span>'}${hasMusic(s) ? '' : '<span class="badge gold">no music</span>'}<span class="badge">▶ ${e.plays}</span><span class="badge">♥ ${e.likes}</span>${e.rating ? `<span class="badge gold">★ ${e.rating}</span>` : ''}</div>
    </div>`;
  }).join('');
  list.innerHTML = rows || '<div class="empty">No songs match the current filters.</div>';
  list.querySelectorAll('.song-card').forEach((el) => el.addEventListener('click', () => selectSong(el.dataset.id, true)));
}

async function selectSong(id, autoplay = false) {
  const song = state.songs.find((s) => s.id === id); if (!song) return;
  state.current = song;
  renderSongList(); renderNow(); renderQueue();
  await loadMainAudio(song);
  await loadStemDeck(song);
  await loadDawSessionForCurrent(song);
  await loadAudioTelemetryForCurrent(song);
  renderDetails();
  if (autoplay) playAll();
}

async function loadAudioTelemetryForCurrent(song) {
  if (!song || !window.hapa?.loadAudioTelemetry) return null;
  if (state.audioTelemetryRuns.has(song.id)) return state.audioTelemetryRuns.get(song.id);
  try {
    const run = await window.hapa.loadAudioTelemetry(song.id);
    if (run) state.audioTelemetryRuns.set(song.id, run);
    return run;
  } catch (err) {
    console.warn('audio telemetry load failed', err);
    return null;
  }
}

function audioTelemetryFor(song = state.current) {
  if (!song) return null;
  return state.audioTelemetryRuns.get(song.id) || song.audioTelemetry || null;
}

async function analyzeCurrentAudioTelemetry() {
  if (!state.current || !window.hapa?.analyzeAudioTelemetry) return;
  const song = state.current;
  const tab = $('tab-telemetry');
  if (tab) tab.insertAdjacentHTML('afterbegin', '<div class="timing-summary">Analyzing audio telemetry… decoding once and writing reusable artifacts.</div>');
  try {
    const result = await window.hapa.analyzeAudioTelemetry(song.id);
    state.audioTelemetryRuns.delete(song.id);
    await loadAudioTelemetryForCurrent(song);
    state.registry = await window.hapa.loadRegistry();
    const refreshed = (state.registry.songs || []).find((s) => s.id === song.id);
    if (refreshed) state.current = refreshed;
    renderStats(); renderTimeline(state.current); renderTelemetry(state.current);
    toast(`Audio telemetry analyzed for ${displayTitle(state.current)}.`);
    console.log('audio telemetry result', result);
  } catch (err) {
    toast(`Audio telemetry failed: ${err.message}`);
  }
}

async function loadMainAudio(song) {
  const audio = $('mainAudio');
  audio.pause();
  audio.muted = $('muteMain').checked;
  const url = hasMusic(song) ? await window.hapa.fileUrl(song.localPath) : null;
  audio.removeAttribute('src');
  if (!url) {
    audio.load();
    drawIdle();
    return;
  }
  audio.src = url;
  audio.load();
  setupAnalyser();
}

function setupAnalyser() {
  const audio = $('mainAudio');
  if (!state.audioCtx) state.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  if (!state.analyser) {
    state.analyser = state.audioCtx.createAnalyser();
    state.analyser.fftSize = 2048;
  }
  if (!state.source) {
    state.source = state.audioCtx.createMediaElementSource(audio);
    state.source.connect(state.analyser);
    state.analyser.connect(state.audioCtx.destination);
  }
}

async function loadStemDeck(song) {
  for (const item of state.stems.values()) { item.audio.pause(); item.audio.remove(); }
  state.stems.clear();
  state.stemAnalysers.clear();
  state.stemMuteState.clear();
  state.stemSoloState.clear();
  const stems = stemsForVariation(song.id);
  for (const stem of stems) {
    state.stemMuteState.set(stem.id, false);
    await ensureStemAudio(stem);
  }
}

async function ensureStemAudio(stemOrId) {
  const stem = typeof stemOrId === 'string' ? (state.registry.stems || []).find((x) => x.id === stemOrId) : stemOrId;
  if (!stemPlayable(stem)) return null;
  const existing = state.stems.get(stem.id);
  const native = document.querySelector(`[data-stem-native="${stem.id}"]`);
  if (existing?.audio) {
    if (native && existing.audio !== native) {
      existing.audio = native;
      wireStemAudioElement(stem, native);
    }
    return existing;
  }
  const audio = native || new Audio(await window.hapa.fileUrl(stem.localPath));
  audio.crossOrigin = 'anonymous';
  audio.preload = 'metadata';
  audio.volume = Number(audio.dataset?.stemVolume || 0.9);
  wireStemAudioElement(stem, audio);
  const item = { stem, audio, enabled: true };
  state.stems.set(stem.id, item);
  return item;
}

function wireStemAudioElement(stem, audio) {
  if (audio.dataset.stemWired) return;
  audio.dataset.stemWired = '1';
  audio.addEventListener('play', () => {
    recordPlay('stem', stem.id);
    applyStemMixState();
  });
  audio.addEventListener('error', () => {
    toast(`Stem failed to load: ${displayTitle(stem, 'stem')}`);
    appendEvent({ type: 'stem.playback.failed', targetType: 'stem', targetId: stem.id, reason: audio.error?.message || 'media-error' }).catch(console.error);
  });
}

function pauseAllStemsExcept(activeId) {
  for (const [stemId, item] of state.stems.entries()) {
    if (stemId !== activeId) {
      item.enabled = false;
      item.audio.pause();
      const cb = document.querySelector(`[data-stem-toggle="${stemId}"]`);
      if (cb) cb.checked = false;
    }
  }
}

async function hydrateNativeStemPlayers(root = document) {
  for (const audio of root.querySelectorAll('[data-stem-native]')) {
    const stem = (state.registry.stems || []).find((x) => x.id === audio.dataset.stemNative);
    if (!stemPlayable(stem)) continue;
    audio.src = await window.hapa.fileUrl(stem.localPath);
    await ensureStemAudio(stem);
  }
}

function renderNow() {
  const s = state.current;
  $('nowTitle').textContent = displayTitle(s);
  const master = masterInfoFor(s.id);
  const variationStemCount = stemsForVariation(s.id).length;
  const masterStemCount = allStemsForMaster(s.id).length;
  const promptGroupCount = promptGroupsForMaster(s.id).length;
  $('nowMeta').textContent = `${s.model || 'unknown'} • ${contentTypeFor(s)}${isMashup(s) ? ' mashup' : ''} • ${s.majorModelVersion || ''} • ${fmt(s.duration)} • ${variationStemCount} stems on this variation / ${masterStemCount} on master • ${master.variations.length} variation(s) • ${promptGroupCount} prompt group(s) • ${new Date(s.createdAt || Date.now()).toLocaleString()}`;
  $('cover').src = s.imageUrl || '';
  renderEngagementBar('song', s.id);
}

function renderEngagementBar(targetType, targetId) {
  const item = targetType === 'song' ? state.songs.find((s) => s.id === targetId) : targetType === 'stem' ? (state.registry.stems || []).find((s) => s.id === targetId) : state.loops.find((l) => l.id === targetId);
  const e = engagementFor(item || { id: targetId }, targetType);
  $('engagementBar').innerHTML = `<button data-like="${targetType}:${targetId}">♥ ${e.likes}</button><button data-playmark="${targetType}:${targetId}">▶ ${e.plays}</button><label>Rating <select data-rate="${targetType}:${targetId}">${[0, 1, 2, 3, 4, 5].map((n) => `<option value="${n}" ${e.rating === n ? 'selected' : ''}>${n || '—'}</option>`).join('')}</select></label>`;
  wireEngagementControls($('engagementBar'));
}

function wireEngagementControls(root = document) {
  root.querySelectorAll('[data-like]').forEach((btn) => btn.addEventListener('click', () => {
    const [targetType, targetId] = btn.dataset.like.split(':');
    appendEvent({ type: `${targetType}.liked`, targetType, targetId, value: true });
  }));
  root.querySelectorAll('[data-playmark]').forEach((btn) => btn.addEventListener('click', () => {
    const [targetType, targetId] = btn.dataset.playmark.split(':');
    appendEvent({ type: `${targetType}.played`, targetType, targetId, count: 1 });
  }));
  root.querySelectorAll('[data-rate]').forEach((sel) => sel.addEventListener('change', () => {
    const [targetType, targetId] = sel.dataset.rate.split(':');
    appendEvent({ type: `${targetType}.rated`, targetType, targetId, rating: Number(sel.value) });
  }));
}

function switchTab(tab) {
  document.querySelectorAll('.tab').forEach((b) => b.classList.toggle('active', b.dataset.tab === tab));
  document.querySelectorAll('.tab-content').forEach((c) => c.classList.toggle('active', c.id === `tab-${tab}`));
}

function openTimelinePage() {
  if (!state.current) return;
  renderTimelinePage(state.current);
  const page = $('timelinePage');
  page.className = 'timeline-page active';
  page.setAttribute('aria-hidden', 'false');
}

function closeTimelinePage() {
  const page = $('timelinePage');
  page.className = 'timeline-page';
  page.setAttribute('aria-hidden', 'true');
}

function openStemLabPage() {
  if (!state.current) return;
  renderStemLabPage(state.current);
  const page = $('stemLabPage');
  page.className = 'stem-lab-page active';
  page.setAttribute('aria-hidden', 'false');
}

function closeStemLabPage() {
  const page = $('stemLabPage');
  page.className = 'stem-lab-page';
  page.setAttribute('aria-hidden', 'true');
  if (state.dawVisualRaf) cancelAnimationFrame(state.dawVisualRaf);
  state.dawVisualRaf = null;
}

function renderDetails() {
  const s = state.current;
  renderOverview(s); renderLyrics(s); renderStems(s); renderTimeline(s); renderLoops(s); renderMixer(s); renderAncestry(s); renderRelations(s); renderTelemetry(s);
}
function renderOverview(s) {
  const master = masterInfoFor(s.id);
  const currentPromptGroup = promptGroupForSong(s.id);
  const promptGroups = promptGroupsForMaster(s.id);
  $('tab-overview').innerHTML = `<div class="action-row"><button id="renameSong">Rename song/variation</button><button data-like="song:${s.id}">♥ Like</button><button data-playmark="song:${s.id}">Mark play</button></div>
    <div class="kv"><b>Title</b><span>${esc(displayTitle(s))}</span></div>
    <div class="kv"><b>Lyric master</b><span>${esc(displayTitle(state.songs.find((x) => x.id === master.masterId) || s))} • ${master.variations.length} variation(s) • ${promptGroups.length} prompt group(s)</span></div>
    <div class="kv"><b>Prompt group</b><span>${esc(promptGroupLabel(currentPromptGroup))}</span></div>
    <div class="kv"><b>Content type</b><span>${esc(contentTypeFor(s))}${isMashup(s) ? ' • mashup' : ''}${(s.mashupSourceIds || []).length ? ` • sources: ${esc((s.mashupSourceIds || []).join(', '))}` : ''}</span></div>
    <div class="kv"><b>Model</b><span>${esc(s.model)} / ${esc(s.majorModelVersion)}</span></div>
    <div class="kv"><b>Duration</b><span>${fmt(s.duration)}</span></div>
    <div class="kv"><b>Created</b><span>${esc(s.createdAt || '')}</span></div>
    <div class="kv"><b>Stems</b><span>${stemsForVariation(s.id).length} on this variation / ${allStemsForMaster(s.id).length} on lyric master (${uniq(allStemsForMaster(s.id).map((st) => st.stemType)).join(', ')})</span></div>
    <h2>Prompt groups for this lyric master</h2><div class="variation-list">${promptGroups.map((g) => `<button class="mini-card ${g.id === currentPromptGroup?.id ? 'active' : ''}" data-prompt-group="${g.id}">${esc(promptGroupLabel(g))}<small>${esc((g.facets?.mood || []).concat(g.facets?.themes || []).slice(0, 4).join(', '))}${g.mashupCount ? ` • ${g.mashupCount} mashup(s)` : ''}</small></button>`).join('') || '<div class="empty">No prompt groups indexed.</div>'}</div>
    <h2>Variations</h2><div class="variation-list">${master.variations.map((id) => { const v = state.songs.find((x) => x.id === id); const count = stemsForVariation(id).length; return `<button class="mini-card ${id === s.id ? 'active' : ''}" data-variation="${id}">${esc(displayTitle(v || { id }))}<small>${fmt(v?.duration)} • ${count} stems • ${esc(contentTypeFor(v || {}))}</small></button>`; }).join('')}</div>
    <h2>Facets</h2><div class="facet-cloud">${Object.entries(s.facets || {}).flatMap(([k, vals]) => (vals || []).map((v) => `<span class="facet">${esc(k)}: ${esc(v)}</span>`)).join('')}</div>
    <h2>Style / Tags</h2><pre>${esc(s.tags || '')}</pre>
    <h2>Style prompt / generation prompt group</h2><pre>${esc(s.stylePrompt || '')}</pre>
    <h2>Prompt / Lyrics</h2><pre>${esc(s.prompt || '')}</pre>`;
  $('renameSong').addEventListener('click', () => renameTarget('song', s.id, displayTitle(s)));
  $('tab-overview').querySelectorAll('[data-prompt-group]').forEach((btn) => btn.addEventListener('click', () => { $('promptGroupFilter').value = btn.dataset.promptGroup; applyFilters(); }));
  $('tab-overview').querySelectorAll('[data-variation]').forEach((btn) => btn.addEventListener('click', () => selectSong(btn.dataset.variation, false)));
  wireEngagementControls($('tab-overview'));
}
function renderLyrics(s) {
  const timed = s.lyricTiming?.lines || [];
  const sections = s.lyricTiming?.sections || [];
  if (timed.length) {
    const bySection = new Map(sections.map((sec) => [sec.index, sec]));
    let currentSection = null;
    const rows = [];
    timed.forEach((line) => {
      if (line.sectionIndex !== currentSection) {
        currentSection = line.sectionIndex;
        const sec = bySection.get(currentSection);
        rows.push(`<div class="lyric-section"><span>${esc(sec?.timestamp || line.timestamp)}</span>${esc(sec?.label || line.section || 'Lyrics')}</div>`);
      }
      rows.push(`<button class="lyric-line" data-line="${line.index}" data-start="${line.start}"><span class="lyric-time">${esc(line.timestamp || fmt(line.start))}</span><span class="lyric-text">${esc(line.text)}</span><span class="lyric-confidence">${Math.round((line.confidence || 0) * 100)}%</span></button>`);
    });
    $('tab-lyrics').innerHTML = `<div class="timing-summary">Timing: ${esc(s.lyricTiming.method)} • source: ${esc(s.lyricTiming.source)} • confidence: ${Math.round((s.lyricTiming.confidence || 0) * 100)}% • ${timed.length} timestamped lines</div><div class="lyrics">${rows.join('\n')}</div>`;
    document.querySelectorAll('.lyric-line[data-start]').forEach((btn) => btn.addEventListener('click', () => {
      $('mainAudio').currentTime = Number(btn.dataset.start || 0);
      syncStemsToMain();
    }));
    return;
  }
  const lines = (s.lyrics || '').split('\n').filter(Boolean);
  $('tab-lyrics').innerHTML = lines.length ? `<div class="timing-summary low">No analyzed timings yet; using approximate playback distribution.</div><div class="lyrics">${lines.map((l, i) => `<span class="lyric-line" data-line="${i}"><span class="lyric-time">${fmt((i / Math.max(1, lines.length)) * (s.duration || 0))}</span><span class="lyric-text">${esc(l)}</span></span>`).join('\n')}</div>` : '<div class="empty">No lyrics found in telemetry.</div>';
}
function renderStems(s) {
  const master = masterInfoFor(s.id);
  const variationRows = master.variations.map((id) => {
    const variation = songForId(id) || { id, title: id, duration: s.duration };
    const count = stemsForVariation(id).length;
    return `<button class="mini-card ${id === s.id ? 'active' : ''}" data-variation-stems="${id}">${esc(displayTitle(variation))}<small>${count} variation-specific stems</small></button>`;
  }).join('');
  const stems = stemsForVariation(s.id);
  $('tab-stems').innerHTML = `<div class="action-row"><button data-open-stem-lab="1">Open professional DAW workstation</button></div><p class="muted">Stems are specific to the selected song variation. The workstation now exposes the shared-clock Web Audio DAW engine: decoded buffers, track buses, synchronized transport, mute/solo, loop regions, waveforms, spectrograms, and FFT.</p><div class="variation-list stem-variation-list">${variationRows}</div>` + (stems.length ? `<div class="stem-grid">${stems.map((st) => {
    const e = engagementFor(st, 'stem');
    return `<div class="stem first-class-stem" data-stem-card="${st.id}">
      <div class="stem-head"><label><input type="checkbox" data-stem-toggle="${st.id}" /> ${esc(st.stemType || 'Stem')}</label><button data-stem-play="${st.id}">solo</button></div>
      <h3>${esc(displayTitle(st, 'stem'))}</h3>
      <canvas class="stem-wave" data-stem-wave="${st.id}"></canvas>
      <p>${fmt(st.duration)} • ${esc(st.model || '')} • ▶ ${e.plays} • ♥ ${e.likes} ${e.rating ? `• ★ ${e.rating}` : ''}</p>
      <audio class="detachedStemPlayer" data-stem-native="${st.id}" controls preload="metadata"></audio>
      <input type="range" min="0" max="1" step="0.01" value="0.9" data-stem-volume="${st.id}" />
      <div class="action-row"><button data-stem-rename="${st.id}">Rename</button><button data-like="stem:${st.id}">♥</button><button data-playmark="stem:${st.id}">Play</button><select data-rate="stem:${st.id}">${[0, 1, 2, 3, 4, 5].map((n) => `<option value="${n}" ${e.rating === n ? 'selected' : ''}>${n || 'rate'}</option>`).join('')}</select><button data-clip-source="stem:${st.id}">Clip loop</button><button data-mix-add="stem:${st.id}">Add to mixer</button></div>
      <details><summary>Telemetry</summary><pre>${esc(JSON.stringify({ id: st.id, parentId: st.parentId, stemType: st.stemType, createdAt: st.createdAt, duration: st.duration, settings: st.settings, localPath: st.localPath, raw: { play_count: rawMetric(st, 'play_count'), upvote_count: rawMetric(st, 'upvote_count'), is_liked: st.raw?.is_liked } }, null, 2))}</pre></details>
    </div>`;
  }).join('')}</div>` : '<div class="empty">No purchased/generated stems linked to this variation. Choose another variation above to see its stems.</div>');
  document.querySelectorAll('[data-variation-stems]').forEach((btn) => btn.addEventListener('click', () => selectSong(btn.dataset.variationStems, false)));
  const stemLabBtn = $('tab-stems').querySelector('[data-open-stem-lab]');
  if (stemLabBtn) stemLabBtn.addEventListener('click', openStemLabPage);
  document.querySelectorAll('[data-stem-toggle]').forEach((cb) => cb.addEventListener('change', onStemToggle));
  document.querySelectorAll('[data-stem-volume]').forEach((sl) => sl.addEventListener('input', () => { const item = state.stems.get(sl.dataset.stemVolume); if (item) item.audio.volume = Number(sl.value); }));
  document.querySelectorAll('[data-stem-play]').forEach((btn) => btn.addEventListener('click', () => soloStem(btn.dataset.stemPlay)));
  document.querySelectorAll('[data-stem-rename]').forEach((btn) => btn.addEventListener('click', () => { const st = (state.registry.stems || []).find((x) => x.id === btn.dataset.stemRename); renameTarget('stem', st.id, displayTitle(st, 'stem')); }));
  document.querySelectorAll('[data-clip-source]').forEach((btn) => btn.addEventListener('click', () => fillLoopClip(btn.dataset.clipSource)));
  document.querySelectorAll('[data-mix-add]').forEach((btn) => btn.addEventListener('click', () => addMixerSource(btn.dataset.mixAdd)));
  wireEngagementControls($('tab-stems'));
  hydrateNativeStemPlayers($('tab-stems')).catch((err) => toast(`Stem player setup failed: ${err.message}`));
  drawStemWaves();
}

function timelineActivity(stem, index, total) {
  const analysis = state.stemAnalysis.get(stem.id);
  if (analysis && !analysis.then && analysis.real && analysis.waveform?.length) {
    const start = Math.floor((index / Math.max(1, total)) * analysis.waveform.length);
    const end = Math.max(start + 1, Math.floor(((index + 1) / Math.max(1, total)) * analysis.waveform.length));
    const segment = analysis.waveform.slice(start, end);
    const energy = segment.reduce((sum, p) => sum + Math.max(Math.abs(p.min), Math.abs(p.max)), 0) / Math.max(1, segment.length);
    return clamp(energy * 100, 5, 100);
  }
  const engagement = Math.min(1, engagementScore(stem, 'stem') / 250);
  return clamp((0.35 + engagement * 0.15) * 100, 5, 55);
}

function timelineMarkup(s, fullPage = false) {
  const stems = stemsForVariation(s.id);
  const duration = Math.max(1, Number(s.duration || $('mainAudio').duration || 0));
  const telemetry = audioTelemetryFor(s);
  const telemetrySummary = telemetry?.summary || telemetry?.summary || {};
  const telemetryEvents = telemetry?.timeline?.events || [];
  const telemetryBpm = Number(telemetrySummary.bpm || telemetry?.rhythm?.bpm || 0);
  const bpm = Number(telemetryBpm || s.settings?.bpm || s.raw?.bpm || 120);
  const countSeconds = 60 / Math.max(1, bpm);
  const fourCountSeconds = countSeconds * 4;
  const eightCountSeconds = countSeconds * 8;
  const bars = Math.max(1, Math.ceil(duration / eightCountSeconds));
  const barCells = Array.from({ length: bars }, (_x, i) => {
    const start = i * eightCountSeconds;
    const mid = Math.min(duration, start + fourCountSeconds);
    const end = Math.min(duration, start + eightCountSeconds);
    return `<div class="timeline-bar" data-bar="${i}">
      <div class="timeline-bar-head"><b>8-count ${i + 1}</b><span>${fmt(start)}–${fmt(end)}</span></div>
      <div class="timeline-halves"><button data-timeline-clip="song:${s.id}:${start}:${mid}">4-count A</button><button data-timeline-clip="song:${s.id}:${mid}:${end}">4-count B</button></div>
      <button class="wide" data-timeline-clip="song:${s.id}:${start}:${end}">Clip full 8-count</button>
    </div>`;
  }).join('');
  const stemRows = stems.map((st) => {
    const e = engagementFor(st, 'stem');
    const cells = Array.from({ length: bars }, (_x, i) => {
      const start = i * eightCountSeconds;
      const end = Math.min(duration, start + eightCountSeconds);
      const activity = timelineActivity(st, i, bars);
      return `<button class="timeline-activity" style="--activity:${activity}%" title="${esc(st.stemType || 'Stem')} frequency/activity ${Math.round(activity)}%" data-timeline-clip="stem:${st.id}:${start}:${end}"><span>${Math.round(activity)}%</span></button>`;
    }).join('');
    return `<div class="timeline-stem-row"><div class="timeline-stem-label"><b>${esc(st.stemType || 'Stem')}</b><small>▶ ${e.plays} • ♥ ${e.likes} • ${fmt(st.duration)}</small><button data-stem-play="${st.id}">solo</button></div><div class="timeline-stem-cells">${cells}</div></div>`;
  }).join('');
  const telemetryMarkers = telemetryEvents.filter((ev) => ['hook_candidate', 'section', 'peak'].includes(ev.type)).slice(0, 24).map((ev) => {
    const start = Number(ev.start || 0);
    const left = clamp((start / duration) * 100, 0, 100);
    const kind = ev.type === 'hook_candidate' ? 'hot' : ev.type === 'section' ? 'gold' : '';
    return `<button class="badge ${kind}" style="position:relative;left:${left}%;margin-left:-.5rem" title="${esc(ev.type)} ${fmt(ev.start)}–${fmt(ev.end)} confidence ${Math.round((ev.confidence || 0) * 100)}%">${esc(ev.label || ev.type)}</button>`;
  }).join('');
  return `<div class="timeline-view ${fullPage ? 'full' : ''}">
    <div class="timing-summary">Timeline uses ${bpm} BPM${telemetryBpm ? ' from persisted audio telemetry' : ''}: every cell is an 8-count (${fmt(eightCountSeconds)}), split into two 4-count clip zones. Stem lanes show activity/frequency/telemetry for the selected variation only.</div>
    ${telemetryMarkers ? `<h2>Audio telemetry markers</h2><div class="telemetry-marker-strip">${telemetryMarkers}</div>` : '<div class="timing-summary low">No persisted audio telemetry markers yet. Use the Telemetry tab to analyze this song.</div>'}
    <div class="timeline-grid">${barCells}</div>
    <h2>Stem activity / frequency lanes</h2>
    ${stemRows || '<div class="empty">No stems on this variation. Pick another variation in Overview/Stems.</div>'}
  </div>`;
}

function wireTimeline(root) {
  root.querySelectorAll('[data-timeline-clip]').forEach((btn) => btn.addEventListener('click', () => fillTimelineClip(btn.dataset.timelineClip)));
  root.querySelectorAll('[data-stem-play]').forEach((btn) => btn.addEventListener('click', () => soloStem(btn.dataset.stemPlay)));
}

function renderTimeline(s) {
  $('tab-timeline').innerHTML = `<div class="action-row"><button data-open-timeline-page="1">Open full timeline page</button></div>${timelineMarkup(s, false)}`;
  $('tab-timeline').querySelector('[data-open-timeline-page]').addEventListener('click', openTimelinePage);
  wireTimeline($('tab-timeline'));
}

function renderTimelinePage(s) {
  $('timelinePageBody').innerHTML = timelineMarkup(s, true);
  wireTimeline($('timelinePageBody'));
}

function stemLabMasterTimeline(s, stems) {
  const duration = Math.max(1, Number(s.duration || $('mainAudio').duration || 0));
  const pointer = state.loopPointer ?? $('mainAudio').currentTime ?? 0;
  const endLoopMarker = state.endLoopMarker;
  const pointerPct = clamp((pointer / duration) * 100, 0, 100);
  const endPct = endLoopMarker == null ? null : clamp((endLoopMarker / duration) * 100, 0, 100);
  const loopOverlays = loopsForSong(s.id).map((loop) => {
    const left = clamp((Number(loop.start || 0) / duration) * 100, 0, 100);
    const width = clamp((Number(loop.duration || (loop.end - loop.start) || 0) / duration) * 100, 0.4, 100 - left);
    return `<button class="loop-region" style="left:${left}%;width:${width}%" title="${esc(loop.title || loop.id)} ${fmt(loop.start)}–${fmt(loop.end)}" data-loop-play="${loop.id}">${esc(loop.title || 'loop')}</button>`;
  }).join('');
  const stemLanes = stems.map((st, idx) => {
    const blocks = Array.from({ length: 18 }, (_x, i) => `<span style="height:${Math.round(timelineActivity(st, i + idx, 18))}%"></span>`).join('');
    return `<div class="stem-master-lane"><b>${esc(st.stemType || 'Stem')}</b><div class="stem-lane-wave">${blocks}</div></div>`;
  }).join('');
  return `<section class="masterTimeline" id="masterTimeline">
    <div class="stem-lab-section-head"><h2>Main timeline</h2><span>${fmt(duration)} total • ${stems.length} stems • ${loopsForSong(s.id).length} captured loops</span></div>
    <div class="stemLabMasterTimeline" data-main-timeline="1">
      <div class="loopCaptureFlash" id="loopCaptureFlash">Loop captured → dock</div>
      <div class="loop-overlays">${loopOverlays}</div>
      <button class="timeline-drop-zone" data-drop-loop-pointer="1" title="Click to drop pointer on main timeline"></button>
      <div class="loop-pointer" style="left:${pointerPct}%"><span>START ${fmt(pointer)}</span></div>
      ${endPct == null ? '' : `<div class="endLoopMarker" style="left:${endPct}%"><span>END ${fmt(endLoopMarker)}</span></div>`}
    </div>
    <div class="stem-master-lanes">${stemLanes}</div>
    <div class="loop-marker-controls">
      <button data-play-stem-session="1">Play synced stems</button>
      <button data-loop-counts="4">Capture +4-count loop</button>
      <button data-loop-counts="8">Capture +8-count loop</button>
      <button data-end-loop-marker="1">Drop END LOOP marker</button>
      <button data-loop-from-markers="1">Capture START → END</button>
    </div>
  </section>`;
}

function renderDawUtilityPanel(s, stems) {
  const engine = state.dawEngine;
  const trackCount = engine?.tracks?.size || (hasMusic(s) ? 1 : 0) + stems.length;
  const sampleRate = engine?.sampleRate ? `${Math.round(engine.sampleRate).toLocaleString()} Hz` : 'pending decode';
  const latency = engine?.ctx?.baseLatency ? `${(engine.ctx.baseLatency * 1000).toFixed(1)} ms` : 'interactive';
  const loop = engine?.loopRegion;
  return `<section class="dawUtilityPanel daw-utility-panel">
    <div class="daw-utility-head">
      <div><span class="daw-signal-pill">DAW Engine Online</span><h2>Professional stem utility</h2><p>Shared AudioContext clock • Decoded AudioBuffer tracks • Sample-accurate loop region</p></div>
      <div id="dawStatusReadout" class="daw-status-readout">${engine?.isPlaying ? 'playing' : 'ready'} @ ${fmt(engine?.currentTime?.() || 0)}</div>
    </div>
    <div class="daw-metric-grid">
      <div><b>${trackCount}</b><span>decoded tracks</span></div>
      <div><b>${sampleRate}</b><span>sample rate</span></div>
      <div><b>${latency}</b><span>base latency</span></div>
      <div><b>${loop ? `${fmt(loop.start)}–${fmt(loop.end)}` : 'none'}</b><span>loop region</span></div>
    </div>
    <div class="daw-transport-strip">
      <button data-daw-play="1">Play shared-clock stems</button>
      <button data-daw-pause="1">Pause DAW</button>
      <button data-daw-clear-loop="1">Clear DAW loop</button>
      <small>Native stem players below are previews; this strip controls the Web Audio buffer engine.</small>
    </div>
  </section>`;
}

function wireDawUtilityControls(root = document) {
  const play = root.querySelector('[data-daw-play]');
  if (play) play.addEventListener('click', () => playStemSession(state.dawEngine?.currentTime?.() || $('mainAudio').currentTime || state.loopPointer || 0));
  const pause = root.querySelector('[data-daw-pause]');
  if (pause) pause.addEventListener('click', () => { if (state.dawEngine) state.dawEngine.pause(); if (state.dawVisualRaf) cancelAnimationFrame(state.dawVisualRaf); state.dawVisualRaf = null; state.stemSessionPlaying = false; updateDawStatusReadout(); });
  const clear = root.querySelector('[data-daw-clear-loop]');
  if (clear) clear.addEventListener('click', () => { if (state.dawEngine) state.dawEngine.clearLoopRegion(); renderStemLabPage(state.current); toast('DAW loop region cleared.'); });
  updateDawStatusReadout();
}

function updateDawStatusReadout() {
  const el = $('dawStatusReadout');
  if (!el || !state.dawEngine) return;
  const loop = state.dawEngine.loopRegion;
  el.textContent = `${state.dawEngine.isPlaying ? 'playing' : 'ready'} @ ${fmt(state.dawEngine.currentTime())} • ${state.dawEngine.tracks.size} tracks${loop ? ` • loop ${fmt(loop.start)}–${fmt(loop.end)}` : ''}`;
  if (state.dawStatusRaf) cancelAnimationFrame(state.dawStatusRaf);
  if (state.dawEngine.isPlaying) state.dawStatusRaf = requestAnimationFrame(updateDawStatusReadout);
}

function renderStemLabPage(s) {
  const stems = stemsForVariation(s.id);
  const rows = stems.map((st, idx) => {
    const e = engagementFor(st, 'stem');
    return `<article class="stem-lab-row" data-stem-lab-row="${st.id}">
      <div class="stem-lab-controls">
        <label class="stem-unmuted"><input type="checkbox" data-stem-mute="${st.id}" checked /> unmuted</label>
        <button data-stem-play="${st.id}">play in sync</button>
        <button data-stem-solo="${st.id}">solo</button>
        <button data-stem-playhead-pointer="${st.id}">drop pointer here</button>
        <button data-clip-source="stem:${st.id}">clip stem</button>
        <button data-mix-add="stem:${st.id}">add stem to mixer</button>
        <small>${esc(st.stemType || 'Stem')} • ${fmt(st.duration)} • ▶ ${e.plays} • ♥ ${e.likes}</small>
      </div>
      <div class="stem-analysis-grid">
        <div><b>Waveform</b><canvas class="stemWaveformCanvas" data-analysis-stem-id="${st.id}" data-stem-analysis="waveform:${st.id}:${idx}"></canvas></div>
        <div><b>Spectrogram</b><canvas class="stemSpectrogramCanvas" data-analysis-stem-id="${st.id}" data-stem-analysis="spectrogram:${st.id}:${idx}"></canvas></div>
        <div><b>Spectral Analysis / FFT</b><canvas class="stemFftCanvas" data-analysis-stem-id="${st.id}" data-stem-analysis="fft:${st.id}:${idx}"></canvas></div>
      </div>
      <audio class="detachedStemPlayer" data-stem-native="${st.id}" controls preload="metadata"></audio>
    </article>`;
  }).join('');
  $('stemLabBody').innerHTML = `${renderDawUtilityPanel(s, stems)}${stemLabMasterTimeline(s, stems)}<section class="stem-lab-stems"><div class="stem-lab-section-head"><h2>All stems</h2><span>Every stem starts unmuted; use per-stem toggles to mute/unmute.</span></div>${rows || '<div class="empty">No stems on this variation.</div>'}</section>`;
  wireDawUtilityControls($('stemLabBody'));
  wireStemLab($('stemLabBody'));
  hydrateNativeStemPlayers($('stemLabBody')).then(() => unmuteStemLabByDefault($('stemLabBody'))).catch((err) => toast(`Stem workstation setup failed: ${err.message}`));
  drawStemAnalysisVisuals($('stemLabBody'));
  drawLiveDawVisuals();
}

function unmuteStemLabByDefault(root) {
  root.querySelectorAll('[data-stem-mute]').forEach((cb) => {
    cb.checked = true;
    const item = state.stems.get(cb.dataset.stemMute);
    if (item) item.audio.muted = false;
  });
}

function wireStemLab(root) {
  const timeline = root.querySelector('[data-drop-loop-pointer]');
  if (timeline) timeline.addEventListener('click', dropLoopPointer);
  root.querySelectorAll('[data-loop-counts]').forEach((btn) => btn.addEventListener('click', () => capturePointerLoopCounts(Number(btn.dataset.loopCounts))));
  root.querySelectorAll('[data-end-loop-marker]').forEach((btn) => btn.addEventListener('click', dropEndLoopMarker));
  root.querySelectorAll('[data-loop-from-markers]').forEach((btn) => btn.addEventListener('click', () => capturePointerLoop(null)));
  root.querySelectorAll('[data-stem-mute]').forEach((cb) => cb.addEventListener('change', () => setStemMuted(cb.dataset.stemMute, !cb.checked)));
  const playSession = root.querySelector('[data-play-stem-session]');
  if (playSession) playSession.addEventListener('click', () => playStemSession($('mainAudio').currentTime || state.loopPointer || 0));
  root.querySelectorAll('[data-stem-play]').forEach((btn) => btn.addEventListener('click', () => playStemAudio(btn.dataset.stemPlay, false)));
  root.querySelectorAll('[data-stem-solo]').forEach((btn) => btn.addEventListener('click', () => soloStem(btn.dataset.stemSolo)));
  root.querySelectorAll('[data-stem-playhead-pointer]').forEach((btn) => btn.addEventListener('click', () => { const item = state.stems.get(btn.dataset.stemPlayheadPointer); state.loopPointer = item?.audio?.currentTime || 0; renderStemLabPage(state.current); }));
  root.querySelectorAll('[data-clip-source]').forEach((btn) => btn.addEventListener('click', () => fillLoopClip(btn.dataset.clipSource)));
  root.querySelectorAll('[data-mix-add]').forEach((btn) => btn.addEventListener('click', () => addMixerSource(btn.dataset.mixAdd)));
  root.querySelectorAll('[data-loop-play]').forEach((btn) => btn.addEventListener('click', () => playLoop(btn.dataset.loopPlay)));
}

function setStemMuted(id, muted) {
  state.stemMuteState.set(id, muted);
  ensureStemAudio(id).then(() => applyStemMixState());
}

function dropLoopPointer(event) {
  const rect = event.currentTarget.getBoundingClientRect();
  const duration = Math.max(1, Number(state.current?.duration || $('mainAudio').duration || 0));
  state.loopPointer = clamp(((event.clientX - rect.left) / rect.width) * duration, 0, duration);
  renderStemLabPage(state.current);
}

function dropEndLoopMarker() {
  const duration = Math.max(1, Number(state.current?.duration || $('mainAudio').duration || 0));
  state.endLoopMarker = clamp($('mainAudio').currentTime || (state.loopPointer || 0) + 8, 0, duration);
  renderStemLabPage(state.current);
}

async function capturePointerLoopCounts(counts) {
  return capturePointerLoop(countsToSeconds(counts), `${counts}-count`);
}

async function capturePointerLoop(seconds, label = 'marker') {
  if (!state.current) return;
  const duration = Math.max(1, Number(state.current.duration || $('mainAudio').duration || 0));
  const start = clamp(state.loopPointer ?? $('mainAudio').currentTime ?? 0, 0, duration);
  const rawEnd = seconds == null && state.endLoopMarker != null ? state.endLoopMarker : start + Number(seconds || countsToSeconds(8));
  if (rawEnd <= start) { toast('END marker must be after START.'); return; }
  const end = clamp(rawEnd, start + 0.1, duration);
  const loopId = idFor('loop');
  const src = sourceFromKey(`song:${state.current.id}`);
  const payload = { type: 'loop.created', targetType: 'loop', targetId: loopId, loopId, title: `${displayTitle(state.current)} ${fmt(start)} ${label} loop`, origin: { type: 'song', id: state.current.id, songId: state.current.id, title: displayTitle(state.current) }, start, end, duration: end - start, renderStatus: 'metadata-only' };
  try {
    const saved = await window.hapa.createClip({ ...payload, inputPath: src.path });
    state.events.push(saved); applyEvent(saved, true); toast('Rendered loop audio and saved to dock.');
  } catch (err) {
    toast(`Loop render failed: ${err.message}. Saved metadata-only loop.`);
    await appendEvent(payload);
  }
  renderLoopDock();
  renderStemLabPage(state.current);
  const flash = $('loopCaptureFlash');
  if (flash) { flash.classList.add('active'); setTimeout(() => flash.classList.remove('active'), 900); }
}

function renderAnalysisCanvas(canvas, kind, analysis) {
  const ctx = canvas.getContext('2d');
  const w = canvas.width = Math.max(220, canvas.clientWidth * devicePixelRatio);
  const h = canvas.height = Math.max(86, canvas.clientHeight * devicePixelRatio);
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = '#081021'; ctx.fillRect(0, 0, w, h);
  if (!analysis?.real) {
    ctx.fillStyle = '#9aa4bd';
    ctx.fillText(analysis?.error ? `analysis failed: ${analysis.error}` : 'analyzing audio…', 12, 24);
    return;
  }
  if (kind === 'waveform') {
    ctx.strokeStyle = '#45f5ff'; ctx.beginPath();
    const peaks = analysis.waveform || [];
    peaks.forEach((p, i) => {
      const x = (i / Math.max(1, peaks.length - 1)) * w;
      ctx.moveTo(x, h / 2 + p.min * h * .46);
      ctx.lineTo(x, h / 2 + p.max * h * .46);
    });
    ctx.stroke();
  } else if (kind === 'spectrogram') {
    const frames = analysis.spectrogram || [];
    const cellW = w / Math.max(1, frames.length);
    const cellH = h / Math.max(1, frames[0]?.length || 1);
    frames.forEach((frame, x) => frame.forEach((v, y) => {
      ctx.fillStyle = `hsla(${215 + v * 135},95%,${16 + v * 55}%,.92)`;
      ctx.fillRect(x * cellW, h - (y + 1) * cellH, Math.max(1, cellW), Math.max(1, cellH));
    }));
  } else {
    const bins = analysis.fft || [];
    const barW = w / Math.max(1, bins.length);
    bins.forEach((v, i) => {
      ctx.fillStyle = `hsla(${42 + v * 100},100%,60%,.94)`;
      ctx.fillRect(i * barW, h - v * h, Math.max(2, barW - 1), v * h);
    });
  }
}

function drawStemAnalysisVisuals(root = document) {
  root.querySelectorAll('[data-stem-analysis]').forEach((canvas) => {
    const [kind, id] = canvas.dataset.stemAnalysis.split(':');
    const stem = (state.registry.stems || []).find((x) => x.id === id);
    renderAnalysisCanvas(canvas, kind, null);
    if (stem) analyzeStemAudio(stem).then((analysis) => renderAnalysisCanvas(canvas, kind, analysis));
  });
}

function ensureCanvasSize(canvas) {
  const w = Math.max(220, canvas.clientWidth * devicePixelRatio);
  const h = Math.max(86, canvas.clientHeight * devicePixelRatio);
  if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
  return { w, h };
}

function drawPlayheadOverlay(canvas, track) {
  const engine = state.dawEngine;
  if (!engine || !track?.buffer) return;
  const ctx = canvas.getContext('2d');
  const w = canvas.width, h = canvas.height;
  const duration = Math.max(0.001, track.buffer.duration || state.current?.duration || 1);
  const t = engine.loopRegion ? ((engine.currentTime() - engine.loopRegion.start) % Math.max(0.001, engine.loopRegion.duration)) + engine.loopRegion.start : engine.currentTime();
  const x = clamp((t / duration) * w, 0, w);
  ctx.save();
  ctx.strokeStyle = '#fffb8f';
  ctx.lineWidth = 2 * devicePixelRatio;
  ctx.beginPath();
  ctx.moveTo(x, 0);
  ctx.lineTo(x, h);
  ctx.stroke();
  ctx.fillStyle = 'rgba(255,251,143,.92)';
  ctx.font = `${10 * devicePixelRatio}px sans-serif`;
  ctx.fillText(fmt(t), Math.min(w - 48 * devicePixelRatio, x + 5 * devicePixelRatio), 14 * devicePixelRatio);
  ctx.restore();
}

function drawLiveWaveform(canvas, analyser, track) {
  const ctx = canvas.getContext('2d');
  const { w, h } = ensureCanvasSize(canvas);
  const data = new Uint8Array(analyser.fftSize);
  analyser.getByteTimeDomainData(data);
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = '#081021'; ctx.fillRect(0, 0, w, h);
  ctx.strokeStyle = '#45f5ff';
  ctx.lineWidth = 1.6 * devicePixelRatio;
  ctx.beginPath();
  data.forEach((v, i) => {
    const x = (i / Math.max(1, data.length - 1)) * w;
    const y = (v / 255) * h;
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.stroke();
  drawPlayheadOverlay(canvas, track);
}

function liveFrequencyBins(analyser, binCount = 72) {
  const freq = new Uint8Array(analyser.frequencyBinCount);
  analyser.getByteFrequencyData(freq);
  return Array.from({ length: binCount }, (_x, bin) => {
    const start = Math.floor((bin / binCount) * freq.length);
    const end = Math.max(start + 1, Math.floor(((bin + 1) / binCount) * freq.length));
    let sum = 0;
    for (let i = start; i < end; i++) sum += freq[i] || 0;
    return sum / ((end - start) * 255);
  });
}

function drawLiveSpectrogram(canvas, analyser, track, stemId) {
  const ctx = canvas.getContext('2d');
  const { w, h } = ensureCanvasSize(canvas);
  const frame = liveFrequencyBins(analyser, 72);
  const history = state.dawSpectrogramHistory.get(stemId) || [];
  history.push(frame);
  while (history.length > 120) history.shift();
  state.dawSpectrogramHistory.set(stemId, history);
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = '#081021'; ctx.fillRect(0, 0, w, h);
  const cellW = w / Math.max(1, history.length);
  const cellH = h / Math.max(1, frame.length);
  history.forEach((bins, x) => bins.forEach((v, y) => {
    ctx.fillStyle = `hsla(${215 + v * 135},95%,${16 + v * 55}%,.92)`;
    ctx.fillRect(x * cellW, h - (y + 1) * cellH, Math.max(1, cellW), Math.max(1, cellH));
  }));
  drawPlayheadOverlay(canvas, track);
}

function drawLiveFft(canvas, analyser, track) {
  const ctx = canvas.getContext('2d');
  const { w, h } = ensureCanvasSize(canvas);
  const bins = liveFrequencyBins(analyser, 72);
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = '#081021'; ctx.fillRect(0, 0, w, h);
  const barW = w / Math.max(1, bins.length);
  bins.forEach((v, i) => {
    ctx.fillStyle = `hsla(${42 + v * 100},100%,60%,.94)`;
    ctx.fillRect(i * barW, h - v * h, Math.max(2, barW - 1), v * h);
  });
  drawPlayheadOverlay(canvas, track);
}

function drawLiveDawVisuals() {
  const active = $('stemLabPage')?.classList.contains('active');
  const engine = state.dawEngine;
  const canvases = active ? [...document.querySelectorAll('[data-stem-analysis][data-analysis-stem-id]')] : [];
  for (const canvas of canvases) {
    const [kind, id] = canvas.dataset.stemAnalysis.split(':');
    const track = engine?.tracks?.get(id);
    if (!track?.analyser) continue;
    if (kind === 'waveform') drawLiveWaveform(canvas, track.analyser, track);
    else if (kind === 'spectrogram') drawLiveSpectrogram(canvas, track.analyser, track, id);
    else drawLiveFft(canvas, track.analyser, track);
  }
  if (active && engine?.isPlaying) state.dawVisualRaf = requestAnimationFrame(drawLiveDawVisuals);
  else state.dawVisualRaf = null;
}

function fillTimelineClip(encoded) {
  const [type, id, start, end] = encoded.split(':');
  fillLoopClip(`${type}:${id}`);
  setTimeout(() => {
    if ($('loopStart')) $('loopStart').value = Number(start || 0).toFixed(2);
    if ($('loopEnd')) $('loopEnd').value = Number(end || 0).toFixed(2);
    if ($('loopTitle')) $('loopTitle').value = `${type} ${fmt(start)} ${type === 'stem' ? 'stem' : 'main'} 8-count`;
  }, 0);
}

function renderLoops(s) {
  const currentLoops = loopsForSong(s.id);
  const sources = [{ type: 'song', id: s.id, title: `Main: ${displayTitle(s)}` }, ...stemsForVariation(s.id).map((st) => ({ type: 'stem', id: st.id, title: `${st.stemType}: ${displayTitle(st, 'stem')}` }))];
  $('tab-loops').innerHTML = `<div class="loop-clipper">
    <h2>Clip a loop</h2>
    <label>Source<select id="loopSource">${sources.map((src) => `<option value="${src.type}:${src.id}">${esc(src.title)}</option>`).join('')}</select></label>
    <div class="three"><label>Start<input id="loopStart" type="number" min="0" step="0.1" value="${Math.max(0, $('mainAudio').currentTime || 0).toFixed(1)}" /></label><label>End<input id="loopEnd" type="number" min="0" step="0.1" value="${Math.min(s.duration || 8, ($('mainAudio').currentTime || 0) + 8).toFixed(1)}" /></label><label>Name<input id="loopTitle" placeholder="Hook, bridge, drum pocket…" /></label></div>
    <div class="action-row"><button id="setLoopFromPlayhead">Use playhead +8s</button><button id="saveLoopMeta">Save loop metadata</button><button id="renderLoopAudio">Render loop audio (ffmpeg)</button></div>
    <p class="muted">Loops persist as append-only history. Rendering writes audio to data/derivatives when ffmpeg is available.</p>
  </div>
  <h2>Loops for current master/variation</h2><div class="loop-list">${renderLoopCards(currentLoops)}</div>`;
  $('setLoopFromPlayhead').addEventListener('click', () => { const t = $('mainAudio').currentTime || 0; $('loopStart').value = t.toFixed(1); $('loopEnd').value = (t + 8).toFixed(1); });
  $('saveLoopMeta').addEventListener('click', () => saveLoop(false));
  $('renderLoopAudio').addEventListener('click', () => saveLoop(true));
  wireLoopCardControls($('tab-loops'));
}

function renderLoopCards(loops) {
  if (!loops.length) return '<div class="empty">No loops clipped for this song yet.</div>';
  return loops.slice().sort((a, b) => engagementScore(b, 'loop') - engagementScore(a, 'loop')).map((loop) => {
    const e = engagementFor(loop, 'loop');
    return `<div class="loop-card" title="${esc(originLabel(loop.origin))}">
      <h3>${esc(displayTitle(loop, 'loop') || loop.title || 'Untitled loop')}</h3>
      <p>${esc(originLabel(loop.origin))} • ${fmt(loop.start)}–${fmt(loop.end)} • ▶ ${e.plays} • ♥ ${e.likes} ${e.rating ? `• ★ ${e.rating}` : ''}</p>
      <div class="action-row"><button data-loop-play="${loop.id}">Play</button><button data-like="loop:${loop.id}">♥</button><button data-playmark="loop:${loop.id}">Mark play</button><select data-rate="loop:${loop.id}">${[0, 1, 2, 3, 4, 5].map((n) => `<option value="${n}" ${e.rating === n ? 'selected' : ''}>${n || 'rate'}</option>`).join('')}</select><button data-mix-add="loop:${loop.id}" data-dock-to-mixer="loop:${loop.id}">Add to mixer</button></div>
    </div>`;
  }).join('');
}

function renderLoopDock() {
  $('loopCount').textContent = `${state.loops.length} loops`;
  $('loopDockList').innerHTML = renderLoopCards(state.loops.slice().sort((a, b) => engagementScore(b, 'loop') - engagementScore(a, 'loop')).slice(0, 40));
  wireLoopCardControls($('loopDockList'));
}
function wireLoopCardControls(root) {
  root.querySelectorAll('[data-loop-play]').forEach((btn) => btn.addEventListener('click', () => playLoop(btn.dataset.loopPlay)));
  root.querySelectorAll('[data-mix-add]').forEach((btn) => btn.addEventListener('click', () => addMixerSource(btn.dataset.mixAdd)));
  wireEngagementControls(root);
}

function renderMixer() {
  if (!state.current) return;
  const sources = mixerSourcesForCurrent();
  $('tab-mixer').innerHTML = `<p class="muted">Combine main tracks, stems, and loops. Saved derivatives retain origin attribution in append-only history and can be rendered with ffmpeg.</p>
    <div class="mixer-grid">${sources.map((src) => {
      const chosen = state.selectedMixer.has(src.key);
      const vol = state.selectedMixer.get(src.key)?.volume ?? 1;
      return `<div class="mixer-row ${chosen ? 'active' : ''}"><label><input type="checkbox" data-mixer-toggle="${src.key}" ${chosen ? 'checked' : ''}/> ${esc(src.title)}</label><span>${esc(src.kind)}</span><input type="range" min="0" max="1.5" step="0.01" value="${vol}" data-mixer-volume="${src.key}" /></div>`;
    }).join('')}</div>
    <div class="mixer-save"><input id="mixTitle" placeholder="Derivative title" /><button id="saveMixMeta">Save mix metadata</button><button id="renderMixAudio">Render mix audio</button></div>
    <h2>Derivatives</h2>${state.derivatives.slice(-20).reverse().map((d) => `<div class="relation"><b>${esc(d.title || d.id)}</b><br/><span>${esc((d.inputs || []).map((i) => i.title || i.key).join(' + '))}</span><br/><small>${esc(d.outputPath || '')}</small></div>`).join('') || '<div class="empty">No derivatives yet.</div>'}`;
  document.querySelectorAll('[data-mixer-toggle]').forEach((cb) => cb.addEventListener('change', () => toggleMixerSource(cb.dataset.mixerToggle, cb.checked)));
  document.querySelectorAll('[data-mixer-volume]').forEach((sl) => sl.addEventListener('input', () => { const entry = state.selectedMixer.get(sl.dataset.mixerVolume); if (entry) entry.volume = Number(sl.value); }));
  $('saveMixMeta').addEventListener('click', () => saveMix(false));
  $('renderMixAudio').addEventListener('click', () => saveMix(true));
}

function renderAncestry(s) {
  const master = masterInfoFor(s.id);
  const stems = stemsForVariation(s.id);
  const childDerivatives = state.derivatives.filter((d) => JSON.stringify(d.origin || {}).includes(s.id) || JSON.stringify(d.inputs || []).includes(s.id));
  $('tab-ancestry').innerHTML = `<div class="ancestry-tree">
    <div class="node master"><b>Lyric master</b><span>${esc(displayTitle(state.songs.find((x) => x.id === master.masterId) || s))}</span></div>
    <div class="branches">${master.variations.map((id) => { const v = state.songs.find((x) => x.id === id); return `<button class="node variation ${id === s.id ? 'active' : ''}" data-variation="${id}"><b>Variation</b><span>${esc(displayTitle(v || { id }))}</span></button>`; }).join('')}</div>
    <div class="branches">${stems.map((st) => `<div class="node stem-node"><b>${esc(st.stemType || 'Stem')}</b><span>${esc(displayTitle(st, 'stem'))}</span></div>`).join('') || '<div class="empty">No child stems.</div>'}</div>
    <div class="branches">${loopsForSong(s.id).map((loop) => `<div class="node loop-node"><b>Loop</b><span>${esc(loop.title || loop.id)} ${fmt(loop.start)}–${fmt(loop.end)}</span></div>`).join('') || '<div class="empty">No loops clipped yet.</div>'}</div>
    <div class="branches">${childDerivatives.map((d) => `<div class="node derivative-node"><b>Derivative</b><span>${esc(d.title || d.id)}</span></div>`).join('') || '<div class="empty">No saved derivatives from this selection.</div>'}</div>
  </div>`;
  $('tab-ancestry').querySelectorAll('[data-variation]').forEach((btn) => btn.addEventListener('click', () => selectSong(btn.dataset.variation, false)));
}

function renderRelations(s) {
  const sims = (state.registry.similarities || []).filter((x) => x.songA === s.id || x.songB === s.id).slice(0, 40);
  const groups = (state.registry.groups || []).filter((g) => (g.songIds || []).includes(s.id) && g.kind !== 'stems').slice(0, 30);
  $('tab-relations').innerHTML = `<h2>Similar / Variations</h2>${sims.map((x) => { const otherId = x.songA === s.id ? x.songB : x.songA; const o = state.songs.find((song) => song.id === otherId); return `<div class="relation" data-rel="${otherId}">${esc(displayTitle(o || { id: otherId }))} — ${(x.score * 100).toFixed(0)}% (${esc(x.reason)})</div>`; }).join('') || '<div class="empty">No close similarity links.</div>'}<h2>Groups</h2>${groups.map((g) => `<div class="kv"><b>${esc(g.kind)}</b><span>${esc(g.key)} (${g.count})</span></div>`).join('')}`;
  document.querySelectorAll('[data-rel]').forEach((el) => el.addEventListener('click', () => selectSong(el.dataset.rel, false)));
}
function renderTelemetry(s) {
  const persisted = audioTelemetryFor(s);
  const run = persisted?.kind === 'hapa.audioTelemetry.run' ? persisted : null;
  const manifest = run ? s.audioTelemetry : persisted;
  const summary = run?.summary || manifest?.summary || null;
  const hooks = (run?.timeline?.events || []).filter((ev) => ev.type === 'hook_candidate').slice(0, 12);
  const sections = (run?.timeline?.events || []).filter((ev) => ev.type === 'section').slice(0, 12);
  $('tab-telemetry').innerHTML = `<div class="action-row"><button id="analyzeAudioTelemetry">Analyze / refresh audio telemetry</button><button id="openTelemetryManifest" ${manifest?.manifestPath ? '' : 'disabled'}>Show manifest in folder</button></div>
    <h2>Audio telemetry analysis queue</h2>
    ${summary ? `<div class="timing-summary">Persisted run ${esc(run?.runId || manifest?.latestRunId || 'manifest')} • status ${esc(run?.status || manifest?.status)} • confidence ${Math.round(((run?.confidence ?? manifest?.confidence) || 0) * 100)}% • BPM ${esc(summary.bpm || 'n/a')} • ${summary.beatCount || 0} beats • ${summary.sectionCount || 0} sections • ${summary.hookCount || 0} hook candidates</div>` : '<div class="timing-summary low">No persisted audio telemetry yet. Click Analyze to decode once, write artifacts, and reuse the summary/timeline across the app.</div>'}
    ${hooks.length ? `<h2>Hook candidates</h2>${hooks.map((ev) => `<div class="kv"><b>${esc(ev.label || 'hook candidate')}</b><span>${fmt(ev.start)}–${fmt(ev.end)} • ${Math.round((ev.confidence || 0) * 100)}% • ${(ev.reasons || []).map(esc).join(', ')}</span></div>`).join('')}` : ''}
    ${sections.length ? `<h2>Sections</h2>${sections.map((ev) => `<div class="kv"><b>${esc(ev.label || 'section')}</b><span>${fmt(ev.start)}–${fmt(ev.end)} • ${Math.round((ev.confidence || 0) * 100)}%</span></div>`).join('')}` : ''}
    <h2>Normalized song telemetry</h2><pre>${esc(JSON.stringify({ id: s.id, title: displayTitle(s), createdAt: s.createdAt, duration: s.duration, model: s.model, majorModelVersion: s.majorModelVersion, audioTelemetry: s.audioTelemetry || null, engagement: engagementFor(s, 'song'), facets: s.facets, stemCount: s.stemCount, stemTypes: s.stemTypes, lyricTiming: s.lyricTiming ? { method: s.lyricTiming.method, source: s.lyricTiming.source, sourcePath: s.lyricTiming.sourcePath, confidence: s.lyricTiming.confidence, stats: s.lyricTiming.stats, warnings: s.lyricTiming.warnings } : null, settings: s.settings, localPath: s.localPath, audioUrl: s.audioUrl, imageUrl: s.imageUrl }, null, 2))}</pre>
    ${run ? `<h2>Persisted audio telemetry run</h2><pre>${esc(JSON.stringify({ runId: run.runId, summary: run.summary, waveform: run.waveform, rhythm: run.rhythm, timelinePreview: (run.timeline?.events || []).slice(0, 40), provenance: run.provenance, warnings: run.warnings }, null, 2))}</pre>` : ''}
    <h2>Append-only overlays for current song</h2><pre>${esc(JSON.stringify(state.events.filter((e) => JSON.stringify(e).includes(s.id)).slice(-80), null, 2))}</pre><h2>Raw Suno metadata</h2><pre>${esc(JSON.stringify(s.raw, null, 2))}</pre>`;
  const analyzeBtn = $('analyzeAudioTelemetry');
  if (analyzeBtn) analyzeBtn.addEventListener('click', analyzeCurrentAudioTelemetry);
  const showBtn = $('openTelemetryManifest');
  if (showBtn && manifest?.manifestPath) showBtn.addEventListener('click', () => window.hapa.showInFolder(manifest.manifestPath));
}
function stemsFor(id) { return stemsForVariation(id); }

function anyStemPlaying() { return [...state.stems.values()].some((item) => !item.audio.paused); }
async function togglePlay() { $('mainAudio').paused ? playAll() : pauseAll(); }
async function playAll() {
  if (!state.current) return;
  if (state.audioCtx?.state === 'suspended') await state.audioCtx.resume();
  const main = $('mainAudio');
  if (main.src) main.play().catch((err) => toast(`Main playback failed: ${err.message}`));
  else await playStemSession(main.currentTime || 0);
  $('play').textContent = '⏸'; animate();
}
function pauseAll() {
  $('mainAudio').pause();
  if (state.dawEngine) state.dawEngine.pause();
  if (state.dawVisualRaf) cancelAnimationFrame(state.dawVisualRaf);
  state.dawVisualRaf = null;
  updateDawStatusReadout();
  for (const item of state.stems.values()) item.audio.pause();
  state.stemSessionPlaying = false;
  $('play').textContent = '▶';
}
function playAdjacent(dir) {
  const pool = state.queue.length ? state.queue.map((id) => state.songs.find((s) => s.id === id)).filter(Boolean) : state.filtered;
  const idx = pool.findIndex((s) => s.id === state.current?.id);
  const next = pool[(idx + dir + pool.length) % pool.length];
  if (next) selectSong(next.id, true);
}
async function onStemToggle(e) {
  const item = await ensureStemAudio(e.target.dataset.stemToggle); if (!item) return;
  item.enabled = e.target.checked;
  if (item.enabled) await playStemAudio(item.stem.id, false); else item.audio.pause();
}
async function playStemAudio(id, solo = false) {
  const item = await ensureStemAudio(id);
  if (!item) { toast('Stem audio file is missing.'); return false; }
  if (solo) {
    state.stemSoloState.clear();
    state.stemSoloState.add(id);
    $('muteMain').checked = true; $('mainAudio').muted = true;
  }
  item.enabled = true;
  state.stemMuteState.set(id, false);
  applyStemMixState();
  try {
    if (Math.abs(item.audio.currentTime - ($('mainAudio').currentTime || 0)) > 0.35) item.audio.currentTime = $('mainAudio').currentTime || 0;
    await item.audio.play();
    const cb = document.querySelector(`[data-stem-toggle="${id}"]`);
    if (cb) cb.checked = true;
    return true;
  } catch (err) {
    toast(`Stem playback failed: ${err.message}`);
    appendEvent({ type: 'stem.playback.failed', targetType: 'stem', targetId: id, reason: err.message }).catch(console.error);
    return false;
  }
}
function soloStem(id) {
  state.stemSoloState.clear();
  state.stemSoloState.add(id);
  $('muteMain').checked = true;
  $('mainAudio').muted = true;
  if (state.dawEngine) state.dawEngine.setTrackSolo(id, true);
  playStemSession($('mainAudio').currentTime || state.dawEngine?.currentTime() || 0);
}
async function playStemSession(startAt = $('mainAudio').currentTime || 0, options = {}) {
  if (!state.current) return;
  state.stemSessionPlaying = true;
  const engine = await loadDawSessionForCurrent(state.current);
  if (engine) {
    await engine.resume();
    state.dawEngine.clearLoopRegion();
    state.dawIncludeMain = Boolean(options.includeMain);
    const mainTrackId = `song:${state.current.id}`;
    if (state.dawEngine.tracks.has(mainTrackId)) state.dawEngine.setTrackMute(mainTrackId, !state.dawIncludeMain || $('muteMain')?.checked || !$('mainAudio').paused);
    for (const id of state.stems.keys()) state.dawEngine.setTrackMute(id, Boolean(state.stemMuteState.get(id)));
    if (state.stemSoloState.size) {
      for (const id of state.stemSoloState) state.dawEngine.setTrackSolo(id, true);
    } else {
      state.dawEngine.clearSolo();
    }
    state.dawEngine.play(clamp(startAt, 0, state.current?.duration || startAt));
    updateDawStatusReadout();
    drawLiveDawVisuals();
    applyStemMixState();
    return;
  }
  const plays = [];
  for (const [id, item] of state.stems.entries()) {
    if (state.stemMuteState.get(id)) continue;
    if (state.stemSoloState.size && !state.stemSoloState.has(id)) continue;
    if (Number.isFinite(startAt)) item.audio.currentTime = clamp(startAt, 0, item.audio.duration || state.current?.duration || startAt);
    plays.push(item.audio.play().catch((err) => {
      appendEvent({ type: 'stem.playback.failed', targetType: 'stem', targetId: id, reason: err.message }).catch(console.error);
    }));
  }
  applyStemMixState();
  await Promise.all(plays);
}
function seekStemSession(time) {
  if (state.dawEngine) state.dawEngine.seek(time);
  for (const item of state.stems.values()) item.audio.currentTime = clamp(time, 0, item.audio.duration || state.current?.duration || time);
}
function applyStemMixState() {
  for (const [id, item] of state.stems.entries()) {
    const muted = Boolean(state.stemMuteState.get(id)) || (state.stemSoloState.size > 0 && !state.stemSoloState.has(id));
    item.audio.muted = muted;
    if (state.dawEngine) {
      state.dawEngine.setTrackMute(id, Boolean(state.stemMuteState.get(id)));
      if (state.stemSoloState.has(id)) state.dawEngine.setTrackSolo(id, true);
      else if (!state.stemSoloState.size) state.dawEngine.clearSolo();
    }
    const cb = document.querySelector(`[data-stem-mute="${id}"]`);
    if (cb) cb.checked = !item.audio.muted;
  }
  if (state.dawEngine?.tracks?.has(`song:${state.current?.id}`)) {
    const muteMain = $('muteMain')?.checked || !state.dawIncludeMain || !$('mainAudio')?.paused;
    state.dawEngine.setTrackMute(`song:${state.current.id}`, muteMain);
  }
}
function syncStemsToMain() { seekStemSession($('mainAudio').currentTime || 0); }
function onTime() {
  const a = $('mainAudio');
  $('seek').value = a.duration ? Math.floor((a.currentTime / a.duration) * 1000) : 0;
  $('time').textContent = `${fmt(a.currentTime)} / ${fmt(a.duration || state.current?.duration)}`;
  highlightLyric(a.currentTime, a.duration || state.current?.duration || 1);
}
function highlightLyric(t, dur) {
  const lines = [...document.querySelectorAll('.lyric-line')]; if (!lines.length) return;
  let idx = -1;
  const timed = state.current?.lyricTiming?.lines || [];
  if (timed.length) {
    idx = timed.findIndex((line) => t >= line.start && t < line.end);
    if (idx < 0) {
      let best = 0;
      for (let i = 0; i < timed.length; i++) if (timed[i].start <= t) best = i;
      idx = best;
    }
  } else {
    idx = Math.min(lines.length - 1, Math.floor((t / dur) * lines.length));
  }
  lines.forEach((el, i) => el.classList.toggle('current', i === idx));
  if (lines[idx]) lines[idx].scrollIntoView({ block: 'center', behavior: 'smooth' });
}
function renderQueue() {
  $('queue').innerHTML = state.queue.slice(0, 80).map((id) => { const s = state.songs.find((x) => x.id === id); return `<li>${esc(displayTitle(s || { id }))}</li>`; }).join('');
}

async function renameTarget(targetType, targetId, oldTitle) {
  const title = prompt(`Rename ${targetType}`, oldTitle || '');
  if (!title || title === oldTitle) return;
  await appendEvent({ type: `${targetType}.renamed`, targetType, targetId, title });
}
function recordPlay(targetType, targetId) {
  const key = `${targetType}:${targetId}:lastPlayEvent`;
  const now = Date.now();
  if (state[key] && now - state[key] < 20000) return;
  state[key] = now;
  appendEvent({ type: `${targetType}.played`, targetType, targetId, count: 1 }).catch(console.error);
}

function fillLoopClip(sourceKey) {
  switchTab('loops');
  setTimeout(() => { if ($('loopSource')) $('loopSource').value = sourceKey; }, 0);
}
function sourceFromKey(key) {
  const [type, id] = key.split(':');
  if (type === 'song') { const s = state.songs.find((x) => x.id === id); return { type, id, item: s, path: s?.localPath, title: displayTitle(s || { id }) }; }
  if (type === 'stem') { const st = (state.registry.stems || []).find((x) => x.id === id); return { type, id, item: st, path: st?.localPath, title: displayTitle(st || { id }, 'stem') }; }
  const loop = state.loops.find((x) => x.id === id);
  const origin = loop?.origin ? sourceFromKey(`${loop.origin.type}:${loop.origin.id}`) : null;
  return { type, id, item: loop, path: loop?.outputPath || origin?.path, title: displayTitle(loop || { id }, 'loop'), start: loop?.start, end: loop?.end, duration: loop?.duration, rendered: Boolean(loop?.outputPath) };
}
async function saveLoop(renderAudio) {
  if (!state.current) return;
  const key = $('loopSource').value;
  const src = sourceFromKey(key);
  const start = clamp($('loopStart').value, 0, state.current.duration || 9999);
  const end = clamp($('loopEnd').value, start + 0.1, state.current.duration || start + 9999);
  const title = $('loopTitle').value || `${displayTitle(state.current)} loop ${fmt(start)}`;
  const loopId = idFor('loop');
  const payload = { type: 'loop.created', targetType: 'loop', targetId: loopId, loopId, title, origin: { type: src.type, id: src.id, songId: state.current.id, title: src.title }, start, end, duration: end - start };
  if (renderAudio) {
    try {
      const saved = await window.hapa.createClip({ ...payload, inputPath: src.path });
      state.events.push(saved); applyEvent(saved, true); toast('Rendered loop audio.');
    } catch (err) { toast(`ffmpeg clip failed: ${err.message}. Saving metadata only.`); await appendEvent(payload); }
  } else await appendEvent(payload);
}
function loopsForSong(songId) {
  const master = masterInfoFor(songId);
  const ids = new Set([songId, ...master.variations]);
  return state.loops.filter((loop) => ids.has(loop.origin?.songId) || ids.has(loop.origin?.id));
}
async function playLoop(loopId) {
  const loop = state.loops.find((x) => x.id === loopId); if (!loop) return;
  const source = loop.origin ? sourceFromKey(`${loop.origin.type}:${loop.origin.id}`) : null;
  if (source?.type === 'song' && source.id !== state.current?.id) await selectSong(source.id, false);
  if (source?.type === 'stem') {
    await playStemLoopRegion(source.id, loop);
  } else {
    $('mainAudio').currentTime = Number(loop.start || 0);
    await playAll();
    stopAtLoopEnd($('mainAudio'), loop);
  }
  recordPlay('loop', loop.id);
}

async function playStemLoopRegion(stemId, loop) {
  const stem = (state.registry.stems || []).find((x) => x.id === stemId);
  if (stem?.parentId && stem.parentId !== state.current?.id) await selectSong(stem.parentId, false);
  state.stemSoloState.clear();
  state.stemSoloState.add(stemId);
  $('muteMain').checked = true; $('mainAudio').muted = true;
  const item = await ensureStemAudio(stemId);
  if (!item) return;
  const start = Number(loop.start || 0);
  const end = Number(loop.end || (start + Number(loop.duration || 0)));
  const engine = await loadDawSessionForCurrent(state.current);
  if (engine) {
    await engine.resume();
    state.dawIncludeMain = false;
    state.dawEngine.setLoopRegion(start, end);
    state.dawEngine.setTrackSolo(stemId, true);
    state.dawEngine.setTrackMute(`song:${state.current.id}`, true);
    state.dawEngine.play(start);
    updateDawStatusReadout();
    drawLiveDawVisuals();
    state.stemSessionPlaying = true;
    applyStemMixState();
    return;
  }
  item.audio.currentTime = start;
  applyStemMixState();
  await item.audio.play().catch((err) => toast(`Stem loop playback failed: ${err.message}`));
  stopAtLoopEnd(item.audio, loop);
}

function stopAtLoopEnd(audio, loop) {
  if (state.loopStopTimer) clearInterval(state.loopStopTimer);
  const end = Number(loop.end || (Number(loop.start || 0) + Number(loop.duration || 0)));
  state.loopStopTimer = setInterval(() => {
    if (audio.paused || audio.currentTime >= end) {
      clearInterval(state.loopStopTimer);
      state.loopStopTimer = null;
      pauseAll();
    }
  }, 60);
}
function originLabel(origin) {
  if (!origin) return 'Unknown origin';
  return `${origin.type || 'source'}: ${origin.title || origin.id} @ ${origin.songId || origin.id}`;
}

function mixerSourcesForCurrent() {
  if (!state.current) return [];
  return [
    { key: `song:${state.current.id}`, kind: 'main', title: displayTitle(state.current), path: state.current.localPath },
    ...stemsForVariation(state.current.id).map((st) => ({ key: `stem:${st.id}`, kind: st.stemType || 'stem', title: displayTitle(st, 'stem'), path: st.localPath })),
    ...loopsForSong(state.current.id).map((loop) => { const src = sourceFromKey(`loop:${loop.id}`); return { key: `loop:${loop.id}`, kind: 'loop', title: loop.title || loop.id, path: src.path, loop, start: loop.start, end: loop.end, rendered: Boolean(loop.outputPath) }; }),
  ];
}
function addMixerSource(key) { state.selectedMixer.set(key, { key, volume: 1 }); switchTab('mixer'); renderMixer(); }
function toggleMixerSource(key, enabled) { if (enabled) addMixerSource(key); else state.selectedMixer.delete(key); renderMixer(); }
function buildMixerInputs() {
  const all = mixerSourcesForCurrent();
  return [...state.selectedMixer.values()].map((entry) => {
    const src = all.find((candidate) => candidate.key === entry.key);
    if (!src) return null;
    if (src.loop) return { ...src, volume: entry.volume, start: src.rendered ? 0 : src.loop.start, end: src.rendered ? undefined : src.loop.end };
    return { ...src, volume: entry.volume };
  }).filter((x) => x?.path);
}
async function saveMix(renderAudio) {
  const inputs = buildMixerInputs();
  if (!inputs.length) { toast('Choose at least one mixer input.'); return; }
  const derivativeId = idFor('derivative');
  const title = $('mixTitle').value || `Derivative from ${displayTitle(state.current)}`;
  const payload = { type: 'derivative.created', targetType: 'derivative', targetId: derivativeId, derivativeId, title, origin: { songId: state.current.id, title: displayTitle(state.current) }, inputs: inputs.map((x) => ({ key: x.key, title: x.title, kind: x.kind, path: x.path, volume: x.volume, start: x.start, end: x.end })) };
  if (renderAudio) {
    try {
      const saved = await window.hapa.createMix(payload);
      state.events.push(saved); applyEvent(saved, true); toast('Rendered mixer derivative.');
    } catch (err) { toast(`ffmpeg mix failed: ${err.message}. Saving metadata only.`); await appendEvent(payload); }
  } else await appendEvent(payload);
}

function refreshAll() {
  renderStats(); applyFilters(); if (state.current) { renderNow(); renderDetails(); } renderLoopDock();
}
function toast(message) {
  const el = $('toast');
  el.textContent = message;
  el.classList.add('show');
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => el.classList.remove('show'), 2800);
}

function drawStemWaves() {
  document.querySelectorAll('[data-stem-wave]').forEach((canvas) => {
    const id = canvas.dataset.stemWave;
    const stem = (state.registry.stems || []).find((x) => x.id === id);
    renderAnalysisCanvas(canvas, 'waveform', null);
    if (stem) analyzeStemAudio(stem).then((analysis) => renderAnalysisCanvas(canvas, 'waveform', analysis));
  });
}
function animate() {
  if (state.raf) cancelAnimationFrame(state.raf);
  const canvas = $('viz'); const ctx = canvas.getContext('2d');
  const resize = () => { canvas.width = canvas.clientWidth * devicePixelRatio; canvas.height = canvas.clientHeight * devicePixelRatio; };
  resize();
  const data = new Uint8Array(state.analyser?.frequencyBinCount || 1024);
  const loop = () => {
    if (state.analyser) state.analyser.getByteFrequencyData(data);
    paint(ctx, canvas, data, Boolean(state.analyser));
    state.raf = requestAnimationFrame(loop);
  };
  loop();
}
function drawIdle() { const c = $('viz'), ctx = c.getContext('2d'); c.width = c.clientWidth * devicePixelRatio; c.height = c.clientHeight * devicePixelRatio; paint(ctx, c, new Uint8Array(256).map((_, i) => 80 + 60 * Math.sin(i)), false); }
function paint(ctx, canvas, data, live) {
  const w = canvas.width, h = canvas.height; ctx.clearRect(0, 0, w, h);
  const grd = ctx.createLinearGradient(0, 0, w, h); grd.addColorStop(0, '#111947'); grd.addColorStop(.45, '#180827'); grd.addColorStop(1, '#031a24'); ctx.fillStyle = grd; ctx.fillRect(0, 0, w, h);
  const cx = w / 2, cy = h / 2; const bars = 96; const step = Math.floor(data.length / bars) || 1;
  for (let i = 0; i < bars; i++) {
    const v = (data[i * step] || 0) / 255; const ang = (Math.PI * 2 * i) / bars; const r = 40 * devicePixelRatio + v * 120 * devicePixelRatio;
    const x1 = cx + Math.cos(ang) * r, y1 = cy + Math.sin(ang) * r; const x2 = cx + Math.cos(ang) * (r + 30 * devicePixelRatio + v * 150 * devicePixelRatio), y2 = cy + Math.sin(ang) * (r + 30 * devicePixelRatio + v * 150 * devicePixelRatio);
    ctx.strokeStyle = `hsla(${(i * 4 + Date.now() / 80) % 360},100%,65%,${.25 + v * .75})`; ctx.lineWidth = 2 * devicePixelRatio; ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
  }
  ctx.fillStyle = 'rgba(255,255,255,.08)'; ctx.beginPath(); ctx.arc(cx, cy, (live ? 42 : 32) * devicePixelRatio, 0, Math.PI * 2); ctx.fill();
}

init().catch((err) => { console.error(err); document.body.innerHTML = `<pre>${esc(err.stack || err)}</pre>`; });
