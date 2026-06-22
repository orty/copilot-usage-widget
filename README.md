# Copilot Usage Widget

Windows 10/11 taskbar widget that monitors your GitHub Copilot Enterprise premium interaction credits — monthly limit, remaining count, and reset countdown — in a compact always-on-top display.

Inspired by [claude-usage-widget](https://github.com/niccolo-sabato/claude-usage-widget).

## Requirements

- Windows 10/11
- GitHub Copilot Enterprise seat
- [GitHub CLI](https://cli.github.com) (`gh`) — recommended for zero-config auth  
  **or** a GitHub Personal Access Token (PAT) — works without `gh` installed

## Installation

1. Download `CopilotUsage-Setup.exe` from [Releases](../../releases)
2. Run the installer (no admin required)
3. Widget launches automatically

## Authentication

The widget needs a GitHub token to call the Copilot usage API. Two options:

---

### Option A — GitHub CLI (recommended, zero-config)

1. Install [GitHub CLI](https://cli.github.com)
2. Run once in a terminal:

   ```powershell
   gh auth login
   ```

   Complete the browser flow. The widget picks up the token automatically on next launch — no further configuration needed.

> **Note:** if the widget launched *before* you ran `gh auth login`, right-click the widget and choose **Re-authenticate**, or simply restart it.

---

### Option B — Manual PAT (no GitHub CLI required)

Use this if your machine has no `gh` CLI, or if you prefer a token you control explicitly.

#### 1 — Create a no-expiry PAT

1. Go to **GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)**
2. Click **Generate new token (classic)**
3. Name: `Copilot Usage Widget` (or anything you like)
4. Expiration: **No expiration**
5. Scopes — check **`copilot`** (grants read access to your Copilot quota)
6. Click **Generate token** and **copy it immediately** — GitHub shows it only once

#### 2 — Write the token to config.json

Open (or create) the config file at:

```text
%LOCALAPPDATA%\Copilot Usage\config.json
```

Paste your token as `oauth_token`:

```json
{
  "oauth_token": "ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
}
```

Save the file. If the widget is already running, right-click → **Refresh** to pick up the new token.

> The file may not exist yet on first install. Create it manually: open `%LOCALAPPDATA%\Copilot Usage\` in Explorer (create the folder if missing) and save the JSON above.

---

## Display

| Color | Meaning |
| --- | --- |
| Blue | < 75% of monthly credits used |
| Yellow | 75–89% used |
| Red | ≥ 90% used |
| Yellow | 75–89% used |
| Red | ≥ 90% used |

Right-click the widget for mode toggle (essential / standard), manual refresh, notifications, and quit.

## Troubleshooting

### Widget shows "not responding" on launch

**Cause:** `gh` is installed but not logged in. The widget tries to authenticate via `gh auth login --web` in the background, which can take up to 5 minutes to time out while the UI appears frozen.

**Fix (immediate):** Run `gh auth login` in a terminal before launching the widget, or use the manual PAT option (Option B above) to bypass `gh` entirely.

**Fix (permanent):** Update to v2.0.5+ — the auth call was moved off the UI thread so the widget stays responsive regardless of `gh` state.

### Widget shows "Check gh auth" in title bar

The token is invalid, expired, or missing the `copilot` scope. Re-authenticate:

- **GitHub CLI:** run `gh auth login` then right-click → **Re-authenticate**
- **PAT:** generate a new token with the `copilot` scope and update `config.json`

### Widget does not appear / hides behind taskbar

Right-click the system tray or re-launch. The widget restores to its last saved position. If the saved position is off-screen (e.g. after a monitor layout change), delete `window_x` and `window_y` from `config.json` — the widget will re-anchor to the bottom-right corner.

## Build From Source

Requires Python 3.11+, PyInstaller, Inno Setup 6+.

```powershell
.\scripts\build.ps1
```

## Privacy

No data is sent anywhere except `https://api.github.com/copilot_internal/user`. Your OAuth token is stored locally at `%LOCALAPPDATA%\Copilot Usage\config.json` and never leaves your machine.
