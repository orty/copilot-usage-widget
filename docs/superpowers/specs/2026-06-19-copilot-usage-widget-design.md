# Copilot Usage Widget — Design Spec
**Date:** 2026-06-19  
**Reference:** https://github.com/niccolo-sabato/claude-usage-widget  
**Status:** Approved

---

## Goal

Windows 11 taskbar widget that monitors GitHub Copilot Enterprise premium interaction credits in real time — monthly limit, consumed count, and reset countdown — with identical form factor and Win32 integration to the claude-usage-widget reference project.

---

## Architecture

Single-file application (`src/widget.pyw`) with minimal supporting assets. No modular split — scope does not warrant it.

```
copilot-usage-widget/
├── src/
│   └── widget.pyw          # entire application
├── installer/
│   └── setup.iss           # Inno Setup 6+ script
├── scripts/
│   └── build.ps1           # PyInstaller → Inno Setup pipeline
├── releases/               # CopilotUsage-Setup.exe output
└── docs/superpowers/specs/
    └── 2026-06-19-copilot-usage-widget-design.md
```

**Stack:**
- Python 3.11+
- tkinter (window/event loop)
- Pillow (anti-aliased pill bar rendering, 4× supersample)
- ctypes (Win32 API calls)
- `curl` bundled (avoids TLS fingerprint issues on GitHub endpoints)

**Runtime config:** `%LOCALAPPDATA%\Copilot Usage\config.json`  
Stores: OAuth token, refresh interval, window position, display mode.

**Packaging:** PyInstaller → single exe → Inno Setup installer (~15–20 MB).

---

## Data / API Layer

### Endpoint

```
GET https://api.github.com/copilot_internal/user
Authorization: Bearer <token>
```

This is the internal endpoint used by the GitHub Copilot VS Code extension. Confirmed via DevTools network capture.

### Auth Flow

1. Try `gh auth token` → use output as Bearer token
2. If `gh` not found or token returns 401 → GitHub OAuth device flow (opens browser, stores token in config)
3. On subsequent 401 → re-trigger device flow

### Response Schema (relevant fields)

```json
{
  "login": "...",
  "quota_reset_date_utc": "2026-07-01T00:00:00.000Z",
  "quota_snapshots": {
    "premium_interactions": {
      "entitlement": 5000,
      "remaining": 90,
      "percent_remaining": 1.8,
      "unlimited": false,
      "overage_count": 0,
      "overage_permitted": true
    },
    "chat": { "unlimited": true, ... },
    "completions": { "unlimited": true, ... }
  }
}
```

### Bar Discovery

Iterate `quota_snapshots`. Show a bar for each entry where `unlimited == false`. Currently yields one bar (`premium_interactions`). Future GitHub quotas are handled automatically.

### Derived Values

```
used        = entitlement - remaining
percent_used = 100 - percent_remaining
reset_in    = quota_reset_date_utc - now()
```

### Polling

- Default: 180 seconds
- Minimum: 10 seconds
- Maximum: 1 hour
- Immediate refresh when reset time is reached

---

## UI / Display

### Bar Anatomy

Each bar displays:
- **Label:** quota ID humanized (`premium_interactions` → `"Premium"`)
- **Pill progress bar:** filled proportional to `percent_used`, Pillow-rendered at 4× supersample
- **Count:** `"{remaining} remaining"` (e.g., `"90 remaining"`)
- **Reset countdown:** `"reset 2026-07-01 (11d 12h)"`
- **Overage badge:** shown only when `overage_count > 0` (e.g., `"+3 overage"`)

### Color Thresholds (by percent_used)

| Range | Color | Meaning |
|---|---|---|
| < 75% used | GitHub blue (`#0969da`) | Normal |
| 75–89% used | Yellow (`#d4a017`) | Warning |
| ≥ 90% used | Red (`#cf222e`) | Critical |

### Display Modes

**Essential mode** (primary):
- No title bar
- Compact single row, bars side by side
- Bottom edge anchored to taskbar
- Extra bars expand upward

**Standard mode**:
- Full title bar (`"Copilot Usage"`)
- Bars stacked vertically with labels
- Section dividers between bars

### Refresh Indicator

Pulsing dot (identical to reference). Cycles through opacity states between polls.

### Toast Notifications

Fired at 75%, 90%, 95%, 100% `percent_used` for the `premium_interactions` quota. One notification per threshold per billing period (suppressed until next reset).

---

## Win32 Integration (exact clone of reference)

| Feature | Implementation |
|---|---|
| No focus steal | `WS_EX_NOACTIVATE` extended style |
| Hidden from Alt+Tab / Win+Tab | `SetWindowLong` flags |
| Always on top | `HWND_TOPMOST`, re-asserted on focus events |
| Rounded corners (Win11) | `DwmSetWindowAttribute(DWMWA_WINDOW_CORNER_PREFERENCE)` |
| Taskbar icon progress overlay | `ITaskbarList3::SetProgressValue` |
| Taskbar anchoring | Read taskbar position via `SHAppBarMessage` |

---

## Error Handling

| Condition | Behavior |
|---|---|
| `gh` not found | Fall through to device flow immediately |
| 401 Unauthorized | Re-trigger OAuth device flow |
| Network timeout | Show last known data with stale indicator; retry next poll |
| Endpoint returns no quotas | Show "No quotas" placeholder; retry |
| `quota_snapshots` missing | Treat as empty; show connection error state |

---

## Testing

No automated test suite for the widget itself (UI-heavy, single file). Manual verification checklist:
- [ ] `gh auth token` path: token extracted, endpoint called, bar rendered
- [ ] Device flow path: browser opens, token stored, widget loads
- [ ] Essential mode: renders correctly at 100%, 125%, 150%, 200% DPI
- [ ] Standard mode: same DPI checks
- [ ] Color thresholds: inject mock data at 74%, 75%, 89%, 90%, 100% used
- [ ] Reset countdown: verify countdown decrements correctly
- [ ] Overage badge: appears when `overage_count > 0`
- [ ] Toast: fires at correct thresholds, suppressed on second poll at same threshold
- [ ] Win32: no focus steal, hidden from Alt+Tab, topmost, rounded corners on Win11

---

## Out of Scope

- Browser extension (auth handled via `gh` CLI / device flow)
- Auto-update mechanism (add after initial release)
- Localization (English only for v1)
- Mac/Linux support
- `chat` and `completions` bars (`unlimited: true` — no quota to display)
