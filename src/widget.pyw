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


# ── AppConfig dataclass ────────────────────────────────────────────────────────
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


# ── Authentication ─────────────────────────────────────────────────────────────
def get_gh_token() -> Optional[str]:
    """Run `gh auth token`, return token string or None on any failure."""
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        token = result.stdout.strip()
        return token if token else None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def ensure_authenticated(config: AppConfig) -> str:
    """Return valid Bearer token. Updates config.oauth_token as side effect.

    Strategy: cached token → gh auth token → gh auth login --web + retry.
    Raises RuntimeError if all paths fail.
    """
    # Try cached token first
    if config.oauth_token:
        return config.oauth_token

    # Try to get token from gh CLI
    token = get_gh_token()
    if token:
        config.oauth_token = token
        return token

    # gh installed but not logged in — trigger device flow
    subprocess.run(["gh", "auth", "login", "--web"], check=False)
    token = get_gh_token()
    if token:
        config.oauth_token = token
        return token

    raise RuntimeError(
        "Could not obtain GitHub token.\n"
        "Install GitHub CLI (https://cli.github.com) and run: gh auth login"
    )


# ── Guard — everything below this line only runs when launched directly ────────
if __name__ == "__main__":
    pass
