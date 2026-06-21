# Plan — v2.0.0: Electron rewrite (mirror of `SlavomirDurej/claude-usage-widget`, for Copilot)

**Branch:** `claude/electron-rewrite-v2`
**Goal:** Replace the Python/Tk widget with a full Electron desktop widget that copies
`SlavomirDurej/claude-usage-widget` in design and features, but surfaces **GitHub Copilot**
premium-request usage instead of Claude.ai usage. Cross-platform (Win/macOS/Linux) with an
electron-builder + GitHub Actions release pipeline.

## Source-of-truth mapping

| Claude widget (source) | Copilot widget (this repo) |
|---|---|
| Data: `claude.ai/api/.../usage` via hidden BrowserWindow (Cloudflare hack) | Data: `GET https://api.github.com/copilot_internal/user` via plain `https` in main |
| Auth: `sessionKey` cookie captured from login BrowserWindow | Auth: GitHub token — auto-detect via `gh auth token`, or manual paste; stored with `safeStorage` |
| Metrics: `five_hour` (session) + `seven_day` (weekly) + per-model rows | Metrics: `quota_snapshots{}` limited entries (e.g. `premium_interactions`) + `quota_reset_date_utc` |
| Update check: `SlavomirDurej/claude-usage-widget` releases | Update check: `orty/copilot-usage-widget` releases |

Everything else (frameless/transparent/always-on-top window, contextIsolation + preload
allowlist, electron-store + safeStorage, dual dynamic tray %, compact/expanded modes,
Chart.js history graph, renderer-driven refresh loop, manual update banner, 3-OS
electron-builder + Actions pipeline, settings surface) is copied verbatim and is
provider-agnostic.

## Copilot data model (from existing `widget.pyw`, verified)

`GET https://api.github.com/copilot_internal/user`, headers `Authorization: Bearer <token>`,
`Accept: application/json`. Response:

```jsonc
{
  "quota_snapshots": {
    "premium_interactions": {
      "unlimited": false, "percent_remaining": 42.0,
      "entitlement": 300, "remaining": 126,
      "overage_count": 0, "overage_permitted": false
    }
    // possibly: chat, completions (often "unlimited": true → skipped)
  },
  "quota_reset_date_utc": "2026-07-01T00:00:00.000Z"
}
```

`percent_used = 100 - percent_remaining`. Skip `unlimited` snapshots. Color thresholds
75% (warn) / 90% (danger). Notify at 75/90/95/100% once per reset period.

## Tasks

1. **Scaffold & cleanup**
   - Remove Python impl: `src/widget.pyw`, `scripts/build.ps1`, `installer/`, `requirements*.txt`, `tests/*.py`, old `.github/workflows/{release,tests}.yml`.
   - Add `package.json` (electron 28+, electron-builder, electron-store, chart.js; build config copied & re-branded to `com.copilotusage.widget` / `Copilot-Usage-Widget`).
2. **Main process** `main.js` — frameless/transparent/always-on-top window, single-instance lock, dual dynamic-% trays, login-item auto-start, full IPC surface, manual update check, settings via electron-store, token via safeStorage.
3. **Preload** `preload.js` — `contextBridge` `electronAPI` with GitHub external-domain allowlist.
4. **Copilot API module** `src/copilot-api.js` — `https` GET, parse `quota_snapshots` → metric array, error/auth-failure classification (`Unauthorized`/`SessionExpired`).
5. **Auth module** `src/auth.js` — `gh auth token` detection + manual token validation against the API.
6. **Renderer** `src/renderer/{index.html,styles.css,app.js}` — copied DOM/CSS design system (dark `#1e1e2e`, purple/blue gradient bars, serif headings), login step1/step2, main + compact + settings views, Chart.js history, threshold coloring, circular reset timer, update banner.
7. **Assets** — generate `logo.png`, `icon.png` (1024), tray base PNGs (win/mac/linux) via Pillow; reuse `assets/icon.ico`; `copilot-logo.svg`; `build/entitlements.mac.plist`.
8. **CI/CD** `.github/workflows/{build-windows,build-macos,build-linux}.yml` — electron-builder per OS, tag-triggered GitHub Release via `softprops/action-gh-release`, optional macOS signing/notarization via secrets, Windows/Linux unsigned (documented).
9. **Docs** — rewrite `README.md` for the Electron app; bump version to `2.0.0`.
10. **Verify** — `npm install`, `node --check` all JS, electron-builder config dry-run; commit & push.

## Decisions / deviations

- **No Cloudflare hidden-window hack** — GitHub's API is a real authenticated REST endpoint, so main does a direct `https` GET. Simpler and more robust than the Claude path.
- **Auth via GitHub CLI token (auto) + manual paste (fallback)** instead of cookie capture; device-flow OAuth omitted (needs a registered client_id we can't ship). Documented in README.
- **Quota-driven bars**: render every *limited* `quota_snapshot` as a bar (primary = `premium_interactions`). Two-tray design shows the first two limited quotas; trays collapse to one if only one exists.
- **Default refresh 180s** (Copilot heritage), selectable 30/60/120/180/300s.
- Neither v1 nor v2 is Windows/Linux code-signed (same as the upstream Claude widget); macOS signing wired but optional via CI secrets.
