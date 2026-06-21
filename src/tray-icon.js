'use strict';

/**
 * Dynamic tray-icon renderer.
 *
 * The upstream Claude widget draws the live usage percentage onto its tray icons with a
 * hand-rolled bitmap font. We achieve the same "number baked into the tray icon" effect
 * the idiomatic Electron way: a tiny hidden BrowserWindow renders the icon on a <canvas>
 * and hands back a PNG data URL, which we wrap in a nativeImage. No native dependencies.
 */

const { BrowserWindow, nativeImage } = require('electron');

let renderWin = null;
let ready = null;

const RENDER_HTML = `data:text/html,${encodeURIComponent(`
<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>
<script>
function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}
window.__drawTrayIcon = function (opts) {
  const S = 32;
  const c = document.createElement('canvas');
  c.width = S; c.height = S;
  const x = c.getContext('2d');
  x.clearRect(0, 0, S, S);
  x.fillStyle = opts.bg;
  roundRect(x, 1, 1, S - 2, S - 2, 8);
  x.fill();
  const t = opts.mark || String(Math.round(opts.percent));
  x.fillStyle = opts.fg;
  x.textAlign = 'center';
  x.textBaseline = 'middle';
  x.font = 'bold ' + (t.length >= 3 ? 13 : 18) + 'px "Segoe UI", system-ui, sans-serif';
  x.fillText(t, S / 2, S / 2 + 1);
  return c.toDataURL('image/png');
};
</script>
</body></html>`)}`;

function ensureWindow() {
  if (ready) return ready;
  renderWin = new BrowserWindow({
    show: false,
    width: 64,
    height: 64,
    webPreferences: { nodeIntegration: false, contextIsolation: true },
  });
  ready = new Promise((resolve) => {
    renderWin.webContents.once('did-finish-load', () => resolve());
    renderWin.loadURL(RENDER_HTML);
  });
  return ready;
}

/**
 * @param {object} opts { percent:number, bg:string, fg:string, mark?:string }
 * @returns {Promise<Electron.NativeImage>}
 */
async function renderTrayIcon(opts) {
  await ensureWindow();
  const dataUrl = await renderWin.webContents.executeJavaScript(
    `window.__drawTrayIcon(${JSON.stringify(opts)})`
  );
  return nativeImage.createFromDataURL(dataUrl);
}

function destroyTrayRenderer() {
  if (renderWin && !renderWin.isDestroyed()) renderWin.destroy();
  renderWin = null;
  ready = null;
}

module.exports = { renderTrayIcon, destroyTrayRenderer };
