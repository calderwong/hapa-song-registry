const { app, BrowserWindow, ipcMain, shell } = require('electron');
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');

const ROOT = path.resolve(__dirname, '..');
const DATA_DIR = path.join(ROOT, 'data');
const DATA_PATH = path.join(DATA_DIR, 'registry.json');
const HISTORY_PATH = path.join(DATA_DIR, 'history_events.json');
const DERIVATIVE_DIR = path.join(DATA_DIR, 'derivatives');

function ensureDataFiles() {
  fs.mkdirSync(DATA_DIR, { recursive: true });
  fs.mkdirSync(DERIVATIVE_DIR, { recursive: true });
  if (!fs.existsSync(HISTORY_PATH)) fs.writeFileSync(HISTORY_PATH, '[]\n');
}

function readJsonSafe(filePath, fallback) {
  try {
    if (!fs.existsSync(filePath)) return fallback;
    return JSON.parse(fs.readFileSync(filePath, 'utf8'));
  } catch (err) {
    console.error(`Failed to read ${filePath}:`, err);
    return fallback;
  }
}

function appendHistoryEvent(event) {
  ensureDataFiles();
  const events = readJsonSafe(HISTORY_PATH, []);
  const record = {
    id: event.id || `${Date.now()}-${Math.random().toString(36).slice(2)}`,
    at: event.at || new Date().toISOString(),
    ...event,
  };
  events.push(record);
  fs.writeFileSync(HISTORY_PATH, `${JSON.stringify(events, null, 2)}\n`);
  return record;
}

function safeFilePart(value) {
  return String(value || 'derivative')
    .replace(/[\\/:*?"<>|]/g, '_')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 90) || 'derivative';
}

function runFfmpeg(args) {
  return new Promise((resolve, reject) => {
    const child = spawn('ffmpeg', ['-hide_banner', '-y', ...args], { stdio: ['ignore', 'ignore', 'pipe'] });
    let stderr = '';
    child.stderr.on('data', (buf) => { stderr += buf.toString(); });
    child.on('error', reject);
    child.on('close', (code) => {
      if (code === 0) resolve(true);
      else reject(new Error(stderr || `ffmpeg exited with code ${code}`));
    });
  });
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1650,
    height: 1020,
    minWidth: 1180,
    minHeight: 780,
    backgroundColor: '#080912',
    title: 'Hapa Song Registry',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });
  win.loadFile(path.join(__dirname, 'index.html'));
}

ipcMain.handle('registry:load', async () => {
  ensureDataFiles();
  const registry = readJsonSafe(DATA_PATH, { songs: [], stems: [], groups: [], similarities: [], facets: {}, counts: {} });
  registry.historyEvents = readJsonSafe(HISTORY_PATH, []);
  return registry;
});

ipcMain.handle('history:append', async (_event, event) => appendHistoryEvent(event || {}));

ipcMain.handle('audio:createClip', async (_event, payload = {}) => {
  const input = payload.inputPath;
  if (!input || !fs.existsSync(input)) throw new Error('Clip source file is missing.');
  const start = Math.max(0, Number(payload.start || 0));
  const end = Math.max(start + 0.1, Number(payload.end || start + 8));
  const duration = Math.max(0.1, end - start);
  const title = safeFilePart(payload.title || `loop ${start.toFixed(1)}-${end.toFixed(1)}`);
  const outputPath = path.join(DERIVATIVE_DIR, `${title}-${Date.now()}.mp3`);
  await runFfmpeg(['-i', input, '-filter_complex', `atrim=start=${start}:duration=${duration},asetpts=PTS-STARTPTS[out]`, '-map', '[out]', '-c:a', 'libmp3lame', '-q:a', '2', outputPath]);
  return appendHistoryEvent({
    type: 'loop.created',
    targetType: 'loop',
    loopId: payload.loopId,
    title: payload.title,
    outputPath,
    origin: payload.origin,
    start,
    end,
    duration,
  });
});

ipcMain.handle('audio:createMix', async (_event, payload = {}) => {
  const inputs = (payload.inputs || []).filter((item) => item && item.path && fs.existsSync(item.path));
  if (!inputs.length) throw new Error('No readable mixer inputs were provided.');
  const title = safeFilePart(payload.title || 'mixer derivative');
  const outputPath = path.join(DERIVATIVE_DIR, `${title}-${Date.now()}.mp3`);
  const args = [];
  inputs.forEach((item) => args.push('-i', item.path));
  const filters = inputs.map((item, idx) => {
    const start = Number(item.start);
    const end = Number(item.end);
    const trim = Number.isFinite(start) && Number.isFinite(end) && end > start
      ? `atrim=start=${Math.max(0, start)}:end=${end},asetpts=PTS-STARTPTS,`
      : '';
    return `[${idx}:a]${trim}volume=${Number(item.volume ?? 1)}[a${idx}]`;
  }).join(';') + ';' + inputs.map((_item, idx) => `[a${idx}]`).join('') + `amix=inputs=${inputs.length}:duration=longest:dropout_transition=0[out]`;
  args.push('-filter_complex', filters, '-map', '[out]', '-c:a', 'libmp3lame', '-q:a', '2', outputPath);
  await runFfmpeg(args);
  return appendHistoryEvent({
    type: 'derivative.created',
    targetType: 'derivative',
    derivativeId: payload.derivativeId,
    title: payload.title,
    outputPath,
    origin: payload.origin,
    inputs: payload.inputs,
  });
});

ipcMain.handle('path:fileUrl', async (_event, filePath) => {
  if (!filePath) return null;
  return 'file://' + path.resolve(filePath).split(path.sep).map(encodeURIComponent).join('/');
});

ipcMain.handle('path:show', async (_event, filePath) => {
  if (!filePath) return false;
  shell.showItemInFolder(filePath);
  return true;
});

ipcMain.handle('app:openDataFolder', async () => {
  ensureDataFiles();
  await shell.openPath(DATA_DIR);
  return true;
});

app.whenReady().then(() => {
  ensureDataFiles();
  createWindow();
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
