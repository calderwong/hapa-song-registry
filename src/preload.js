const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('hapa', {
  loadRegistry: () => ipcRenderer.invoke('registry:load'),
  appendHistory: (event) => ipcRenderer.invoke('history:append', event),
  createClip: (payload) => ipcRenderer.invoke('audio:createClip', payload),
  createMix: (payload) => ipcRenderer.invoke('audio:createMix', payload),
  fileUrl: (filePath) => ipcRenderer.invoke('path:fileUrl', filePath),
  showInFolder: (filePath) => ipcRenderer.invoke('path:show', filePath),
  openDataFolder: () => ipcRenderer.invoke('app:openDataFolder'),
});
