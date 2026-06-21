'use strict';

const {
  app,
  BrowserWindow,
  ipcMain,
  Tray,
  Menu,
  shell,
  Notification,
  safeStorage,
  nativeImage,
} = require('electron');
const path = require('path');
const fs = require('fs');
const https = require('https');
const Store = require('electron-store');

const { fetchUsage } = require('./src/copilot-api');
const { detectToken, validateToken } = require('./src/auth');
const { renderTrayIcon, destroyTrayRenderer } = require('./src/tray-icon');

// ── Constants ────────────────────────────────────────────────────────────────
const GITHUB_OWNER = 'orty';
const GITHUB_REPO = 'copilot-usage-widget';
const COPILOT_URL = 'https://github.com/features/copilot';
const REPO_URL = `https://github.com/${GITHUB_OWNER}/${GITHUB_REPO}`;

const WIDGET_WIDTH = 560;
const WIDGET_HEIGHT = 155;
const COMPACT_WIDTH = 290;
const COMPACT_HEIGHT = 105;

// Status palette (mirrors the upstream widget's design system).
const COLOR = {
  session: '#8b5cf6', // purple — primary (premium) metric
  weekly: '#3b82f6', // blue — secondary metric
  warning: '#f59e0b',
  danger: '#ef4444',
  fg: '#ffffff',
};

const DEFAULT_SETTINGS = {
  autoStart: false,
  minimizeToTray: false,
  alwaysOnTop: true,
  theme: 'dark',
  warnThreshold: 75,
  dangerThreshold: 90,
  timeFormat: '12h',
  weeklyDateFormat: 'date',
  usageAlerts: true,
  compactMode: false,
  refreshInterval: '180',
  graphVisible: false,
  expandedOpen: false,
  showTrayStats: false,
};

const HISTORY_MAX = 10000;
const HISTORY_RETAIN_MS = 8 * 24 * 3600 * 1000;

const store = new Store();

let mainWindow = null;
let sessionTray = null;
let weeklyTray = null;
let alwaysOnTopTimer = null;
let notifiedThresholds = {}; // { metricId: { periodKey: [thresholds] } }

// ── Token storage (safeStorage with plaintext fallback) ──────────────────────
function saveToken(token) {
  if (safeStorage.isEncryptionAvailable()) {
    store.set('token_encrypted', safeStorage.encryptString(token).toString('base64'));
    store.delete('token');
  } else {
    store.set('token', token);
  }
}

function loadToken() {
  const enc = store.get('token_encrypted');
  if (enc && safeStorage.isEncryptionAvailable()) {
    try {
      return safeStorage.decryptString(Buffer.from(enc, 'base64'));
    } catch {
      return null;
    }
  }
  return store.get('token') || null;
}

function clearToken() {
  store.delete('token_encrypted');
  store.delete('token');
}

function hasToken() {
  return !!loadToken();
}

// ── Settings helpers ─────────────────────────────────────────────────────────
function getSettings() {
  return { ...DEFAULT_SETTINGS, ...(store.get('settings') || {}) };
}

function saveSettings(partial) {
  const merged = { ...getSettings(), ...partial };
  store.set('settings', merged);
  applySettings(merged);
  return merged;
}

function applySettings(settings) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.setAlwaysOnTop(!!settings.alwaysOnTop, 'floating');
    mainWindow.setSkipTaskbar(!!settings.minimizeToTray);
  }
  app.setLoginItemSettings({
    openAtLogin: !!settings.autoStart,
    ...(process.platform !== 'darwin' && { path: app.getPath('exe') }),
  });
}

// ── History ──────────────────────────────────────────────────────────────────
function pushHistory(usage) {
  if (!usage || !usage.metrics || !usage.metrics.length) return;
  const history = store.get('history') || [];
  const sample = { t: usage.fetchedAt || Date.now(), m: {} };
  for (const metric of usage.metrics) sample.m[metric.id] = Math.round(metric.percentUsed);
  history.push(sample);
  const cutoff = Date.now() - HISTORY_RETAIN_MS;
  const trimmed = history.filter((s) => s.t >= cutoff).slice(-HISTORY_MAX);
  store.set('history', trimmed);
}

// ── Notifications (threshold alerts) ─────────────────────────────────────────
const TOAST_THRESHOLDS = [75, 90, 95, 100];

function maybeNotify(usage) {
  if (!getSettings().usageAlerts) return;
  const period = (usage.resetDateUtc || '').slice(0, 10);
  for (const metric of usage.metrics) {
    const fired = (notifiedThresholds[metric.id] || {})[period] || [];
    for (const t of TOAST_THRESHOLDS) {
      if (metric.percentUsed >= t && !fired.includes(t)) {
        new Notification({
          title: 'Copilot Usage',
          body: `${metric.label}: ${Math.round(metric.percentUsed)}% used (${metric.remaining} remaining)`,
        }).show();
        notifiedThresholds[metric.id] = notifiedThresholds[metric.id] || {};
        notifiedThresholds[metric.id][period] = [...fired, t];
      }
    }
  }
}

// ── Tray ─────────────────────────────────────────────────────────────────────
function staticTrayImage() {
  const p = path.join(
    __dirname,
    'assets',
    process.platform === 'darwin'
      ? 'tray-icon-mac.png'
      : process.platform === 'linux'
        ? 'tray-icon-linux.png'
        : 'tray-icon.png'
  );
  return fs.existsSync(p) ? p : path.join(__dirname, 'assets', 'logo.png');
}

function trayColorFor(percentUsed, base) {
  const s = getSettings();
  if (percentUsed >= s.dangerThreshold) return COLOR.danger;
  if (percentUsed >= s.warnThreshold) return COLOR.warning;
  return base;
}

function buildTrayMenu() {
  return Menu.buildFromTemplate([
    {
      label: 'Show Widget',
      click: () => {
        if (mainWindow && !mainWindow.isDestroyed()) {
          mainWindow.show();
          mainWindow.focus();
        } else {
          createMainWindow();
        }
      },
    },
    {
      label: 'Refresh',
      click: () => mainWindow && mainWindow.webContents.send('refresh-usage'),
    },
    { type: 'separator' },
    {
      label: 'Log Out',
      click: () => {
        clearToken();
        if (mainWindow) mainWindow.webContents.send('session-expired');
      },
    },
    { type: 'separator' },
    { label: 'Exit', click: () => app.quit() },
  ]);
}

function createTrays() {
  const img = staticTrayImage();
  sessionTray = new Tray(img);
  sessionTray.setToolTip('Copilot — primary quota');
  sessionTray.setContextMenu(buildTrayMenu());

  weeklyTray = new Tray(img);
  weeklyTray.setToolTip('Copilot — secondary quota');
  weeklyTray.setContextMenu(buildTrayMenu());
  // Second tray hidden until there's a second limited quota to show.
  weeklyTray.setImage(nativeImage.createEmpty());
}

async function updateTrays(usage) {
  if (!getSettings().showTrayStats || !usage || !usage.metrics.length) {
    if (sessionTray) sessionTray.setImage(nativeImage.createFromPath(staticTrayImage()));
    if (weeklyTray) weeklyTray.setImage(nativeImage.createEmpty());
    return;
  }
  const [primary, secondary] = usage.metrics;
  try {
    if (primary && sessionTray) {
      const mark = primary.percentUsed >= 99 ? 'X' : null;
      const icon = await renderTrayIcon({
        percent: primary.percentUsed,
        bg: trayColorFor(primary.percentUsed, COLOR.session),
        fg: COLOR.fg,
        mark,
      });
      sessionTray.setImage(icon);
      sessionTray.setToolTip(`${primary.label}: ${Math.round(primary.percentUsed)}% used`);
    }
    if (secondary && weeklyTray) {
      const icon = await renderTrayIcon({
        percent: secondary.percentUsed,
        bg: trayColorFor(secondary.percentUsed, COLOR.weekly),
        fg: COLOR.fg,
        mark: secondary.percentUsed >= 99 ? 'X' : null,
      });
      weeklyTray.setImage(icon);
      weeklyTray.setToolTip(`${secondary.label}: ${Math.round(secondary.percentUsed)}% used`);
    } else if (weeklyTray) {
      weeklyTray.setImage(nativeImage.createEmpty());
    }
  } catch {
    // Icon rendering is best-effort; ignore failures.
  }
}

// ── Main window ──────────────────────────────────────────────────────────────
function appIcon() {
  const file =
    process.platform === 'darwin'
      ? 'icon.png'
      : process.platform === 'linux'
        ? 'logo.png'
        : 'icon.ico';
  return path.join(__dirname, 'assets', file);
}

function createMainWindow() {
  const settings = getSettings();
  const compact = settings.compactMode;
  const saved = store.get('windowPosition');

  mainWindow = new BrowserWindow({
    width: compact ? COMPACT_WIDTH : WIDGET_WIDTH,
    height: compact ? COMPACT_HEIGHT : WIDGET_HEIGHT,
    x: saved ? saved.x : undefined,
    y: saved ? saved.y : undefined,
    frame: false,
    transparent: true,
    alwaysOnTop: !!settings.alwaysOnTop,
    resizable: false,
    skipTaskbar: !!settings.minimizeToTray,
    fullscreenable: false,
    maximizable: false,
    icon: appIcon(),
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js'),
    },
  });

  mainWindow.loadFile('src/renderer/index.html');
  if (settings.alwaysOnTop) mainWindow.setAlwaysOnTop(true, 'floating');

  mainWindow.on('moved', () => {
    if (!mainWindow || mainWindow.isDestroyed()) return;
    const [x, y] = mainWindow.getPosition();
    store.set('windowPosition', { x, y });
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });

  if (alwaysOnTopTimer) clearInterval(alwaysOnTopTimer);
  alwaysOnTopTimer = setInterval(() => {
    if (mainWindow && !mainWindow.isDestroyed() && getSettings().alwaysOnTop) {
      mainWindow.setAlwaysOnTop(true, 'floating');
    }
  }, 5000);
}

// ── Update check (manual, notification-only — same as upstream) ──────────────
function parseVersion(v) {
  const m = String(v || '').trim().replace(/^v/i, '').split('-')[0];
  return m.split('.').map((n) => parseInt(n, 10) || 0);
}

function isNewerVersion(local, remote) {
  const a = parseVersion(remote);
  const b = parseVersion(local);
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    if ((a[i] || 0) > (b[i] || 0)) return true;
    if ((a[i] || 0) < (b[i] || 0)) return false;
  }
  return false;
}

function checkForUpdate() {
  return new Promise((resolve) => {
    const req = https.request(
      {
        hostname: 'api.github.com',
        path: `/repos/${GITHUB_OWNER}/${GITHUB_REPO}/releases/latest`,
        method: 'GET',
        headers: {
          'User-Agent': 'copilot-usage-widget',
          Accept: 'application/vnd.github+json',
        },
        timeout: 5000,
      },
      (res) => {
        let data = '';
        res.on('data', (c) => (data += c));
        res.on('end', () => {
          try {
            const json = JSON.parse(data);
            if (json.draft || json.prerelease || !json.tag_name) {
              return resolve({ updateAvailable: false });
            }
            const latest = String(json.tag_name).replace(/^v/i, '');
            resolve({
              updateAvailable: isNewerVersion(app.getVersion(), latest),
              latestVersion: latest,
              url: json.html_url || `${REPO_URL}/releases`,
            });
          } catch {
            resolve({ updateAvailable: false });
          }
        });
      }
    );
    req.on('timeout', () => {
      req.destroy();
      resolve({ updateAvailable: false });
    });
    req.on('error', () => resolve({ updateAvailable: false }));
    req.end();
  });
}

// ── IPC ──────────────────────────────────────────────────────────────────────
function registerIpc() {
  ipcMain.handle('get-credentials', () => ({ hasToken: hasToken() }));

  ipcMain.handle('detect-credentials', async () => {
    const token = await detectToken();
    if (!token) return { success: false, error: 'GitHub CLI not found or not logged in' };
    const result = await validateToken(token);
    if (!result.valid) return { success: false, error: result.error };
    saveToken(token);
    return { success: true };
  });

  ipcMain.handle('save-credentials', async (_e, token) => {
    const result = await validateToken(token);
    if (!result.valid) return { success: false, error: result.error };
    saveToken(token.trim());
    return { success: true };
  });

  ipcMain.handle('delete-credentials', () => {
    clearToken();
    return { success: true };
  });

  ipcMain.handle('fetch-usage-data', async () => {
    const token = loadToken();
    if (!token) throw new Error('Unauthorized: no token stored');
    const usage = await fetchUsage(token);
    pushHistory(usage);
    maybeNotify(usage);
    updateTrays(usage);
    return usage;
  });

  ipcMain.handle('get-usage-history', () => store.get('history') || []);

  ipcMain.handle('get-settings', () => getSettings());
  ipcMain.handle('save-settings', (_e, partial) => saveSettings(partial || {}));

  ipcMain.handle('get-window-position', () => {
    if (!mainWindow) return null;
    const [x, y] = mainWindow.getPosition();
    return { x, y };
  });
  ipcMain.on('set-window-position', (_e, pos) => {
    if (mainWindow && pos) mainWindow.setPosition(Math.round(pos.x), Math.round(pos.y));
  });

  ipcMain.on('minimize-window', () => mainWindow && mainWindow.minimize());
  ipcMain.on('close-window', () => {
    if (getSettings().minimizeToTray) {
      mainWindow && mainWindow.hide();
    } else {
      app.quit();
    }
  });

  ipcMain.handle('set-compact-mode', (_e, compact) => {
    saveSettings({ compactMode: !!compact });
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.setSize(
        compact ? COMPACT_WIDTH : WIDGET_WIDTH,
        compact ? COMPACT_HEIGHT : WIDGET_HEIGHT
      );
    }
    return { success: true };
  });

  ipcMain.on('resize-window', (_e, size) => {
    if (mainWindow && size) {
      mainWindow.setSize(Math.round(size.width), Math.round(size.height));
    }
  });

  ipcMain.handle('open-external', (_e, url) => {
    if (typeof url === 'string' && /^https:\/\//i.test(url)) shell.openExternal(url);
    return { success: true };
  });

  ipcMain.handle('check-for-update', () => checkForUpdate());
  ipcMain.handle('get-app-version', () => app.getVersion());

  ipcMain.handle('show-notification', (_e, { title, body }) => {
    if (getSettings().usageAlerts) {
      new Notification({ title: title || 'Copilot Usage', body: body || '' }).show();
    }
    return { success: true };
  });
}

// ── App lifecycle ────────────────────────────────────────────────────────────
const gotTheLock = app.requestSingleInstanceLock();
if (!gotTheLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.show();
      mainWindow.focus();
    }
  });

  app.whenReady().then(() => {
    registerIpc();
    createTrays();
    createMainWindow();
    applySettings(getSettings());

    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) createMainWindow();
    });
  });

  app.on('window-all-closed', () => {
    // Tray-resident app: only quit on macOS when explicitly asked.
    if (process.platform !== 'darwin') {
      // Keep running in tray unless the user chose to quit via tray/Exit.
    }
  });

  app.on('before-quit', () => {
    if (alwaysOnTopTimer) clearInterval(alwaysOnTopTimer);
    destroyTrayRenderer();
  });
}
