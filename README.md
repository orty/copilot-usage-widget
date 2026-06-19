# Copilot Usage Widget

Windows 11 taskbar widget that monitors your GitHub Copilot Enterprise premium interaction credits — monthly limit, remaining count, and reset countdown — in a compact always-on-top display.

Inspired by [claude-usage-widget](https://github.com/niccolo-sabato/claude-usage-widget).

## Requirements

- Windows 10/11
- GitHub Copilot Enterprise seat
- [GitHub CLI](https://cli.github.com) (`gh`) — recommended for zero-config auth

## Installation

1. Download `CopilotUsage-Setup.exe` from [Releases](../../releases)
2. Run the installer (no admin required)
3. Widget launches automatically

**Auth:** The widget uses `gh auth token` on first run. If GitHub CLI is not installed or not logged in, a browser window opens for OAuth login.

## Display

| Color | Meaning |
| --- | --- |
| Blue | < 75% of monthly credits used |
| Yellow | 75–89% used |
| Red | ≥ 90% used |

Right-click the widget for mode toggle (essential / standard), manual refresh, and quit.

## Build From Source

Requires Python 3.11+, PyInstaller, Inno Setup 6+.

```powershell
.\scripts\build.ps1
```

## Privacy

No data is sent anywhere except `https://api.github.com/copilot_internal/user`. Your OAuth token is stored locally at `%LOCALAPPDATA%\Copilot Usage\config.json`.
