# Copilot Usage Widget

A small, frameless desktop widget that shows your **GitHub Copilot** premium‑request usage
in real time — always on top, out of your way, colour‑coded as you approach your limit.

> Cross‑platform Electron app (Windows / macOS / Linux). v2.0.0 is a full rewrite,
> inspired by [`SlavomirDurej/claude-usage-widget`](https://github.com/SlavomirDurej/claude-usage-widget)
> and re‑skinned for Copilot.

![widget](assets/logo.png)

## Features

- **Live quota bars** for your limited Copilot quotas (e.g. premium interactions), with a
  per‑quota reset countdown and circular timer.
- **Colour‑coded** thresholds — purple/blue normal, amber at the warn threshold, red at danger.
- **Dynamic tray icons** that bake the usage percentage into the tray (optional).
- **Compact mode** — a slim two‑bar strip you can park anywhere.
- **History graph** (Chart.js) of usage over the last ~8 days.
- **Desktop notifications** at 75 / 90 / 95 / 100 %.
- **Always‑on‑top**, frameless, draggable; remembers its position.
- **Launch at startup**, minimise‑to‑tray, light/dark/system themes, configurable refresh.
- **Update banner** when a newer release is published.

## How it gets your data

The widget calls GitHub's authenticated endpoint from the main process:

```
GET https://api.github.com/copilot_internal/user
Authorization: Bearer <your token>
```

It reads the `quota_snapshots` (skipping unlimited ones) and `quota_reset_date_utc`. No data
leaves your machine except that request to GitHub — the renderer has `connect-src 'none'`
and never touches the network itself.

## Authentication

Two ways to connect, surfaced in the login screen:

1. **Detect via GitHub CLI** — if you have [`gh`](https://cli.github.com) installed and are
   logged in, the widget lifts your token from `gh auth token`.
2. **Paste a token manually** — any GitHub token with Copilot access (the value of
   `gh auth token`, or a fine‑grained/classic PAT).

The token is stored locally, encrypted with the OS keychain via Electron's `safeStorage`
(plaintext fallback only if encryption is unavailable).

## Develop

```bash
npm install
npm start        # or: npm run dev
```

## Build installers

```bash
npm run build:win     # NSIS Setup + portable .exe   → dist/
npm run build:mac     # DMG (arm64 + x64)            → dist/
npm run build:linux   # AppImage (x64 + arm64)       → dist/
```

Releases are produced automatically by GitHub Actions when a `v*` tag is pushed
(`.github/workflows/build-{windows,macos,linux}.yml`) and attached to a GitHub Release.

### Code signing

Windows and Linux artifacts are **unsigned** (same as the upstream Claude widget), so Windows
SmartScreen will show an "unknown publisher" prompt until the binary earns download reputation.
macOS signing + notarization is wired up and activates automatically if these repo secrets are
present: `CSC_LINK`, `CSC_KEY_PASSWORD`, `APPLE_ID`, `APPLE_APP_SPECIFIC_PASSWORD`,
`APPLE_TEAM_ID`. Without them the macOS build still completes, unsigned.

## Settings

Launch at startup · hide from taskbar · always on top · usage alerts · history graph ·
show % in tray · theme · refresh interval (30s–5m) · warn % · danger % · time format.

---

*Unofficial tool — not affiliated with GitHub or Microsoft.* MIT licensed.
