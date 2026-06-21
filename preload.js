'use strict';

const { contextBridge, ipcRenderer } = require('electron');

// Only these hosts may be opened externally from the renderer (https-only).
const ALLOWED_EXTERNAL_HOSTS = [
  'github.com',
  'www.github.com',
  'docs.github.com',
  'githubcopilot.com',
  'cli.github.com',
];

function isAllowedExternal(url) {
  try {
    const u = new URL(url);
    return u.protocol === 'https:' && ALLOWED_EXTERNAL_HOSTS.includes(u.hostname);
  } catch {
    return false;
  }
}

contextBridge.exposeInMainWorld('electronAPI', {
  // Auth / credentials
  getCredentials: () => ipcRenderer.invoke('get-credentials'),
  detectCredentials: () => ipcRenderer.invoke('detect-credentials'),
  saveCredentials: (token) => ipcRenderer.invoke('save-credentials', token),
  deleteCredentials: () => ipcRenderer.invoke('delete-credentials'),

  // Usage data
  fetchUsageData: () => ipcRenderer.invoke('fetch-usage-data'),
  getUsageHistory: () => ipcRenderer.invoke('get-usage-history'),

  // Window controls
  minimizeWindow: () => ipcRenderer.send('minimize-window'),
  closeWindow: () => ipcRenderer.send('close-window'),
  resizeWindow: (size) => ipcRenderer.send('resize-window', size),
  getWindowPosition: () => ipcRenderer.invoke('get-window-position'),
  setWindowPosition: (pos) => ipcRenderer.send('set-window-position', pos),
  setCompactMode: (compact) => ipcRenderer.invoke('set-compact-mode', compact),

  // Settings
  getSettings: () => ipcRenderer.invoke('get-settings'),
  saveSettings: (partial) => ipcRenderer.invoke('save-settings', partial),

  // Misc
  openExternal: (url) => {
    if (isAllowedExternal(url)) return ipcRenderer.invoke('open-external', url);
    return Promise.resolve({ success: false, error: 'blocked' });
  },
  checkForUpdate: () => ipcRenderer.invoke('check-for-update'),
  getAppVersion: () => ipcRenderer.invoke('get-app-version'),
  showNotification: (payload) => ipcRenderer.invoke('show-notification', payload),

  // Events main → renderer
  onRefreshUsage: (cb) => ipcRenderer.on('refresh-usage', () => cb()),
  onSessionExpired: (cb) => ipcRenderer.on('session-expired', () => cb()),

  platform: process.platform,
  isPortable: process.platform === 'win32' && !!process.env.PORTABLE_EXECUTABLE_FILE,
});
