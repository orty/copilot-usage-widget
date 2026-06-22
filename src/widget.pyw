"""Copilot Usage Widget — monitors GitHub Copilot Enterprise premium interaction credits."""
from __future__ import annotations

import ctypes
import json
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── Constants ──────────────────────────────────────────────────────────────────
APP_NAME = "Copilot Usage"
APP_VERSION = "2.0.4"
GITHUB_REPO_URL = "https://github.com/orty/copilot-usage-widget"
COPILOT_URL = "https://github.com/features/copilot"
UPDATE_API_URL = "https://api.github.com/repos/orty/copilot-usage-widget/releases/latest"
UPDATE_RELEASES_URL = f"{GITHUB_REPO_URL}/releases"
UPDATE_ASSET_NAME = "CopilotUsage-Setup.exe"
UPDATE_CHECK_INTERVAL_S = 24 * 3600   # throttle: re-check at most once per day
UPDATE_STARTUP_DELAY_MS = 12_000      # wait 12s after launch before first check
CONFIG_PATH = Path(os.environ.get("LOCALAPPDATA", ".")) / APP_NAME / "config.json"
API_URL = "https://api.github.com/copilot_internal/user"
POLL_DEFAULT = 180
POLL_MIN = 10
POLL_MAX = 3600
TOAST_THRESHOLDS = [75, 90, 95, 100]
COLOR_NORMAL = "#0969da"
COLOR_WARNING = "#d4a017"
COLOR_CRITICAL = "#cf222e"
LABEL_MAP = {"premium_interactions": "Premium"}


# ── Subprocess / network helpers ────────────────────────────────────────────────
# On Windows a console subprocess (curl, gh, powershell) briefly flashes a cmd
# window. CREATE_NO_WINDOW + a hidden STARTUPINFO suppress it. No-op elsewhere.
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def _no_window_kwargs() -> dict:
    """subprocess kwargs that suppress the console window on Windows."""
    if sys.platform != "win32":
        return {}
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = subprocess.SW_HIDE
    return {"creationflags": _CREATE_NO_WINDOW, "startupinfo": si}


def _ssl_context() -> ssl.SSLContext:
    """Default SSL context, preferring certifi's CA bundle when available.

    A frozen (PyInstaller) build often lacks the system CA store, which makes
    urllib HTTPS fail with CERTIFICATE_VERIFY_FAILED. certifi ships a bundle so
    the auto-update check and API call work the same way curl did.
    """
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        return ctx


def _http_get_json(url: str, headers: dict, timeout: int = 15) -> dict:
    """GET a URL and parse JSON. Pure urllib — never spawns a console window."""
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _download_file(url: str, dest: Path, timeout: int = 120) -> Path:
    """Stream a URL to dest (atomically) for the seamless updater.

    Follows GitHub's redirect to the asset CDN. Writes to a .part file first,
    then renames, so a half-finished download is never run.
    """
    req = urllib.request.Request(
        url, headers={"User-Agent": f"CopilotUsageWidget/{APP_VERSION}",
                      "Accept": "application/octet-stream"},
    )
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp, \
            open(tmp, "wb") as f:
        shutil.copyfileobj(resp, f)
    os.replace(tmp, dest)
    return dest


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
    countdown_display: str = "dot"   # "dot" | "numeric"
    show_in_taskbar: bool = False
    notifications_enabled: bool = True
    window_width: int = -1
    window_height: int = -1
    last_update_check: int = 0


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
            countdown_display=raw.get("countdown_display", "dot"),
            show_in_taskbar=raw.get("show_in_taskbar", False),
            notifications_enabled=raw.get("notifications_enabled", True),
            window_width=raw.get("window_width", -1),
            window_height=raw.get("window_height", -1),
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
        "countdown_display": config.countdown_display,
        "show_in_taskbar": config.show_in_taskbar,
        "notifications_enabled": config.notifications_enabled,
        "window_width": config.window_width,
        "window_height": config.window_height,
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
            **_no_window_kwargs(),
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
    try:
        subprocess.run(["gh", "auth", "login", "--web"], check=False, timeout=300,
                       **_no_window_kwargs())
    except subprocess.TimeoutExpired:
        pass
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

    Uses urllib instead of a curl subprocess so no console window flashes on
    every refresh.

    Args:
        token: GitHub personal access token.

    Returns:
        Parsed JSON response containing quota_snapshots.

    Raises:
        RuntimeError: If the request fails.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": f"CopilotUsageWidget/{APP_VERSION}",
    }
    try:
        return _http_get_json(API_URL, headers, timeout=15)
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
        raise RuntimeError(f"API request failed: {e}") from e


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


# ── Notification tracker ───────────────────────────────────────────────────────
def thresholds_to_fire(
    quota_id: str, percent_used: float, notified: dict, reset_date_utc: str
) -> list[int]:
    """Return thresholds not yet fired this billing period.

    Args:
        quota_id: Quota identifier (e.g. "premium_interactions").
        percent_used: Current usage percentage (0-100+).
        notified: Dict of {quota_id: {period: [thresholds]}}.
        reset_date_utc: ISO 8601 reset date (e.g. "2026-07-01T00:00:00.000Z").

    Returns:
        List of thresholds from TOAST_THRESHOLDS that are >= percent_used and not yet fired.
    """
    period_key = reset_date_utc[:10]
    fired = notified.get(quota_id, {}).get(period_key, [])
    return [t for t in TOAST_THRESHOLDS if percent_used >= t and t not in fired]


def record_notified(
    notified: dict, quota_id: str, threshold: int, reset_date_utc: str
) -> dict:
    """Record a fired threshold for this billing period.

    Does NOT mutate the input dict; returns a new dict with the threshold added.

    Args:
        notified: Dict of {quota_id: {period: [thresholds]}}.
        quota_id: Quota identifier (e.g. "premium_interactions").
        threshold: Threshold value to record (e.g. 75, 90, 95, 100).
        reset_date_utc: ISO 8601 reset date (e.g. "2026-07-01T00:00:00.000Z").

    Returns:
        New dict with threshold added to the right period.
    """
    period_key = reset_date_utc[:10]
    updated = {k: {pk: list(pv) for pk, pv in v.items()} for k, v in notified.items()}
    updated.setdefault(quota_id, {}).setdefault(period_key, []).append(threshold)
    return updated


# ── Rendering (Pillow) ────────────────────────────────────────────────────────
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
    """Render an anti-aliased pill-shaped progress bar at 4× supersample.

    The percentage text is deliberately NOT baked into this image. Tk draws it
    natively over the bar (Label compound='center'), so it renders as crisp,
    properly-weighted ClearType — matching the reference widget — instead of a
    downscaled PIL glyph that looked either bold-and-blurry or too thin.
    """
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


# ── Auto-update helpers ────────────────────────────────────────────────────────

def _version_tuple(v: str):
    try:
        return tuple(int(x) for x in str(v).strip().lstrip("vV").split("."))
    except ValueError:
        return (0,)


def is_newer_version(latest: str, current: str = APP_VERSION) -> bool:
    return _version_tuple(latest) > _version_tuple(current)


def check_latest_release() -> Optional[dict]:
    """Query GitHub Releases API. Returns dict or None on failure/draft/pre-release."""
    try:
        data = _http_get_json(
            UPDATE_API_URL,
            {
                "User-Agent": f"CopilotUsageWidget/{APP_VERSION}",
                "Accept": "application/vnd.github+json",
            },
            timeout=10,
        )
    except (urllib.error.URLError, json.JSONDecodeError, OSError):
        return None
    if data.get("draft") or data.get("prerelease"):
        return None
    tag = data.get("tag_name") or ""
    asset_url = None
    for a in data.get("assets") or []:
        if a.get("name") == UPDATE_ASSET_NAME:
            asset_url = a.get("browser_download_url")
            break
    return {
        "version": tag.lstrip("vV"),
        "tag": tag,
        "asset_url": asset_url,
        "html_url": data.get("html_url") or UPDATE_RELEASES_URL,
    }


# ── Guard — everything below this line only runs when launched directly ────────
if __name__ == "__main__":
    import ctypes
    import ctypes.wintypes as wintypes
    import tkinter as tk
    import tkinter.messagebox  # noqa: F401  (registers tk.messagebox)
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
    KEEP_ON_TOP_MS = 10  # re-assert topmost within one frame so the taskbar can't cover us
    EDGE_MARGIN = 4        # gap between widget and screen edge

    user32 = ctypes.windll.user32
    dwmapi = ctypes.windll.dwmapi

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

    def clamp_to_screen(root: tk.Tk, x: int, y: int, widget_w: int, widget_h: int) -> tuple[int, int]:
        """Keep the window on-screen while still letting it overlap the taskbar.

        Uses the full screen size (not the work area) on purpose: the widget is
        meant to sit *over* the taskbar. We only stop it from leaving the screen
        entirely. Staying in front of the taskbar is handled by keep_on_top().
        """
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        x = max(0, min(x, sw - widget_w))
        y = max(0, min(y, sh - widget_h))
        return x, y

    def anchor_to_taskbar(root: tk.Tk, widget_w: int, widget_h: int) -> tuple[int, int]:
        """Anchor the widget to the bottom-right, overlapping the taskbar."""
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        x, y = clamp_to_screen(
            root,
            sw - widget_w - EDGE_MARGIN,
            sh - widget_h - EDGE_MARGIN,
            widget_w, widget_h,
        )
        root.geometry(f"{widget_w}x{widget_h}+{x}+{y}")
        return x, y

    # ── Toast notifications ────────────────────────────────────────────────────
    def send_toast(title: str, message: str) -> None:
        safe_title = title.replace('"', "'")
        safe_message = message.replace('"', "'").replace('$', '`$')
        ps = (
            "[Windows.UI.Notifications.ToastNotificationManager, "
            "Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null\n"
            "$t = [Windows.UI.Notifications.ToastNotificationManager]::"
            "GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)\n"
            f'$t.SelectSingleNode(\'//text[@id="1"]\').InnerText = "{safe_title}"\n'
            f'$t.SelectSingleNode(\'//text[@id="2"]\').InnerText = "{safe_message}"\n'
            "$n = [Windows.UI.Notifications.ToastNotification]::new($t)\n"
            '[Windows.UI.Notifications.ToastNotificationManager]::'
            'CreateToastNotifier(APP_NAME).Show($n)'
        )
        subprocess.Popen(
            ["powershell", "-WindowStyle", "Hidden", "-Command", ps],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            **_no_window_kwargs(),
        )

    # ── Widget UI ──────────────────────────────────────────────────────────────
    BAR_W = 160
    BAR_H = 18
    PAD = 4
    PAD_V = 1
    DOT_SIZE = 8
    FONT = "Segoe UI"
    FONT_LABEL = (FONT, 9, "bold")
    FONT_BAR = (FONT, 9, "bold")   # percentage on the bar — matches reference FT_BAR
    FONT_SMALL = (FONT, 8)
    FONT_TITLE = (FONT, 10, "bold")
    FONT_MENU = (FONT, 11)
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
            self._last_bars: list = []
            self._last_reset: str = ""
            self._available_update: Optional[dict] = None  # set by background update check
            self._updating = False  # guards against re-entrant update runs

            self._frame = tk.Frame(self.root, bg=BG)
            self._frame.pack(padx=PAD, pady=PAD_V)
            self._bar_widgets: list[dict] = []
            self._drag_x = 0
            self._drag_y = 0

            self.root.after(100, self._post_init_win32)

        def _bind_widgets(self, widget: tk.Widget, skip_drag: bool = False) -> None:
            """Recursively bind right-click and drag to widget and all children."""
            widget.bind("<Button-3>", self._show_context_menu)
            if not skip_drag:
                widget.bind("<ButtonPress-1>", self._start_drag)
                widget.bind("<B1-Motion>", self._do_drag)
                widget.bind("<ButtonRelease-1>", self._end_drag)
            for child in widget.winfo_children():
                # Menu button skips drag so clicks open menu, not drag
                self._bind_widgets(child, skip_drag=getattr(child, "_is_menu_btn", False))

        def _start_drag(self, event: tk.Event) -> None:
            self._drag_x = event.x_root - self.root.winfo_x()
            self._drag_y = event.y_root - self.root.winfo_y()

        def _do_drag(self, event: tk.Event) -> None:
            x = event.x_root - self._drag_x
            y = event.y_root - self._drag_y
            self.root.geometry(f"+{x}+{y}")

        def _end_drag(self, event: tk.Event) -> None:
            # Keep on-screen but allow the widget to rest over the taskbar.
            w, h = self.root.winfo_width(), self.root.winfo_height()
            x, y = clamp_to_screen(self.root, self.root.winfo_x(), self.root.winfo_y(), w, h)
            self.config.window_x = x
            self.config.window_y = y
            self.root.geometry(f"+{x}+{y}")
            save_config(self.config)

        def _post_init_win32(self):
            hwnd = int(self.root.wm_frame(), 16)
            setup_window_flags(hwnd)
            self._hwnd = hwnd
            self._taskbar_progress = self._setup_taskbar_progress()
            # Two-layer defence so the widget never slips behind the taskbar
            # (mirrors niccolo-sabato/claude-usage-widget):
            #   1. <Visibility> fires the instant the taskbar covers us →
            #      re-raise immediately (the click-empty-taskbar case).
            #   2. a 10ms timer as a safety net for cases Visibility misses.
            self.root.bind("<Visibility>", lambda e: self._force_topmost())
            self._keep_on_top()
            # Position will be set on first update_bars call

        def _force_topmost(self):
            """Re-assert HWND_TOPMOST + the Tk topmost attribute immediately.

            WS_EX_NOACTIVATE keeps the widget out of the focus chain, so this
            never steals focus. SetWindowPos with NOMOVE/NOSIZE/NOACTIVATE is a
            cheap no-op when already on top.
            """
            hwnd = getattr(self, "_hwnd", None)
            if hwnd:
                try:
                    user32.SetWindowPos(
                        hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
                    )
                except Exception:
                    pass
            try:
                self.root.attributes("-topmost", True)
            except Exception:
                pass

        def _keep_on_top(self):
            """10ms topmost watchdog. Below the 16ms/60Hz frame budget, so any
            taskbar-overlap flash is recovered within one frame — imperceptible.
            """
            self._force_topmost()
            self.root.after(KEEP_ON_TOP_MS, self._keep_on_top)

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
            hresult = ctypes.c_long

            hr_init = ctypes.CFUNCTYPE(hresult, ctypes.c_void_p)(vt[3])
            hr_init(p)

            set_progress_value = ctypes.CFUNCTYPE(
                hresult, ctypes.c_void_p, ctypes.c_void_p,
                ctypes.c_ulonglong, ctypes.c_ulonglong,
            )(vt[9])
            set_progress_state = ctypes.CFUNCTYPE(
                hresult, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int,
            )(vt[10])
            hwnd_ptr = ctypes.c_void_p(self._hwnd)
            set_progress_state(p, hwnd_ptr, 2)  # TBPF_NORMAL

            def _update(value: int, max_value: int):
                set_progress_value(p, hwnd_ptr, value, max_value)

            return _update

        def set_taskbar_progress(self, value: int, max_value: int) -> None:
            if hasattr(self, "_taskbar_progress") and self._taskbar_progress:
                try:
                    self._taskbar_progress(value, max_value)
                except Exception:
                    pass

        def _show_tooltip(self, widget: tk.Widget, text: str) -> None:
            def on_enter(e):
                tip = tk.Toplevel(self.root)
                tip.wm_overrideredirect(True)
                tip.attributes("-topmost", True)
                tip.configure(bg="#333333")
                lbl = tk.Label(tip, text=text, bg="#333333", fg="#ffffff",
                               font=FONT_SMALL, padx=6, pady=3)
                lbl.pack()
                x = widget.winfo_rootx() + 4
                y = widget.winfo_rooty() - tip.winfo_reqheight() - 4
                tip.geometry(f"+{x}+{y}")
                widget._tip = tip
            def on_leave(e):
                tip = getattr(widget, "_tip", None)
                if tip:
                    tip.destroy()
                    widget._tip = None
            widget.bind("<Enter>", on_enter)
            widget.bind("<Leave>", on_leave)

        def _rebuild_essential_frame(self, bars: list[QuotaBar]):
            for w in self._frame.winfo_children():
                w.destroy()
            self._bar_widgets.clear()
            self._bar_images.clear()

            # Essential: pure horizontal pack — no grid rows that inflate height
            for i, bar in enumerate(bars):
                col = tk.Frame(self._frame, bg=BG)
                col.pack(side="left",
                         padx=(0, PAD if i < len(bars) - 1 else 0),
                         pady=0)

                bar_lbl = tk.Label(col, bg=BG, pady=0)
                bar_lbl.pack(anchor="w", pady=0)

                reset_lbl = tk.Label(col, text="", bg=BG, fg="#d0d0ce",
                                     font=FONT_SMALL, pady=0)
                reset_lbl.pack(anchor="w", pady=0)

                self._bar_widgets.append({"bar_lbl": bar_lbl, "reset_lbl": reset_lbl})

            # Dot + ≡ in compact right column
            ctrl = tk.Frame(self._frame, bg=BG)
            ctrl.pack(side="left", padx=(PAD, 0), pady=0)

            menu_btn = tk.Label(ctrl, text="≡", bg="#2a2a2a", fg="#cccccc",
                                font=FONT_LABEL, cursor="hand2", padx=3, pady=0)
            menu_btn._is_menu_btn = True
            menu_btn.bind("<Button-1>", lambda e: self._show_context_menu(e))
            menu_btn.pack(anchor="n", pady=0)

            self._dot_lbl = tk.Label(ctrl, bg=BG, pady=0)
            self._dot_lbl.pack(anchor="s", pady=0)

            self._bind_widgets(self._frame)

        def _rebuild_standard_frame(self, bars: list[QuotaBar]):
            for w in self._frame.winfo_children():
                w.destroy()
            self._bar_widgets.clear()
            self._bar_images.clear()

            # Header row: title + ≡
            hdr = tk.Frame(self._frame, bg=BG)
            hdr.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, PAD))
            tk.Label(hdr, text=APP_NAME, bg=BG, fg=FG, font=FONT_TITLE).pack(side="left")
            menu_btn = tk.Label(hdr, text="≡", bg=BG, fg="#aaaaaa", font=FONT_MENU, cursor="hand2")
            menu_btn._is_menu_btn = True
            menu_btn.bind("<Button-1>", lambda e: self._show_context_menu(e))
            menu_btn.pack(side="right")

            for i, bar in enumerate(bars):
                row = i + 1
                lbl = tk.Label(self._frame, text=bar.label, bg=BG, fg=FG, font=FONT_LABEL, width=10, anchor="w")
                lbl.grid(row=row, column=0, sticky="w", pady=2)

                bar_lbl = tk.Label(self._frame, bg=BG)
                bar_lbl.grid(row=row, column=1, sticky="w", padx=(PAD, 0))

                reset_lbl = tk.Label(self._frame, text="", bg=BG, fg="#d0d0ce", font=FONT_SMALL)
                reset_lbl.grid(row=row + 100, column=0, columnspan=2, sticky="w", pady=(0, PAD))

                self._bar_widgets.append({
                    "bar_lbl": bar_lbl,
                    "reset_lbl": reset_lbl,
                })

            sep = tk.Frame(self._frame, bg="#444444", height=1)
            sep.grid(row=99, column=0, columnspan=2, sticky="ew", pady=PAD)

            self._dot_lbl = tk.Label(self._frame, bg=BG, width=DOT_SIZE, height=DOT_SIZE)
            self._dot_lbl.grid(row=99, column=1, sticky="e")
            self._bind_widgets(self._frame)

        def _rebuild_frame(self, bars: list[QuotaBar]):
            if self.config.display_mode == "standard":
                self._rebuild_standard_frame(bars)
            else:
                self._rebuild_essential_frame(bars)

        def set_mode(self, mode: str):
            self.config.display_mode = mode
            save_config(self.config)
            self._bar_widgets.clear()
            if self._last_bars:
                self.update_bars(self._last_bars, self._last_reset)

        def _show_context_menu(self, event):
            import tkinter.simpledialog as sd
            m = tk.Menu(self.root, tearoff=0, bg="#2d2d2d", fg=FG,
                        activebackground="#444444", font=FONT_SMALL)

            m.add_command(label="↺  Refresh", command=self._trigger_refresh)
            m.add_separator()

            # Mode toggle
            other_mode = "standard" if self.config.display_mode == "essential" else "essential"
            m.add_command(label=f"⇅  {other_mode.title()} mode",
                          command=lambda: self.set_mode(other_mode))
            m.add_separator()

            # Settings
            m.add_command(
                label=f"⏱  Refresh interval... ({self.config.refresh_interval}s)",
                command=self._menu_set_refresh_interval,
            )
            notif_state = "ON" if self.config.notifications_enabled else "OFF"
            m.add_command(
                label=f"🔔  Notifications: {notif_state}",
                command=self._menu_toggle_notifications,
            )
            taskbar_state = "ON" if self.config.show_in_taskbar else "OFF"
            m.add_command(
                label=f"📌  Taskbar icon: {taskbar_state}",
                command=self._menu_toggle_taskbar_icon,
            )
            dot_state = "dot" if self.config.countdown_display == "dot" else "numeric"
            m.add_command(
                label=f"⏲  Countdown: {dot_state}",
                command=self._menu_toggle_countdown,
            )
            m.add_separator()

            # Auth / links
            m.add_command(label="🔑  Re-authenticate", command=self._menu_reauthenticate)
            m.add_command(label="⬡  Open Copilot",
                          command=lambda: webbrowser.open(COPILOT_URL))
            m.add_command(label="⌥  Open GitHub repo",
                          command=lambda: webbrowser.open(GITHUB_REPO_URL))
            m.add_command(label="{}  Open config.json",
                          command=lambda: os.startfile(str(CONFIG_PATH)))
            m.add_separator()

            # Updates
            if self._available_update:
                ver = self._available_update["version"]
                m.add_command(
                    label=f"⬆  Install update (v{ver})",
                    command=self._apply_update,
                    foreground="#4CAF50",
                )
            else:
                m.add_command(label="⬆  Check for updates...", command=self._menu_check_updates)
            m.add_separator()

            m.add_command(label="✕  Quit", command=self.root.destroy)
            m.add_separator()
            m.add_command(label=f"v{APP_VERSION}", state="disabled")

            m.tk_popup(event.x_root, event.y_root)

        def _menu_set_refresh_interval(self):
            import tkinter.simpledialog as sd
            val = sd.askinteger(
                APP_NAME, f"Refresh interval (seconds, {POLL_MIN}–{POLL_MAX}):",
                initialvalue=self.config.refresh_interval,
                minvalue=POLL_MIN, maxvalue=POLL_MAX,
                parent=self.root,
            )
            if val:
                self.config.refresh_interval = val
                save_config(self.config)

        def _menu_toggle_notifications(self):
            self.config.notifications_enabled = not self.config.notifications_enabled
            save_config(self.config)

        def _menu_toggle_taskbar_icon(self):
            self.config.show_in_taskbar = not self.config.show_in_taskbar
            save_config(self.config)

        def _menu_toggle_countdown(self):
            self.config.countdown_display = (
                "numeric" if self.config.countdown_display == "dot" else "dot"
            )
            save_config(self.config)

        def _menu_reauthenticate(self):
            self.config.oauth_token = ""
            save_config(self.config)
            self._trigger_refresh()

        def _trigger_refresh(self):
            self._poll_once()

        # ── Auto-update ──────────────────────────────────────────────────────

        def _schedule_update_check(self):
            now = int(time.time())
            last = self.config.last_update_check
            if now - last < UPDATE_CHECK_INTERVAL_S:
                return
            self.root.after(UPDATE_STARTUP_DELAY_MS, self._auto_check_update)

        def _auto_check_update(self):
            self.config.last_update_check = int(time.time())
            save_config(self.config)
            threading.Thread(target=self._do_check_update, daemon=True).start()

        def _do_check_update(self):
            info = check_latest_release()
            if info and is_newer_version(info["version"]):
                self._available_update = info

        def _menu_check_updates(self):
            """Manual menu trigger — checks, then runs the seamless updater."""
            def _worker():
                info = check_latest_release()
                if info is None:
                    self.root.after(0, lambda: tk.messagebox.showwarning(
                        APP_NAME, "Could not reach GitHub. Check your connection."))
                elif is_newer_version(info["version"]):
                    self._available_update = info
                    self.root.after(0, self._apply_update)
                else:
                    self.root.after(0, lambda: tk.messagebox.showinfo(
                        APP_NAME, f"You're up to date (v{APP_VERSION})."))
            threading.Thread(target=_worker, daemon=True).start()

        # ── Seamless update: download installer, run it, relaunch ─────────────

        def _apply_update(self):
            """Download the installer under the hood and run it — no browser."""
            info = self._available_update
            if not info:
                return
            url = info.get("asset_url")
            if not url:
                # Release has no installer asset — fall back to the page.
                webbrowser.open(info.get("html_url", UPDATE_RELEASES_URL))
                return
            if getattr(self, "_updating", False):
                return  # already in progress
            if not tk.messagebox.askyesno(
                APP_NAME,
                f"Update to v{info['version']} now?\n\n"
                "Copilot Usage will close, install the update, and reopen.",
            ):
                return
            self._updating = True
            send_toast(APP_NAME, f"Downloading update v{info['version']}…")
            threading.Thread(
                target=self._download_and_install, args=(url,), daemon=True
            ).start()

        def _download_and_install(self, url: str):
            try:
                dest = Path(tempfile.gettempdir()) / UPDATE_ASSET_NAME
                _download_file(url, dest)
            except Exception as e:
                self._updating = False
                self.root.after(0, lambda err=e: tk.messagebox.showerror(
                    APP_NAME, f"Update download failed:\n{err}"))
                return
            self.root.after(0, lambda: self._run_installer_and_quit(dest))

        def _run_installer_and_quit(self, installer: Path):
            # /VERYSILENT: no wizard. /CLOSEAPPLICATIONS: free any locked files.
            # setup.iss relaunches the app afterwards (WizardSilent [Run] entry).
            try:
                subprocess.Popen(
                    [str(installer), "/VERYSILENT", "/SUPPRESSMSGBOXES",
                     "/NORESTART", "/CLOSEAPPLICATIONS"],
                    **_no_window_kwargs(),
                )
            except Exception as e:
                self._updating = False
                tk.messagebox.showerror(APP_NAME, f"Could not start installer:\n{e}")
                return
            # Quit so the installer can replace files; it reopens the app.
            self.root.destroy()

        def _poll_once(self):
            stale = False
            bars: list[QuotaBar] = []
            reset_date_utc = ""
            try:
                token = ensure_authenticated(self.config)
                data = fetch_user_data(token)
                bars = parse_quotas(data)
                reset_date_utc = data.get("quota_reset_date_utc", "")
                self.config.oauth_token = token

                for bar in bars:
                    to_fire = thresholds_to_fire(
                        bar.id, bar.percent_used, self.config.notified, reset_date_utc
                    )
                    for t in to_fire:
                        send_toast(
                            APP_NAME,
                            f"{bar.label}: {bar.percent_used:.0f}% used ({bar.remaining} remaining)",
                        )
                        self.config.notified = record_notified(
                            self.config.notified, bar.id, t, reset_date_utc
                        )
                save_config(self.config)
            except RuntimeError:
                stale = True
                bars = getattr(self, "_last_bars", [])
                if not bars:
                    self.root.title("Copilot Usage — Check gh auth")
                reset_date_utc = getattr(self, "_last_reset", "")

            if bars:
                self._last_bars = bars
                self._last_reset = reset_date_utc
                self.update_bars(bars, reset_date_utc, stale=stale)
                self.set_taskbar_progress(int(max(b.percent_used for b in bars)), 100)
            self._schedule_next_poll()

        def _schedule_next_poll(self):
            interval_ms = self.config.refresh_interval * 1000
            self.root.after(interval_ms, self._check_and_poll)

        def _check_and_poll(self):
            self._poll_once()

        def update_bars(self, bars: list[QuotaBar], reset_date_utc: str, stale: bool = False):
            needs_anchor = len(bars) != len(self._bar_widgets)
            if needs_anchor:
                self._rebuild_frame(bars)

            # Set images and text first so winfo_reqwidth includes image sizes
            self._bar_images.clear()
            for i, bar in enumerate(bars):
                color = bar_color(bar.percent_used)
                if self.config.display_mode != "standard" and len(bars) == 1:
                    overlay = f"{bar.percent_used:.0f}%"
                else:
                    overlay = f"{bar.label}: {bar.percent_used:.0f}%"
                if stale:
                    overlay += " ⚠"
                img = render_pill_bar(BAR_W, BAR_H, bar.percent_used, color, stale=stale)
                self._bar_images.append(img)
                w = self._bar_widgets[i]
                # Native Tk text over the pill (compound='center') — crisp,
                # bold ClearType matching the reference widget.
                w["bar_lbl"].configure(
                    image=img, text=overlay, compound="center",
                    font=FONT_BAR, fg="#ffffff",
                )
                self._show_tooltip(w["bar_lbl"], format_bar_count(bar))
                compact = len(bars) > 1 and self.config.display_mode != "standard"
                if reset_date_utc:
                    countdown = calc_reset_countdown(reset_date_utc)
                    reset_text = (
                        f"reset {countdown}"
                        if compact
                        else f"reset {reset_date_utc[:10]} ({countdown})"
                    )
                else:
                    reset_text = "reset unknown"
                w["reset_lbl"].configure(text=reset_text)

            if needs_anchor:
                # Measure after images are set so bar width is included
                self.root.update_idletasks()
                total_w = self._frame.winfo_reqwidth() + PAD * 2
                total_h = self._frame.winfo_reqheight() + PAD_V * 2
                if self.config.window_x >= 0 and self.config.window_y >= 0:
                    # Saved drag position — keep it, clamping only so it stays
                    # on-screen (overlapping the taskbar is allowed/intended).
                    x, y = clamp_to_screen(
                        self.root, self.config.window_x, self.config.window_y,
                        total_w, total_h
                    )
                    self.config.window_x, self.config.window_y = x, y
                    self.root.geometry(f"{total_w}x{total_h}+{x}+{y}")
                else:
                    anchor_to_taskbar(self.root, total_w, total_h)
                self.root.update_idletasks()
                self.config.window_width = self.root.winfo_width()
                self.config.window_height = self.root.winfo_height()
                save_config(self.config)

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

    # ── Launch ──────────────────────────────────────────────────────────────
    ctypes.windll.ole32.CoInitialize(None)
    _config = load_config()
    _app = WidgetApp(_config)
    if _config.window_x >= 0 and _config.window_y >= 0:
        _app.root.geometry(f"+{_config.window_x}+{_config.window_y}")
    _app.root.after(500, _app._poll_once)
    _app._schedule_update_check()
    _app.run()
