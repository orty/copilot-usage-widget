'use strict';

/* Renderer logic for the Copilot Usage widget.
   All network I/O happens in main (CSP connect-src 'none'); this file only renders
   data, drives the refresh loop, and manages the login/settings UI. */

const api = window.electronAPI;

const els = {};
let settings = { ...{} };
let updateTimer = null;
let isFetching = false;
let chart = null;

const TIMER_CIRCUMFERENCE = 50.26; // 2πr, r = 8

function $(id) {
  return document.getElementById(id);
}

function show(view) {
  ['loadingContainer', 'loginContainer', 'noUsageContainer', 'mainContent', 'compactContent'].forEach(
    (id) => {
      const el = $(id);
      if (el) el.style.display = 'none';
    }
  );
  const el = $(view);
  if (el) el.style.display = view === 'compactContent' ? 'flex' : view === 'mainContent' ? 'block' : 'flex';
}

// ── Formatting ────────────────────────────────────────────────────────────────
function fmtCountdown(iso) {
  if (!iso) return '—';
  const reset = new Date(iso.replace('Z', '+00:00'));
  const delta = reset.getTime() - Date.now();
  if (delta <= 0) return 'now';
  const mins = Math.floor(delta / 60000);
  const d = Math.floor(mins / 1440);
  const h = Math.floor((mins % 1440) / 60);
  const m = mins % 60;
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

function statusClass(pct, base) {
  if (pct >= (settings.dangerThreshold || 90)) return 'danger';
  if (pct >= (settings.warnThreshold || 75)) return 'warning';
  return base;
}

// ── Rendering ─────────────────────────────────────────────────────────────────
function renderMetricRow(metric, index) {
  const base = index === 0 ? '' : 'weekly';
  const cls = statusClass(metric.percentUsed, base);
  const pct = Math.round(metric.percentUsed);
  const remainingPortion = Math.max(0, 1 - metric.percentUsed / 100);
  const dashOffset = TIMER_CIRCUMFERENCE * (1 - remainingPortion);

  const row = document.createElement('div');
  row.className = 'metric-row';
  row.innerHTML = `
    <span class="metric-name">${metric.label}</span>
    <div class="bar-wrap">
      <div class="progress-bar"><div class="progress-fill ${cls}" style="width:${pct}%"></div></div>
      <span class="usage-percentage">${pct}%</span>
    </div>
    <span class="metric-remaining">${metric.remaining}${
      metric.overageCount ? ` (+${metric.overageCount})` : ''
    }</span>
    <span class="metric-resets">${fmtCountdown(metric.resetsAt)}</span>
    <svg class="mini-timer" viewBox="0 0 18 18">
      <circle class="track" cx="9" cy="9" r="8"></circle>
      <circle class="prog" cx="9" cy="9" r="8" style="stroke-dashoffset:${dashOffset}"></circle>
    </svg>`;
  return row;
}

function renderExtraRow(metric) {
  const cls = statusClass(metric.percentUsed, '');
  const pct = Math.round(metric.percentUsed);
  const row = document.createElement('div');
  row.className = 'extra-row';
  row.innerHTML = `
    <span style="width:90px">${metric.label}</span>
    <div class="progress-bar"><div class="progress-fill ${cls}" style="width:${pct}%"></div></div>
    <span class="usage-percentage">${pct}%</span>`;
  return row;
}

function updateCompact(metrics) {
  const m1 = metrics[0];
  const m2 = metrics[1];
  if (m1) {
    $('compactLabel1').textContent = m1.label;
    const f1 = $('compactFill1');
    f1.style.width = `${Math.round(m1.percentUsed)}%`;
    f1.className = `compact-bar-fill ${statusClass(m1.percentUsed, '')}`;
    $('compactPct1').textContent = `${Math.round(m1.percentUsed)}%`;
  }
  if (m2) {
    $('compactRow2').style.display = 'flex';
    $('compactLabel2').textContent = m2.label;
    const f2 = $('compactFill2');
    f2.style.width = `${Math.round(m2.percentUsed)}%`;
    f2.className = `compact-bar-fill weekly ${statusClass(m2.percentUsed, '')}`;
    $('compactPct2').textContent = `${Math.round(m2.percentUsed)}%`;
  } else {
    $('compactRow2').style.display = 'none';
  }
}

function updateUI(usage) {
  if (!usage || !usage.metrics || usage.metrics.length === 0) {
    show('noUsageContainer');
    return;
  }
  const metrics = usage.metrics;

  if (settings.compactMode) {
    show('compactContent');
    updateCompact(metrics);
    return;
  }

  show('mainContent');
  // Primary metrics (first two) as full rows.
  const primary = metrics.slice(0, 2);
  const container = $('metricRows');
  container.innerHTML = '';
  primary.forEach((m, i) => container.appendChild(renderMetricRow(m, i)));

  // Expand section: any beyond the first two.
  const extras = metrics.slice(2);
  if (extras.length) {
    $('expandToggle').style.display = 'block';
    const extraEl = $('extraRows');
    extraEl.innerHTML = '';
    extras.forEach((m) => extraEl.appendChild(renderExtraRow(m)));
  } else {
    $('expandToggle').style.display = 'none';
    $('expandSection').style.display = 'none';
  }

  if (settings.graphVisible) {
    $('graphSection').style.display = 'block';
    renderChart();
  } else {
    $('graphSection').style.display = 'none';
  }
}

// ── Chart ───────────────────────────────────────────────────────────────────
async function renderChart() {
  if (typeof Chart === 'undefined') return;
  const history = await api.getUsageHistory();
  if (!history || !history.length) return;

  // Collect series per metric id.
  const ids = new Set();
  history.forEach((s) => Object.keys(s.m || {}).forEach((id) => ids.add(id)));
  const palette = ['#a78bfa', '#60a5fa', '#34d399', '#fbbf24', '#f87171'];
  const datasets = [...ids].map((id, i) => ({
    label: id,
    data: history.map((s) => ({ x: s.t, y: s.m[id] ?? null })),
    borderColor: palette[i % palette.length],
    backgroundColor: 'transparent',
    borderWidth: 1.5,
    pointRadius: 0,
    tension: 0.3,
    spanGaps: true,
  }));

  const cfg = {
    type: 'line',
    data: { datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      plugins: { legend: { display: false } },
      scales: {
        x: {
          type: 'linear',
          ticks: { display: false },
          grid: { color: 'rgba(255,255,255,0.05)' },
        },
        y: {
          min: 0,
          max: 100,
          ticks: {
            color: '#a0a0a0',
            font: { size: 8 },
            callback: (v) => `${v}%`,
          },
          grid: { color: 'rgba(255,255,255,0.05)' },
        },
      },
    },
  };

  if (chart) {
    chart.data = cfg.data;
    chart.update('none');
  } else {
    chart = new Chart($('usageChart').getContext('2d'), cfg);
  }
}

// ── Fetch loop ────────────────────────────────────────────────────────────────
async function fetchUsageData() {
  if (isFetching) return;
  const creds = await api.getCredentials();
  if (!creds.hasToken) {
    showLogin();
    return;
  }
  isFetching = true;
  els.refreshBtn.classList.add('spinning');
  try {
    const usage = await api.fetchUsageData();
    updateUI(usage);
  } catch (error) {
    const msg = String(error.message || error);
    if (/Unauthorized|SessionExpired/.test(msg)) {
      showLogin();
    }
  } finally {
    isFetching = false;
    els.refreshBtn.classList.remove('spinning');
  }
}

function startAutoUpdate() {
  stopAutoUpdate();
  const secs = parseInt(settings.refreshInterval, 10) || 180;
  updateTimer = setInterval(fetchUsageData, secs * 1000);
}
function stopAutoUpdate() {
  if (updateTimer) clearInterval(updateTimer);
  updateTimer = null;
}

// ── Login flow ──────────────────────────────────────────────────────────────
function showLogin() {
  stopAutoUpdate();
  show('loginContainer');
  $('loginStep1').style.display = 'flex';
  $('loginStep2').style.display = 'none';
}

async function afterLogin() {
  await fetchUsageData();
  startAutoUpdate();
}

// ── Settings UI ───────────────────────────────────────────────────────────────
function applyTheme() {
  let theme = settings.theme;
  if (theme === 'system') {
    theme = window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  }
  document.body.classList.toggle('light', theme === 'light');
}

function loadSettingsForm() {
  $('setAutoStart').checked = !!settings.autoStart;
  $('setMinimizeToTray').checked = !!settings.minimizeToTray;
  $('setAlwaysOnTop').checked = !!settings.alwaysOnTop;
  $('setUsageAlerts').checked = !!settings.usageAlerts;
  $('setGraphVisible').checked = !!settings.graphVisible;
  $('setShowTrayStats').checked = !!settings.showTrayStats;
  $('setTheme').value = settings.theme;
  $('setRefreshInterval').value = String(settings.refreshInterval);
  $('setWarnThreshold').value = settings.warnThreshold;
  $('setDangerThreshold').value = settings.dangerThreshold;
  $('setTimeFormat').value = settings.timeFormat;
}

async function persistSettings(partial) {
  settings = await api.saveSettings(partial);
  applyTheme();
}

function wireSettingsForm() {
  const bind = (id, key, type) =>
    $(id).addEventListener('change', async (e) => {
      const v =
        type === 'check' ? e.target.checked : type === 'num' ? parseInt(e.target.value, 10) : e.target.value;
      await persistSettings({ [key]: v });
      if (['graphVisible', 'compactMode', 'warnThreshold', 'dangerThreshold'].includes(key)) {
        fetchUsageData();
      }
      if (key === 'refreshInterval') startAutoUpdate();
    });

  bind('setAutoStart', 'autoStart', 'check');
  bind('setMinimizeToTray', 'minimizeToTray', 'check');
  bind('setAlwaysOnTop', 'alwaysOnTop', 'check');
  bind('setUsageAlerts', 'usageAlerts', 'check');
  bind('setGraphVisible', 'graphVisible', 'check');
  bind('setShowTrayStats', 'showTrayStats', 'check');
  bind('setTheme', 'theme', 'str');
  bind('setRefreshInterval', 'refreshInterval', 'str');
  bind('setWarnThreshold', 'warnThreshold', 'num');
  bind('setDangerThreshold', 'dangerThreshold', 'num');
  bind('setTimeFormat', 'timeFormat', 'str');
}

// ── Update banner ─────────────────────────────────────────────────────────────
async function checkUpdate() {
  try {
    const res = await api.checkForUpdate();
    if (res && res.updateAvailable) {
      $('updateText').textContent = `Update available: v${res.latestVersion}`;
      $('updateBanner').style.display = 'flex';
      $('updateLink').onclick = () => api.openExternal(res.url);
    }
  } catch {
    /* ignore */
  }
}

// ── Wire up ───────────────────────────────────────────────────────────────────
function cacheEls() {
  els.refreshBtn = $('refreshBtn');
}

function wireControls() {
  $('refreshBtn').onclick = fetchUsageData;
  $('minimizeBtn').onclick = () => api.minimizeWindow();
  $('closeBtn').onclick = () => api.closeWindow();
  $('settingsBtn').onclick = () => {
    loadSettingsForm();
    $('versionLabel').textContent = '';
    api.getAppVersion().then((v) => ($('versionLabel').textContent = `v${v}`));
    $('settingsOverlay').style.display = 'flex';
  };
  $('settingsClose').onclick = () => ($('settingsOverlay').style.display = 'none');

  $('compactBtn').onclick = async () => {
    const next = !settings.compactMode;
    await api.setCompactMode(next);
    settings.compactMode = next;
    fetchUsageData();
  };

  $('expandToggle').onclick = () => {
    const sec = $('expandSection');
    const open = sec.style.display !== 'block';
    sec.style.display = open ? 'block' : 'none';
    $('expandToggle').classList.toggle('open', open);
    persistSettings({ expandedOpen: open });
  };

  // Login step controls
  $('detectBtn').onclick = async () => {
    $('loginError').textContent = 'Checking GitHub CLI…';
    const res = await api.detectCredentials();
    if (res.success) {
      $('loginError').textContent = '';
      afterLogin();
    } else {
      $('loginError').textContent = res.error || 'Could not detect a token.';
    }
  };
  $('manualBtn').onclick = () => {
    $('loginStep1').style.display = 'none';
    $('loginStep2').style.display = 'flex';
  };
  $('backBtn').onclick = () => {
    $('loginStep2').style.display = 'none';
    $('loginStep1').style.display = 'flex';
  };
  $('saveTokenBtn').onclick = async () => {
    const token = $('tokenInput').value.trim();
    if (!token) return;
    $('loginError2').textContent = 'Validating…';
    const res = await api.saveCredentials(token);
    if (res.success) {
      $('tokenInput').value = '';
      $('loginError2').textContent = '';
      afterLogin();
    } else {
      $('loginError2').textContent = res.error || 'Invalid token.';
    }
  };

  // Settings footer
  $('openCopilot').onclick = () => api.openExternal('https://github.com/features/copilot');
  $('openRepo').onclick = () => api.openExternal('https://github.com/orty/copilot-usage-widget');
  $('logoutBtn').onclick = async () => {
    await api.deleteCredentials();
    $('settingsOverlay').style.display = 'none';
    showLogin();
  };

  // Compact quick-settings
  $('compactSettingsClose').onclick = () => ($('compactSettingsOverlay').style.display = 'none');
  $('csExpand').onclick = async () => {
    await api.setCompactMode(false);
    settings.compactMode = false;
    $('compactSettingsOverlay').style.display = 'none';
    fetchUsageData();
  };
}

async function init() {
  cacheEls();
  settings = await api.getSettings();
  applyTheme();
  wireControls();
  wireSettingsForm();

  api.onRefreshUsage(() => fetchUsageData());
  api.onSessionExpired(() => showLogin());

  show('loadingContainer');
  const creds = await api.getCredentials();
  if (!creds.hasToken) {
    showLogin();
  } else {
    await fetchUsageData();
    startAutoUpdate();
  }
  checkUpdate();
}

window.addEventListener('DOMContentLoaded', init);
