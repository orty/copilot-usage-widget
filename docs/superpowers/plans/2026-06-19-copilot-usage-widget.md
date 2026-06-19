# Copilot Usage Widget Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Windows 11 taskbar widget that monitors GitHub Copilot Enterprise premium interaction credits — monthly limit, remaining count, reset countdown — with identical form factor to claude-usage-widget.

**Architecture:** Single-file Python app (`src/widget.pyw`). Pure functions at module level are unit-tested via pytest (tkinter/Pillow mocked at import time). Win32/UI code runs only under `if __name__ == '__main__':`. curl used for HTTP to avoid TLS fingerprint issues.

**Tech Stack:** Python 3.11+ · tkinter · Pillow>=10.0 · ctypes · curl (bundled/system) · PyInstaller · Inno Setup 6+· pytest>=8.0

## Global Constraints

- Python 3.11+ required (uses `match`, `datetime.fromisoformat` with Z suffix)
- Windows 11 target; Win10 supported with square corners only
- `src/widget.pyw` is the single source file — no split into multiple modules
- Config: `%LOCALAPPDATA%\Copilot Usage\config.json`
- Endpoint: `https://api.github.com/copilot_internal/user`
- Auth primary: `gh auth token` (returns `gho_...` OAuth token)
- Auth fallback: invoke `gh auth login --web`, then retry `gh auth token`
- Polling: default 180s, min 10s, max 3600s
- Colors: `#0969da` (normal, <75% used) · `#d4a017` (warning, 75-89%) · `#cf222e` (critical, ≥90%)
- Label map: `{"premium_interactions": "Premium"}` — unknown IDs → title-case, underscores→spaces
- Toast thresholds: 75, 90, 95, 100 (once per billing period per quota)
- Pill bar rendered with Pillow at 4× supersample then downscaled
- Win32: `WS_EX_NOACTIVATE`, `WS_EX_TOOLWINDOW`, `HWND_TOPMOST`, `DwmSetWindowAttribute` rounded corners, `ITaskbarList3` progress overlay, `SHAppBarMessage` taskbar position

---

### Task 1: Project Scaffold

**Files:**

- Create: `src/widget.pyw`
- Create: `tests/conftest.py`
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `.gitignore`

**Interfaces:**

- Produces: `widget_module` pytest fixture (all test files use this to import pure functions from `widget.pyw`)

- [ ] **Step 1: Create `requirements.txt`**

```text
Pillow>=10.0
```

- [ ] **Step 2: Create `requirements-dev.txt`**

```text
pytest>=8.0
pytest-mock>=3.12
```

- [ ] **Step 3: Create `.gitignore`**

```text
__pycache__/
*.pyc
.pytest_cache/
dist/
build/
releases/
*.spec
```

- [ ] **Step 4: Create `src/widget.pyw` skeleton**

```python
"""Copilot Usage Widget — monitors GitHub Copilot Enterprise premium interaction credits."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── Constants ──────────────────────────────────────────────────────────────────
CONFIG_PATH = Path(os.environ.get("LOCALAPPDATA", ".")) / "Copilot Usage" / "config.json"
API_URL = "https://api.github.com/copilot_internal/user"
POLL_DEFAULT = 180
POLL_MIN = 10
POLL_MAX = 3600
TOAST_THRESHOLDS = [75, 90, 95, 100]
COLOR_NORMAL = "#0969da"
COLOR_WARNING = "#d4a017"
COLOR_CRITICAL = "#cf222e"
LABEL_MAP = {"premium_interactions": "Premium"}

# ── Guard — everything below this line only runs when launched directly ────────
if __name__ == "__main__":
    pass
```

- [ ] **Step 5: Create `tests/conftest.py`**

```python
"""Mock GUI modules before widget.pyw is imported to prevent display initialization."""
import sys
import importlib.util
import pathlib
from unittest.mock import MagicMock

for _mod in [
    "tkinter", "tkinter.ttk", "tkinter.font",
    "PIL", "PIL.Image", "PIL.ImageDraw", "PIL.ImageTk", "PIL.ImageFilter",
]:
    sys.modules[_mod] = MagicMock()

import pytest

_WIDGET_PATH = pathlib.Path(__file__).parent.parent / "src" / "widget.pyw"


@pytest.fixture(scope="session")
def W():
    """Load widget.pyw as a module (GUI mocked). All tests use this fixture."""
    spec = importlib.util.spec_from_file_location("widget", _WIDGET_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
```

- [ ] **Step 6: Install dev dependencies**

```bash
pip install -r requirements-dev.txt -r requirements.txt
```

Expected: packages install without error.

- [ ] **Step 7: Verify pytest runs cleanly**

```bash
pytest tests/ -v
```

Expected output: `no tests ran` (0 errors, 0 failures).

- [ ] **Step 8: Commit**

```bash
git add src/ tests/ requirements.txt requirements-dev.txt .gitignore
git commit -m "chore: project scaffold with test harness"
```

---

### Task 2: Config Manager

**Files:**

- Modify: `src/widget.pyw` — add `AppConfig`, `load_config()`, `save_config()`
- Create: `tests/test_config.py`

**Interfaces:**

- Produces:
  - `AppConfig` dataclass: fields `oauth_token: str`, `refresh_interval: int`, `window_x: int`, `window_y: int`, `display_mode: str`, `notified: dict`
  - `load_config() -> AppConfig` — reads `CONFIG_PATH`, returns defaults on missing/corrupt file
  - `save_config(config: AppConfig) -> None` — writes `CONFIG_PATH`, creates parent dirs

- [ ] **Step 1: Write failing tests**

Create `tests/test_config.py`:

```python
import json
import pytest
from pathlib import Path


def test_load_config_defaults(W, tmp_path, monkeypatch):
    monkeypatch.setattr(W, "CONFIG_PATH", tmp_path / "config.json")
    cfg = W.load_config()
    assert cfg.oauth_token == ""
    assert cfg.refresh_interval == W.POLL_DEFAULT
    assert cfg.display_mode == "essential"
    assert cfg.notified == {}


def test_load_config_reads_file(W, tmp_path, monkeypatch):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"oauth_token": "gho_abc", "refresh_interval": 60}))
    monkeypatch.setattr(W, "CONFIG_PATH", p)
    cfg = W.load_config()
    assert cfg.oauth_token == "gho_abc"
    assert cfg.refresh_interval == 60


def test_load_config_clamps_interval(W, tmp_path, monkeypatch):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"refresh_interval": 1}))
    monkeypatch.setattr(W, "CONFIG_PATH", p)
    cfg = W.load_config()
    assert cfg.refresh_interval == W.POLL_MIN


def test_load_config_corrupted_json(W, tmp_path, monkeypatch):
    p = tmp_path / "config.json"
    p.write_text("not json{{")
    monkeypatch.setattr(W, "CONFIG_PATH", p)
    cfg = W.load_config()
    assert cfg.oauth_token == ""


def test_save_config_roundtrip(W, tmp_path, monkeypatch):
    p = tmp_path / "config.json"
    monkeypatch.setattr(W, "CONFIG_PATH", p)
    cfg = W.AppConfig(oauth_token="gho_xyz", refresh_interval=30)
    W.save_config(cfg)
    raw = json.loads(p.read_text())
    assert raw["oauth_token"] == "gho_xyz"
    assert raw["refresh_interval"] == 30


def test_save_config_creates_parent_dirs(W, tmp_path, monkeypatch):
    p = tmp_path / "nested" / "deep" / "config.json"
    monkeypatch.setattr(W, "CONFIG_PATH", p)
    W.save_config(W.AppConfig())
    assert p.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_config.py -v
```

Expected: `AttributeError: module 'widget' has no attribute 'AppConfig'`

- [ ] **Step 3: Add `AppConfig`, `load_config`, `save_config` to `widget.pyw`**

Insert after the constants block (before the `if __name__ == "__main__":` guard):

```python
# ── Data classes ───────────────────────────────────────────────────────────────
@dataclass
class AppConfig:
    oauth_token: str = ""
    refresh_interval: int = POLL_DEFAULT
    window_x: int = -1
    window_y: int = -1
    display_mode: str = "essential"
    notified: dict = field(default_factory=dict)


# ── Config I/O ─────────────────────────────────────────────────────────────────
def load_config() -> AppConfig:
    try:
        raw = json.loads(CONFIG_PATH.read_text())
        return AppConfig(
            oauth_token=raw.get("oauth_token", ""),
            refresh_interval=max(POLL_MIN, min(POLL_MAX, raw.get("refresh_interval", POLL_DEFAULT))),
            window_x=raw.get("window_x", -1),
            window_y=raw.get("window_y", -1),
            display_mode=raw.get("display_mode", "essential"),
            notified=raw.get("notified", {}),
        )
    except (FileNotFoundError, json.JSONDecodeError):
        return AppConfig()


def save_config(config: AppConfig) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps({
        "oauth_token": config.oauth_token,
        "refresh_interval": config.refresh_interval,
        "window_x": config.window_x,
        "window_y": config.window_y,
        "display_mode": config.display_mode,
        "notified": config.notified,
    }, indent=2))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_config.py -v
```

Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add src/widget.pyw tests/test_config.py
git commit -m "feat: config manager with load/save and defaults"
```

---

### Task 3: Auth — `gh auth token` + Fallback

**Files:**

- Modify: `src/widget.pyw` — add `get_gh_token()`, `ensure_authenticated()`
- Create: `tests/test_auth.py`

**Interfaces:**

- Consumes: nothing from prior tasks
- Produces:
  - `get_gh_token() -> Optional[str]` — runs `gh auth token`, returns token string or `None`
  - `ensure_authenticated(config: AppConfig) -> str` — returns valid token or raises `RuntimeError`; side effect: may invoke `gh auth login --web` and update `config.oauth_token`

- [ ] **Step 1: Write failing tests**

Create `tests/test_auth.py`:

```python
import pytest
from unittest.mock import patch, MagicMock
import subprocess


def test_get_gh_token_success(W):
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "gho_testtoken123\n"
    with patch("subprocess.run", return_value=mock_result) as mock_run:
        token = W.get_gh_token()
    assert token == "gho_testtoken123"
    mock_run.assert_called_once_with(
        ["gh", "auth", "token"],
        capture_output=True, text=True, timeout=10
    )


def test_get_gh_token_gh_not_found(W):
    with patch("subprocess.run", side_effect=FileNotFoundError()):
        token = W.get_gh_token()
    assert token is None


def test_get_gh_token_empty_output(W):
    mock_result = MagicMock(returncode=0, stdout="  \n")
    with patch("subprocess.run", return_value=mock_result):
        token = W.get_gh_token()
    assert token is None


def test_get_gh_token_timeout(W):
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("gh", 10)):
        token = W.get_gh_token()
    assert token is None


def test_ensure_authenticated_uses_cached_token(W):
    cfg = W.AppConfig(oauth_token="gho_cached")
    with patch.object(W, "get_gh_token") as mock_gh:
        token = W.ensure_authenticated(cfg)
    assert token == "gho_cached"
    mock_gh.assert_not_called()


def test_ensure_authenticated_falls_back_to_gh_cli(W):
    cfg = W.AppConfig(oauth_token="")
    with patch.object(W, "get_gh_token", return_value="gho_from_cli"):
        token = W.ensure_authenticated(cfg)
    assert token == "gho_from_cli"
    assert cfg.oauth_token == "gho_from_cli"


def test_ensure_authenticated_invokes_gh_login_when_no_token(W):
    cfg = W.AppConfig(oauth_token="")
    with patch.object(W, "get_gh_token", return_value=None), \
         patch("subprocess.run") as mock_run, \
         patch.object(W, "get_gh_token", side_effect=[None, "gho_after_login"]):
        token = W.ensure_authenticated(cfg)
    assert token == "gho_after_login"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_auth.py -v
```

Expected: `AttributeError: module 'widget' has no attribute 'get_gh_token'`

- [ ] **Step 3: Add auth functions to `widget.pyw`**

Insert after the config I/O section:

```python
# ── Authentication ─────────────────────────────────────────────────────────────
def get_gh_token() -> Optional[str]:
    """Run `gh auth token` and return the token, or None on any failure."""
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True, text=True, timeout=10,
        )
        token = result.stdout.strip()
        return token if token else None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def ensure_authenticated(config: AppConfig) -> str:
    """Return a valid Bearer token. Updates config.oauth_token as side effect.

    Order: cached token → gh auth token → gh auth login --web + retry.
    Raises RuntimeError if all paths fail.
    """
    if config.oauth_token:
        return config.oauth_token

    token = get_gh_token()
    if token:
        config.oauth_token = token
        return token

    # gh is installed but not logged in — trigger device flow via gh CLI
    subprocess.run(["gh", "auth", "login", "--web"], check=False)
    token = get_gh_token()
    if token:
        config.oauth_token = token
        return token

    raise RuntimeError(
        "Could not obtain a GitHub token.\n"
        "Install GitHub CLI (https://cli.github.com) and run: gh auth login"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_auth.py -v
```

Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add src/widget.pyw tests/test_auth.py
git commit -m "feat: auth via gh CLI with gh auth login fallback"
```

---

### Task 4: API Client + QuotaBar Parsing

**Files:**

- Modify: `src/widget.pyw` — add `QuotaBar`, `fetch_user_data()`, `parse_quotas()`, `humanize_label()`
- Create: `tests/test_api.py`

**Interfaces:**

- Consumes: `ensure_authenticated(config)` from Task 3
- Produces:
  - `QuotaBar` dataclass: `id: str`, `label: str`, `entitlement: int`, `remaining: int`, `percent_used: float`, `overage_count: int`, `overage_permitted: bool`
  - `fetch_user_data(token: str) -> dict` — calls `API_URL` via curl, returns parsed JSON, raises `RuntimeError` on failure
  - `parse_quotas(data: dict) -> list[QuotaBar]` — extracts bars where `unlimited == False`
  - `humanize_label(quota_id: str) -> str` — uses `LABEL_MAP`, fallback to title-case

- [ ] **Step 1: Write failing tests**

Create `tests/test_api.py`:

```python
import json
import pytest
from unittest.mock import patch, MagicMock

SAMPLE_RESPONSE = {
    "login": "testuser",
    "quota_reset_date_utc": "2026-07-01T00:00:00.000Z",
    "quota_snapshots": {
        "premium_interactions": {
            "entitlement": 5000,
            "remaining": 90,
            "percent_remaining": 1.8,
            "unlimited": False,
            "overage_count": 3,
            "overage_permitted": True,
        },
        "chat": {
            "unlimited": True,
            "entitlement": 0,
            "remaining": 0,
            "percent_remaining": 100.0,
        },
        "completions": {
            "unlimited": True,
            "entitlement": 0,
            "remaining": 0,
            "percent_remaining": 100.0,
        },
    },
}


def test_parse_quotas_returns_only_limited(W):
    bars = W.parse_quotas(SAMPLE_RESPONSE)
    assert len(bars) == 1
    assert bars[0].id == "premium_interactions"


def test_parse_quotas_bar_fields(W):
    bar = W.parse_quotas(SAMPLE_RESPONSE)[0]
    assert bar.entitlement == 5000
    assert bar.remaining == 90
    assert abs(bar.percent_used - 98.2) < 0.1
    assert bar.overage_count == 3
    assert bar.overage_permitted is True
    assert bar.label == "Premium"


def test_parse_quotas_empty_snapshots(W):
    bars = W.parse_quotas({"quota_snapshots": {}})
    assert bars == []


def test_parse_quotas_missing_snapshots_key(W):
    bars = W.parse_quotas({})
    assert bars == []


def test_parse_quotas_all_unlimited(W):
    data = {"quota_snapshots": {"chat": {"unlimited": True}}}
    bars = W.parse_quotas(data)
    assert bars == []


def test_humanize_label_known(W):
    assert W.humanize_label("premium_interactions") == "Premium"


def test_humanize_label_unknown_falls_back_to_titlecase(W):
    assert W.humanize_label("some_new_quota") == "Some New Quota"


def test_fetch_user_data_success(W):
    mock_result = MagicMock(returncode=0, stdout=json.dumps(SAMPLE_RESPONSE).encode())
    with patch("subprocess.run", return_value=mock_result):
        data = W.fetch_user_data("gho_token")
    assert data["login"] == "testuser"


def test_fetch_user_data_curl_failure(W):
    mock_result = MagicMock(returncode=22, stderr=b"404 Not Found")
    with patch("subprocess.run", return_value=mock_result):
        with pytest.raises(RuntimeError, match="curl failed"):
            W.fetch_user_data("gho_bad_token")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_api.py -v
```

Expected: `AttributeError: module 'widget' has no attribute 'QuotaBar'`

- [ ] **Step 3: Add `QuotaBar`, `fetch_user_data`, `parse_quotas`, `humanize_label` to `widget.pyw`**

Insert after the constants block (before `AppConfig`):

```python
@dataclass
class QuotaBar:
    id: str
    label: str
    entitlement: int
    remaining: int
    percent_used: float
    overage_count: int
    overage_permitted: bool
```

Insert after the auth section:

```python
# ── API client ─────────────────────────────────────────────────────────────────
def humanize_label(quota_id: str) -> str:
    if quota_id in LABEL_MAP:
        return LABEL_MAP[quota_id]
    return quota_id.replace("_", " ").title()


def fetch_user_data(token: str) -> dict:
    result = subprocess.run(
        ["curl", "-s", "--fail",
         "-H", f"Authorization: Bearer {token}",
         "-H", "Accept: application/json",
         API_URL],
        capture_output=True, timeout=15,
    )
    if result.returncode != 0:
        raise RuntimeError(f"curl failed (exit {result.returncode}): {result.stderr.decode()}")
    return json.loads(result.stdout)


def parse_quotas(data: dict) -> list[QuotaBar]:
    bars = []
    for quota_id, snap in data.get("quota_snapshots", {}).items():
        if snap.get("unlimited", True):
            continue
        entitlement = snap.get("entitlement", 0)
        remaining = snap.get("remaining", 0)
        percent_used = 100.0 - snap.get("percent_remaining", 100.0)
        bars.append(QuotaBar(
            id=quota_id,
            label=humanize_label(quota_id),
            entitlement=entitlement,
            remaining=remaining,
            percent_used=percent_used,
            overage_count=snap.get("overage_count", 0),
            overage_permitted=snap.get("overage_permitted", False),
        ))
    return bars
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_api.py -v
```

Expected: `9 passed`

- [ ] **Step 5: Commit**

```bash
git add src/widget.pyw tests/test_api.py
git commit -m "feat: API client with QuotaBar parsing and label humanization"
```

---

### Task 5: Display Helpers — Color, Countdown, Stale Text

**Files:**

- Modify: `src/widget.pyw` — add `bar_color()`, `calc_reset_countdown()`, `format_bar_count()`
- Create: `tests/test_display.py`

**Interfaces:**

- Produces:
  - `bar_color(percent_used: float) -> str` — returns hex color string
  - `calc_reset_countdown(reset_date_utc: str) -> str` — e.g. `"11d 12h"`, `"45m"`, `"reset now"`
  - `format_bar_count(bar: QuotaBar) -> str` — e.g. `"90 remaining"` or `"90 remaining (+3 overage)"`

- [ ] **Step 1: Write failing tests**

Create `tests/test_display.py`:

```python
import pytest
from unittest.mock import patch
from datetime import datetime, timezone, timedelta


def test_bar_color_normal(W):
    assert W.bar_color(0.0) == W.COLOR_NORMAL
    assert W.bar_color(74.9) == W.COLOR_NORMAL


def test_bar_color_warning(W):
    assert W.bar_color(75.0) == W.COLOR_WARNING
    assert W.bar_color(89.9) == W.COLOR_WARNING


def test_bar_color_critical(W):
    assert W.bar_color(90.0) == W.COLOR_CRITICAL
    assert W.bar_color(100.0) == W.COLOR_CRITICAL


def test_calc_reset_countdown_days(W):
    future = (datetime.now(timezone.utc) + timedelta(days=11, hours=12)).isoformat()
    result = W.calc_reset_countdown(future)
    assert result == "11d 12h"


def test_calc_reset_countdown_hours(W):
    future = (datetime.now(timezone.utc) + timedelta(hours=3, minutes=45)).isoformat()
    result = W.calc_reset_countdown(future)
    assert result == "3h 45m"


def test_calc_reset_countdown_minutes(W):
    future = (datetime.now(timezone.utc) + timedelta(minutes=23)).isoformat()
    result = W.calc_reset_countdown(future)
    assert result == "23m"


def test_calc_reset_countdown_past(W):
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    assert W.calc_reset_countdown(past) == "reset now"


def test_calc_reset_countdown_z_suffix(W):
    # API returns Z suffix — must parse correctly
    future = "2099-01-01T00:00:00.000Z"
    result = W.calc_reset_countdown(future)
    assert "d" in result


def test_format_bar_count_no_overage(W):
    bar = W.QuotaBar("premium_interactions", "Premium", 5000, 90, 98.2, 0, True)
    assert W.format_bar_count(bar) == "90 remaining"


def test_format_bar_count_with_overage(W):
    bar = W.QuotaBar("premium_interactions", "Premium", 5000, 0, 100.0, 3, True)
    assert W.format_bar_count(bar) == "0 remaining (+3 overage)"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_display.py -v
```

Expected: `AttributeError: module 'widget' has no attribute 'bar_color'`

- [ ] **Step 3: Add display helpers to `widget.pyw`**

Insert after the API client section:

```python
# ── Display helpers ────────────────────────────────────────────────────────────
def bar_color(percent_used: float) -> str:
    if percent_used >= 90.0:
        return COLOR_CRITICAL
    if percent_used >= 75.0:
        return COLOR_WARNING
    return COLOR_NORMAL


def calc_reset_countdown(reset_date_utc: str) -> str:
    reset = datetime.fromisoformat(reset_date_utc.replace("Z", "+00:00"))
    delta = reset - datetime.now(timezone.utc)
    if delta.total_seconds() <= 0:
        return "reset now"
    total_minutes = int(delta.total_seconds() // 60)
    days = total_minutes // (60 * 24)
    hours = (total_minutes % (60 * 24)) // 60
    minutes = total_minutes % 60
    if days > 0:
        return f"{days}d {hours}h"
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def format_bar_count(bar: QuotaBar) -> str:
    base = f"{bar.remaining} remaining"
    if bar.overage_count > 0:
        return f"{base} (+{bar.overage_count} overage)"
    return base
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_display.py -v
```

Expected: `10 passed`

- [ ] **Step 5: Commit**

```bash
git add src/widget.pyw tests/test_display.py
git commit -m "feat: display helpers — color thresholds, reset countdown, bar count"
```

---

### Task 6: Notification Threshold Tracker

**Files:**

- Modify: `src/widget.pyw` — add `thresholds_to_fire()`, `record_notified()`
- Create: `tests/test_notify.py`

**Interfaces:**

- Consumes: `TOAST_THRESHOLDS` constant, `AppConfig.notified` dict
- Produces:
  - `thresholds_to_fire(quota_id: str, percent_used: float, notified: dict, reset_date_utc: str) -> list[int]` — returns thresholds not yet fired this billing period
  - `record_notified(notified: dict, quota_id: str, threshold: int, reset_date_utc: str) -> dict` — returns new notified dict with threshold marked

- [ ] **Step 1: Write failing tests**

Create `tests/test_notify.py`:

```python
import pytest


RESET = "2026-07-01T00:00:00.000Z"
PERIOD = "2026-07-01"


def test_thresholds_to_fire_none_yet(W):
    result = W.thresholds_to_fire("premium_interactions", 98.2, {}, RESET)
    assert result == [75, 90, 95]


def test_thresholds_to_fire_at_100(W):
    result = W.thresholds_to_fire("premium_interactions", 100.0, {}, RESET)
    assert result == [75, 90, 95, 100]


def test_thresholds_to_fire_already_fired(W):
    notified = {"premium_interactions": {PERIOD: [75, 90]}}
    result = W.thresholds_to_fire("premium_interactions", 98.2, notified, RESET)
    assert result == [95]


def test_thresholds_to_fire_below_all(W):
    result = W.thresholds_to_fire("premium_interactions", 50.0, {}, RESET)
    assert result == []


def test_thresholds_to_fire_different_quota(W):
    notified = {"other_quota": {PERIOD: [75]}}
    result = W.thresholds_to_fire("premium_interactions", 80.0, notified, RESET)
    assert result == [75]


def test_record_notified_adds_entry(W):
    updated = W.record_notified({}, "premium_interactions", 75, RESET)
    assert 75 in updated["premium_interactions"][PERIOD]


def test_record_notified_appends(W):
    notified = {"premium_interactions": {PERIOD: [75]}}
    updated = W.record_notified(notified, "premium_interactions", 90, RESET)
    assert updated["premium_interactions"][PERIOD] == [75, 90]


def test_record_notified_does_not_mutate_original(W):
    notified = {}
    W.record_notified(notified, "premium_interactions", 75, RESET)
    assert notified == {}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_notify.py -v
```

Expected: `AttributeError: module 'widget' has no attribute 'thresholds_to_fire'`

- [ ] **Step 3: Add notification functions to `widget.pyw`**

Insert after display helpers:

```python
# ── Notification tracker ───────────────────────────────────────────────────────
def thresholds_to_fire(
    quota_id: str, percent_used: float, notified: dict, reset_date_utc: str
) -> list[int]:
    period_key = reset_date_utc[:10]
    fired = notified.get(quota_id, {}).get(period_key, [])
    return [t for t in TOAST_THRESHOLDS if percent_used >= t and t not in fired]


def record_notified(
    notified: dict, quota_id: str, threshold: int, reset_date_utc: str
) -> dict:
    period_key = reset_date_utc[:10]
    updated = {k: {pk: list(pv) for pk, pv in v.items()} for k, v in notified.items()}
    updated.setdefault(quota_id, {}).setdefault(period_key, []).append(threshold)
    return updated
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_notify.py -v
```

Expected: `8 passed`

- [ ] **Step 5: Run full test suite**

```bash
pytest tests/ -v
```

Expected: `all tests pass` (config + auth + api + display + notify)

- [ ] **Step 6: Commit**

```bash
git add src/widget.pyw tests/test_notify.py
git commit -m "feat: notification threshold tracker — once-per-period suppression"
```

---

### Task 7: Pillow Pill Bar Renderer

**Files:**

- Modify: `src/widget.pyw` — add `render_pill_bar()`, `render_dot()`

**Interfaces:**

- Produces:
  - `render_pill_bar(width: int, height: int, percent_used: float, color: str, stale: bool = False) -> "PIL.ImageTk.PhotoImage"` — returns tkinter-compatible image
  - `render_dot(size: int, alpha: int) -> "PIL.ImageTk.PhotoImage"` — pulsing dot at given opacity (0-255)

Note: these functions import PIL at call time (PIL is mocked in tests, so rendering is not exercised by unit tests). Manual verification required.

- [ ] **Step 1: Add renderer functions to `widget.pyw`**

Insert after the notification tracker section (still before `if __name__ == "__main__":`):

```python
# ── Rendering (Pillow) ─────────────────────────────────────────────────────────
def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def render_pill_bar(
    width: int,
    height: int,
    percent_used: float,
    color: str,
    stale: bool = False,
) -> object:
    """Render an anti-aliased pill-shaped progress bar at 4× supersample."""
    from PIL import Image, ImageDraw, ImageTk

    scale = 4
    W, H = width * scale, height * scale
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    bg = (60, 60, 60, 255)
    fg = _hex_to_rgb(color) + (180 if stale else 255,)
    fill_w = int(W * max(0.0, min(1.0, percent_used / 100.0)))
    radius = H // 2

    # Background pill
    draw.rounded_rectangle([0, 0, W - 1, H - 1], radius=radius, fill=bg)
    # Filled portion
    if fill_w > 0:
        clip_img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        clip_draw = ImageDraw.Draw(clip_img)
        clip_draw.rounded_rectangle([0, 0, W - 1, H - 1], radius=radius, fill=fg)
        mask = Image.new("L", (W, H), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.rectangle([0, 0, fill_w, H], fill=255)
        img.paste(clip_img, mask=mask)

    img = img.resize((width, height), Image.LANCZOS)
    return ImageTk.PhotoImage(img)


def render_dot(size: int, alpha: int) -> object:
    """Render a circular pulsing dot at given alpha (0-255)."""
    from PIL import Image, ImageDraw, ImageTk

    scale = 4
    S = size * scale
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([0, 0, S - 1, S - 1], fill=(150, 150, 150, alpha))
    img = img.resize((size, size), Image.LANCZOS)
    return ImageTk.PhotoImage(img)
```

- [ ] **Step 2: Run full test suite to verify nothing broke**

```bash
pytest tests/ -v
```

Expected: all tests pass (renderer functions not exercised by unit tests — that is expected).

- [ ] **Step 3: Commit**

```bash
git add src/widget.pyw
git commit -m "feat: Pillow pill bar and pulsing dot renderer at 4x supersample"
```

---

### Task 8: Win32 Window Setup + Taskbar Anchoring

**Files:**

- Modify: `src/widget.pyw` — add Win32 ctypes declarations and window setup functions inside `if __name__ == "__main__":` block

**Interfaces:**

- Produces (all called from inside `__main__` block):
  - `setup_window_flags(hwnd: int) -> None` — applies `WS_EX_NOACTIVATE`, `WS_EX_TOOLWINDOW`, `HWND_TOPMOST`, rounded corners
  - `get_taskbar_rect() -> tuple[int, int, int, int]` — returns `(x, y, width, height)` of taskbar
  - `anchor_to_taskbar(root, widget_width: int, widget_height: int) -> tuple[int, int]` — positions widget bottom-left of work area, returns `(x, y)`

Note: All Win32 code is Windows-only. No automated tests — manual verification on a Windows machine required.

- [ ] **Step 1: Add Win32 declarations and functions to `widget.pyw`**

Replace the `if __name__ == "__main__": pass` block with:

```python
if __name__ == "__main__":
    import ctypes
    import ctypes.wintypes as wintypes
    import tkinter as tk
    from PIL import Image, ImageDraw, ImageTk

    # ── Win32 constants ────────────────────────────────────────────────────────
    GWL_EXSTYLE = -20
    WS_EX_NOACTIVATE = 0x08000000
    WS_EX_TOOLWINDOW = 0x00000080
    HWND_TOPMOST = -1
    SWP_NOMOVE = 0x0002
    SWP_NOSIZE = 0x0001
    SWP_NOACTIVATE = 0x0010
    DWMWA_WINDOW_CORNER_PREFERENCE = 33
    DWMWCP_ROUND = 2
    ABM_GETTASKBARPOS = 0x00000005

    user32 = ctypes.windll.user32
    dwmapi = ctypes.windll.dwmapi
    shell32 = ctypes.windll.shell32

    class _RECT(ctypes.Structure):
        _fields_ = [
            ("left", wintypes.LONG), ("top", wintypes.LONG),
            ("right", wintypes.LONG), ("bottom", wintypes.LONG),
        ]

    class _APPBARDATA(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("hWnd", wintypes.HWND),
            ("uCallbackMessage", wintypes.UINT),
            ("uEdge", wintypes.UINT),
            ("rc", _RECT),
            ("lParam", ctypes.c_long),
        ]

    # ── Win32 functions ────────────────────────────────────────────────────────
    def setup_window_flags(hwnd: int) -> None:
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        style |= WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        user32.SetWindowPos(
            hwnd, HWND_TOPMOST, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
        )
        try:
            pref = ctypes.c_int(DWMWCP_ROUND)
            dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
                ctypes.byref(pref), ctypes.sizeof(pref),
            )
        except Exception:
            pass  # Win10: square corners

    def get_taskbar_rect() -> tuple[int, int, int, int]:
        data = _APPBARDATA()
        data.cbSize = ctypes.sizeof(_APPBARDATA)
        shell32.SHAppBarMessage(ABM_GETTASKBARPOS, ctypes.byref(data))
        r = data.rc
        return r.left, r.top, r.right - r.left, r.bottom - r.top

    def anchor_to_taskbar(root: tk.Tk, widget_w: int, widget_h: int) -> tuple[int, int]:
        tx, ty, tw, th = get_taskbar_rect()
        screen_w = root.winfo_screenwidth()
        screen_h = root.winfo_screenheight()
        # Place bottom-left above taskbar
        x = 4
        y = screen_h - th - widget_h - 4
        root.geometry(f"{widget_w}x{widget_h}+{x}+{y}")
        return x, y

    # (UI and main loop added in Tasks 9-12)
```

- [ ] **Step 2: Run full test suite to confirm nothing broke**

```bash
pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 3: Manual smoke test — launch widget and verify window appears**

```bash
python src/widget.pyw
```

Expected: Python runs without import errors. Window not yet visible (no UI built yet — that's fine).

- [ ] **Step 4: Commit**

```bash
git add src/widget.pyw
git commit -m "feat: Win32 window flags, rounded corners, taskbar anchoring"
```

---

### Task 9: Essential Mode UI

**Files:**

- Modify: `src/widget.pyw` — add `build_essential_ui()` and `WidgetApp` class skeleton inside `__main__` block

**Interfaces:**

- Consumes: `render_pill_bar()`, `render_dot()`, `bar_color()`, `format_bar_count()`, `calc_reset_countdown()`, `QuotaBar`
- Produces: `WidgetApp` class with `update_bars(bars: list[QuotaBar], reset_date_utc: str, stale: bool)` method

Manual verification required.

- [ ] **Step 1: Add `WidgetApp` with essential mode to `widget.pyw`**

Append inside the `if __name__ == "__main__":` block, after the Win32 functions:

```python
    # ── Widget UI ──────────────────────────────────────────────────────────────
    BAR_W = 160
    BAR_H = 18
    PAD = 6
    DOT_SIZE = 8
    FONT_LABEL = ("Segoe UI", 9, "bold")
    FONT_SMALL = ("Segoe UI", 8)
    BG = "#1e1e1e"
    FG = "#cccccc"

    class WidgetApp:
        def __init__(self, config: AppConfig):
            self.config = config
            self.root = tk.Tk()
            self.root.overrideredirect(True)
            self.root.configure(bg=BG)
            self.root.attributes("-topmost", True)
            self.root.attributes("-alpha", 0.95)

            self._bar_images: list = []  # keep refs so GC doesn't collect PhotoImages
            self._dot_image = None
            self._dot_alpha = 255
            self._dot_direction = -1

            self._frame = tk.Frame(self.root, bg=BG)
            self._frame.pack(padx=PAD, pady=PAD)
            self._bar_widgets: list[dict] = []

            self.root.after(100, self._post_init_win32)

        def _post_init_win32(self):
            hwnd = int(self.root.wm_frame(), 16)
            setup_window_flags(hwnd)
            self._hwnd = hwnd
            # Position will be set on first update_bars call

        def _rebuild_frame(self, bars: list[QuotaBar]):
            for w in self._frame.winfo_children():
                w.destroy()
            self._bar_widgets.clear()
            self._bar_images.clear()

            # Essential mode: bars side by side in a single row
            for i, bar in enumerate(bars):
                col_frame = tk.Frame(self._frame, bg=BG)
                col_frame.grid(row=0, column=i, padx=(0, PAD if i < len(bars) - 1 else 0))

                lbl = tk.Label(col_frame, text=bar.label, bg=BG, fg=FG, font=FONT_LABEL)
                lbl.pack(anchor="w")

                bar_lbl = tk.Label(col_frame, bg=BG)
                bar_lbl.pack(anchor="w")

                count_lbl = tk.Label(col_frame, text="", bg=BG, fg=FG, font=FONT_SMALL)
                count_lbl.pack(anchor="w")

                reset_lbl = tk.Label(col_frame, text="", bg=BG, fg="#888888", font=FONT_SMALL)
                reset_lbl.pack(anchor="w")

                self._bar_widgets.append({
                    "bar_lbl": bar_lbl,
                    "count_lbl": count_lbl,
                    "reset_lbl": reset_lbl,
                })

            # Dot indicator (refresh pulse)
            self._dot_lbl = tk.Label(self._frame, bg=BG)
            self._dot_lbl.grid(row=0, column=len(bars), padx=(PAD, 0), sticky="s")

        def update_bars(self, bars: list[QuotaBar], reset_date_utc: str, stale: bool = False):
            if len(bars) != len(self._bar_widgets):
                self._rebuild_frame(bars)
                self.root.update_idletasks()
                total_w = self._frame.winfo_reqwidth() + PAD * 2
                total_h = self._frame.winfo_reqheight() + PAD * 2
                anchor_to_taskbar(self.root, total_w, total_h)

            self._bar_images.clear()
            for i, bar in enumerate(bars):
                color = bar_color(bar.percent_used)
                img = render_pill_bar(BAR_W, BAR_H, bar.percent_used, color, stale=stale)
                self._bar_images.append(img)
                w = self._bar_widgets[i]
                w["bar_lbl"].configure(image=img)
                count_text = format_bar_count(bar)
                if stale:
                    count_text += " ⚠ stale"
                w["count_lbl"].configure(text=count_text)
                w["reset_lbl"].configure(text=f"reset {reset_date_utc[:10]} ({calc_reset_countdown(reset_date_utc)})")

        def pulse_dot(self):
            self._dot_alpha = max(40, min(255, self._dot_alpha + self._dot_direction * 15))
            if self._dot_alpha <= 40 or self._dot_alpha >= 255:
                self._dot_direction *= -1
            self._dot_image = render_dot(DOT_SIZE, self._dot_alpha)
            if hasattr(self, "_dot_lbl"):
                self._dot_lbl.configure(image=self._dot_image)
            self.root.after(80, self.pulse_dot)

        def run(self):
            self.pulse_dot()
            self.root.mainloop()
```

- [ ] **Step 2: Run full test suite**

```bash
pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 3: Manual verification — launch with mock data**

Add a temporary block at the very bottom of `widget.pyw` (inside `__main__`, after `WidgetApp`):

```python
    # TEMP: smoke test with mock data — remove before Task 12
    _cfg = AppConfig()
    _app = WidgetApp(_cfg)
    _bar = QuotaBar("premium_interactions", "Premium", 5000, 90, 98.2, 0, True)
    _app.root.after(200, lambda: _app.update_bars([_bar], "2026-07-01T00:00:00.000Z"))
    _app.run()
```

Run: `python src/widget.pyw`

Expected: compact widget appears near taskbar bottom-left. Progress bar shows ~98% filled in red. Label "Premium", count "90 remaining", reset date visible. Pulsing dot animates.

- [ ] **Step 4: Remove the TEMP block**

Delete the 5 lines marked `# TEMP` from `widget.pyw`.

- [ ] **Step 5: Commit**

```bash
git add src/widget.pyw
git commit -m "feat: essential mode UI with pill bars, labels, reset countdown, pulsing dot"
```

---

### Task 10: Standard Mode UI

**Files:**

- Modify: `src/widget.pyw` — add `_rebuild_standard_frame()` to `WidgetApp`, add mode toggle

**Interfaces:**

- Consumes: `WidgetApp` from Task 9
- Produces: `WidgetApp.set_mode(mode: str)` — switches between `"essential"` and `"standard"`. Right-click on widget triggers context menu with mode toggle.

Manual verification required.

- [ ] **Step 1: Add standard mode and context menu to `WidgetApp` in `widget.pyw`**

Add the following methods to the `WidgetApp` class (inside `__main__` block):

```python
        def _rebuild_standard_frame(self, bars: list[QuotaBar]):
            for w in self._frame.winfo_children():
                w.destroy()
            self._bar_widgets.clear()
            self._bar_images.clear()

            # Standard mode: title bar row, then bars stacked vertically
            title_lbl = tk.Label(
                self._frame, text="Copilot Usage", bg=BG, fg=FG,
                font=("Segoe UI", 10, "bold"),
            )
            title_lbl.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, PAD))

            for i, bar in enumerate(bars):
                row = i + 1
                lbl = tk.Label(self._frame, text=bar.label, bg=BG, fg=FG, font=FONT_LABEL, width=10, anchor="w")
                lbl.grid(row=row, column=0, sticky="w", pady=2)

                bar_lbl = tk.Label(self._frame, bg=BG)
                bar_lbl.grid(row=row, column=1, sticky="w", padx=(PAD, 0))

                count_lbl = tk.Label(self._frame, text="", bg=BG, fg=FG, font=FONT_SMALL)
                count_lbl.grid(row=row + 100, column=0, columnspan=2, sticky="w")

                reset_lbl = tk.Label(self._frame, text="", bg=BG, fg="#888888", font=FONT_SMALL)
                reset_lbl.grid(row=row + 200, column=0, columnspan=2, sticky="w", pady=(0, PAD))

                self._bar_widgets.append({
                    "bar_lbl": bar_lbl,
                    "count_lbl": count_lbl,
                    "reset_lbl": reset_lbl,
                })

            sep = tk.Frame(self._frame, bg="#444444", height=1)
            sep.grid(row=99, column=0, columnspan=2, sticky="ew", pady=PAD)

            self._dot_lbl = tk.Label(self._frame, bg=BG)
            self._dot_lbl.grid(row=99, column=1, sticky="e")

        def set_mode(self, mode: str):
            self.config.display_mode = mode
            save_config(self.config)
            # Force rebuild on next update_bars call
            self._bar_widgets.clear()

        def _show_context_menu(self, event):
            menu = tk.Menu(self.root, tearoff=0, bg="#2d2d2d", fg=FG, activebackground="#444")
            mode = self.config.display_mode
            other = "standard" if mode == "essential" else "essential"
            menu.add_command(label=f"Switch to {other} mode", command=lambda: self.set_mode(other))
            menu.add_separator()
            menu.add_command(label="Refresh now", command=self._trigger_refresh)
            menu.add_separator()
            menu.add_command(label="Quit", command=self.root.destroy)
            menu.tk_popup(event.x_root, event.y_root)

        def _trigger_refresh(self):
            self._poll_once()
```

Also update `_rebuild_frame` to dispatch based on mode. Replace the `_rebuild_frame` method body with:

```python
        def _rebuild_frame(self, bars: list[QuotaBar]):
            if self.config.display_mode == "standard":
                self._rebuild_standard_frame(bars)
            else:
                self._rebuild_essential_frame(bars)
```

And rename the existing essential layout code inside `_rebuild_frame` to `_rebuild_essential_frame`.

Bind right-click on the frame in `__init__`:

```python
            self._frame.bind("<Button-3>", self._show_context_menu)
```

- [ ] **Step 2: Run full test suite**

```bash
pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 3: Manual verification — test mode toggle**

Temporarily add mock data call (same as Task 9 step 3), run widget, right-click → "Switch to standard mode". Verify:

- Standard mode: title "Copilot Usage" visible, bars stacked vertically with labels in left column
- Right-click again → switch back to essential mode

Remove temp code after verification.

- [ ] **Step 4: Commit**

```bash
git add src/widget.pyw
git commit -m "feat: standard mode UI and right-click context menu with mode toggle"
```

---

### Task 11: Toast Notifications + ITaskbarList3 Progress

**Files:**

- Modify: `src/widget.pyw` — add `send_toast()` and `_setup_taskbar_progress()` inside `__main__` block

**Interfaces:**

- Consumes: `thresholds_to_fire()`, `record_notified()` from Task 6
- Produces:
  - `send_toast(title: str, message: str) -> None` — fires Windows toast via PowerShell
  - `WidgetApp._setup_taskbar_progress()` — initializes `ITaskbarList3`, returns callable or `None`
  - `WidgetApp.set_taskbar_progress(value: int, max_value: int) -> None` — updates taskbar icon overlay

Manual verification required.

- [ ] **Step 1: Add `send_toast` to `widget.pyw`** (inside `__main__` block, before `WidgetApp`):

```python
    def send_toast(title: str, message: str) -> None:
        ps = (
            "[Windows.UI.Notifications.ToastNotificationManager, "
            "Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null\n"
            "$t = [Windows.UI.Notifications.ToastNotificationManager]::"
            "GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)\n"
            f'$t.SelectSingleNode(\'//text[@id="1"]\').InnerText = "{title}"\n'
            f'$t.SelectSingleNode(\'//text[@id="2"]\').InnerText = "{message}"\n'
            "$n = [Windows.UI.Notifications.ToastNotification]::new($t)\n"
            '[Windows.UI.Notifications.ToastNotificationManager]::'
            'CreateToastNotifier("Copilot Usage").Show($n)'
        )
        subprocess.Popen(
            ["powershell", "-WindowStyle", "Hidden", "-Command", ps],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
```

- [ ] **Step 2: Add `ITaskbarList3` progress to `WidgetApp`**

Add `_setup_taskbar_progress` and `set_taskbar_progress` methods to `WidgetApp`:

```python
        def _setup_taskbar_progress(self):
            import uuid
            CLSID = "{56FDF344-FD6D-11d0-958A-006097C9A090}"
            IID   = "{EA1AFB91-9E28-4B86-90E9-9E9F8A5EEFAF}"

            class _GUID(ctypes.Structure):
                _fields_ = [
                    ("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                    ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_byte * 8),
                ]

            def _to_guid(s):
                u = uuid.UUID(s)
                b = u.bytes_le
                return _GUID(
                    int.from_bytes(b[:4], "little"),
                    int.from_bytes(b[4:6], "little"),
                    int.from_bytes(b[6:8], "little"),
                    (ctypes.c_byte * 8)(*b[8:]),
                )

            ole32 = ctypes.windll.ole32
            clsid, iid = _to_guid(CLSID), _to_guid(IID)
            p = ctypes.c_void_p()
            if ole32.CoCreateInstance(ctypes.byref(clsid), None, 1, ctypes.byref(iid), ctypes.byref(p)):
                return None

            vt = ctypes.cast(
                ctypes.cast(p, ctypes.POINTER(ctypes.c_void_p))[0],
                ctypes.POINTER(ctypes.c_void_p),
            )
            HRESULT = ctypes.c_long

            HrInit = ctypes.CFUNCTYPE(HRESULT, ctypes.c_void_p)(vt[3])
            HrInit(p)

            _SetProgressValue = ctypes.CFUNCTYPE(
                HRESULT, ctypes.c_void_p, ctypes.c_void_p,
                ctypes.c_ulonglong, ctypes.c_ulonglong,
            )(vt[9])
            _SetProgressState = ctypes.CFUNCTYPE(
                HRESULT, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int,
            )(vt[10])
            hwnd_ptr = ctypes.c_void_p(self._hwnd)
            _SetProgressState(p, hwnd_ptr, 2)  # TBPF_NORMAL

            def _update(value: int, max_value: int):
                _SetProgressValue(p, hwnd_ptr, value, max_value)

            return _update

        def set_taskbar_progress(self, value: int, max_value: int) -> None:
            if hasattr(self, "_taskbar_progress") and self._taskbar_progress:
                try:
                    self._taskbar_progress(value, max_value)
                except Exception:
                    pass
```

Call `_setup_taskbar_progress` from `_post_init_win32`:

```python
        def _post_init_win32(self):
            hwnd = int(self.root.wm_frame(), 16)
            setup_window_flags(hwnd)
            self._hwnd = hwnd
            self._taskbar_progress = self._setup_taskbar_progress()
```

- [ ] **Step 3: Run full test suite**

```bash
pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 4: Manual verification**

Add temp mock data (as before), launch widget. In Task 12 the real polling loop fires toasts; for now verify no crash on startup.

- [ ] **Step 5: Commit**

```bash
git add src/widget.pyw
git commit -m "feat: toast notifications via PowerShell and ITaskbarList3 progress overlay"
```

---

### Task 12: Main Polling Loop

**Files:**

- Modify: `src/widget.pyw` — add `_poll_once()`, `_schedule_next_poll()` to `WidgetApp`, complete the `__main__` launch block

**Interfaces:**

- Consumes: `ensure_authenticated()`, `fetch_user_data()`, `parse_quotas()`, `thresholds_to_fire()`, `record_notified()`, `send_toast()`, `save_config()`, `WidgetApp`
- Produces: complete, runnable widget that polls on schedule and displays live data

- [ ] **Step 1: Add polling to `WidgetApp` in `widget.pyw`**

Add to `WidgetApp`:

```python
        def _poll_once(self):
            stale = False
            bars = []
            reset_date_utc = ""
            try:
                token = ensure_authenticated(self.config)
                data = fetch_user_data(token)
                bars = parse_quotas(data)
                reset_date_utc = data.get("quota_reset_date_utc", "")
                self.config.oauth_token = token

                # Fire notifications
                for bar in bars:
                    to_fire = thresholds_to_fire(
                        bar.id, bar.percent_used, self.config.notified, reset_date_utc
                    )
                    for t in to_fire:
                        send_toast(
                            "Copilot Usage",
                            f"{bar.label}: {bar.percent_used:.0f}% used ({bar.remaining} remaining)",
                        )
                        self.config.notified = record_notified(
                            self.config.notified, bar.id, t, reset_date_utc
                        )
                save_config(self.config)

            except RuntimeError as e:
                stale = True
                # Keep last bars if available
                if not bars:
                    bars = getattr(self, "_last_bars", [])
                    reset_date_utc = getattr(self, "_last_reset", "")

            if bars:
                self._last_bars = bars
                self._last_reset = reset_date_utc
                self.update_bars(bars, reset_date_utc, stale=stale)
                if bars:
                    self.set_taskbar_progress(
                        int(bars[0].percent_used),
                        100,
                    )

            self._force_refresh = False
            self._schedule_next_poll()

        def _schedule_next_poll(self):
            interval_ms = self.config.refresh_interval * 1000
            self.root.after(interval_ms, self._check_and_poll)

        def _check_and_poll(self):
            self._poll_once()
```

- [ ] **Step 2: Add the main launch block**

Replace the `pass` (or any temp code) at the very bottom of `if __name__ == "__main__":` with:

```python
    # ── Launch ─────────────────────────────────────────────────────────────────
    ctypes.windll.ole32.CoInitialize(None)
    _config = load_config()
    _app = WidgetApp(_config)
    _app._force_refresh = False
    _app.root.after(500, _app._poll_once)  # first poll after 500ms startup delay
    _app.run()
```

- [ ] **Step 3: Run full test suite**

```bash
pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 4: Manual verification — end-to-end**

```bash
python src/widget.pyw
```

Expected:

- Widget appears near taskbar bottom-left
- After ~500ms, bars populate with live Copilot usage data
- Reset countdown shows correct date
- Right-click context menu works: mode toggle, refresh now, quit
- Taskbar icon shows progress overlay
- Pulsing dot animates continuously

- [ ] **Step 5: Commit**

```bash
git add src/widget.pyw
git commit -m "feat: main polling loop with live data, notifications, and taskbar progress"
```

---

### Task 13: Build Pipeline

**Files:**

- Create: `scripts/build.ps1`
- Create: `installer/setup.iss`
- Create: `widget.spec` (PyInstaller spec, generated then committed)

- [ ] **Step 1: Create `scripts/build.ps1`**

```powershell
<#
.SYNOPSIS
    Build CopilotUsage-Setup.exe from source.
.PREREQUISITES
    Python 3.11+, PyInstaller, Inno Setup 6+ (iscc in PATH)
#>
$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent

Write-Host "==> Installing Python dependencies..."
pip install -r "$Root\requirements.txt" --quiet

Write-Host "==> Running PyInstaller..."
pyinstaller --noconfirm `
    --onefile `
    --windowed `
    --name "CopilotUsage" `
    --icon "$Root\assets\icon.ico" `
    --add-binary "C:\Windows\System32\curl.exe;." `
    --distpath "$Root\dist" `
    --workpath "$Root\build" `
    "$Root\src\widget.pyw"

Write-Host "==> Running Inno Setup..."
iscc "$Root\installer\setup.iss"

Write-Host "==> Done. Installer at $Root\releases\CopilotUsage-Setup.exe"
```

- [ ] **Step 2: Create `installer/setup.iss`**

```iss
[Setup]
AppName=Copilot Usage
AppVersion=1.0.0
AppPublisher=Serge ARADJ
DefaultDirName={autopf}\CopilotUsage
DefaultGroupName=Copilot Usage
OutputDir=..\releases
OutputBaseFilename=CopilotUsage-Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest

[Files]
Source: "..\dist\CopilotUsage.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Copilot Usage"; Filename: "{app}\CopilotUsage.exe"
Name: "{userstartup}\Copilot Usage"; Filename: "{app}\CopilotUsage.exe"

[Run]
Filename: "{app}\CopilotUsage.exe"; Description: "Launch Copilot Usage"; Flags: nowait postinstall skipifsilent
```

- [ ] **Step 3: Create `assets/` placeholder and `icon.ico`**

```bash
mkdir -p assets
```

Note: `assets/icon.ico` must be a valid `.ico` file. Create a 32×32 icon with the GitHub Copilot logo or a simple placeholder. The build will fail without it. If no icon is ready, temporarily remove the `--icon` flag from `build.ps1`.

- [ ] **Step 4: Commit build pipeline**

```bash
git add scripts/build.ps1 installer/setup.iss assets/
git commit -m "chore: PyInstaller + Inno Setup build pipeline"
```

- [ ] **Step 5: Manual build verification**

```powershell
.\scripts\build.ps1
```

Expected: `releases/CopilotUsage-Setup.exe` created. Run the installer, verify widget launches from Start Menu shortcut and from startup entry.

---

### Task 14: README

**Files:**

- Create: `README.md`

- [ ] **Step 1: Create `README.md`**

```markdown
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

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: README with install, auth, display, and build instructions"
```

---

## Final Verification

- [ ] Run `pytest tests/ -v` — all tests pass
- [ ] Run `python src/widget.pyw` — widget launches, shows live data
- [ ] Run `.\scripts\build.ps1` — installer builds successfully
- [ ] Install from `releases/CopilotUsage-Setup.exe` — widget starts on login
