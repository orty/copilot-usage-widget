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


# ── QuotaBar dataclass ─────────────────────────────────────────────────────────
@dataclass
class QuotaBar:
    id: str
    label: str
    entitlement: int
    remaining: int
    percent_used: float
    overage_count: int
    overage_permitted: bool


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


# ── API client ─────────────────────────────────────────────────────────────────
def humanize_label(quota_id: str) -> str:
    """Convert quota_id to human-readable label.

    Uses LABEL_MAP if available, otherwise converts quota_id to title case.
    """
    if quota_id in LABEL_MAP:
        return LABEL_MAP[quota_id]
    return quota_id.replace("_", " ").title()


def fetch_user_data(token: str) -> dict:
    """Fetch user quota data from GitHub API.

    Args:
        token: GitHub personal access token.

    Returns:
        Parsed JSON response containing quota_snapshots.

    Raises:
        RuntimeError: If curl request fails.
    """
    result = subprocess.run(
        ["curl", "-s", "--fail",
         "-H", f"Authorization: Bearer {token}",
         "-H", "Accept: application/json",
         API_URL],
        capture_output=True,
        timeout=15,
    )

    if result.returncode != 0:
        raise RuntimeError(f"curl failed (exit {result.returncode}): {result.stderr.decode()}")

    return json.loads(result.stdout)


def parse_quotas(data: dict) -> list[QuotaBar]:
    """Parse quota_snapshots from API response into QuotaBar objects.

    Skips any snapshots where unlimited == True.

    Args:
        data: Response dict from fetch_user_data.

    Returns:
        List of QuotaBar objects for all limited quotas.
    """
    quotas = []
    for quota_id, snap in data.get("quota_snapshots", {}).items():
        if snap.get("unlimited", False):
            continue

        percent_used = 100.0 - snap.get("percent_remaining", 100.0)

        quota = QuotaBar(
            id=quota_id,
            label=humanize_label(quota_id),
            entitlement=snap.get("entitlement", 0),
            remaining=snap.get("remaining", 0),
            percent_used=percent_used,
            overage_count=snap.get("overage_count", 0),
            overage_permitted=snap.get("overage_permitted", False),
        )
        quotas.append(quota)

    return quotas


# ── Display helpers ────────────────────────────────────────────────────────────
def bar_color(percent_used: float) -> str:
    """Return hex color string based on usage percentage.

    Args:
        percent_used: Percentage of quota used (0-100+).

    Returns:
        Hex color string: critical (#cf222e) if >= 90%, warning (#d4a017) if >= 75%, normal (#0969da) otherwise.
    """
    if percent_used >= 90.0:
        return COLOR_CRITICAL
    if percent_used >= 75.0:
        return COLOR_WARNING
    return COLOR_NORMAL


def calc_reset_countdown(reset_date_utc: str) -> str:
    """Calculate human-readable countdown to reset date.

    Handles ISO 8601 format with Z suffix (from API).

    Args:
        reset_date_utc: ISO 8601 datetime string (e.g. "2099-01-01T00:00:00.000Z").

    Returns:
        Countdown string: "reset now" if past, "11d 12h" if > 1 day, "3h 45m" if > 1 hour, "23m" otherwise.
    """
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
    """Format remaining count with optional overage suffix.

    Args:
        bar: QuotaBar object with remaining and overage_count.

    Returns:
        String like "90 remaining" or "0 remaining (+3 overage)" if overage.
    """
    base = f"{bar.remaining} remaining"
    if bar.overage_count > 0:
        return f"{base} (+{bar.overage_count} overage)"
    return base


# ── Guard — everything below this line only runs when launched directly ────────
if __name__ == "__main__":
    pass
