"""Copilot Usage Widget — monitors GitHub Copilot Enterprise premium interaction credits."""
from __future__ import annotations

import ctypes
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
    try:
        subprocess.run(["gh", "auth", "login", "--web"], check=False, timeout=300)
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


# ── Guard — everything below this line only runs when launched directly ────────
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
        _, _, _, th = get_taskbar_rect()
        screen_h = root.winfo_screenheight()
        # Place bottom-left above taskbar
        x = 4
        y = screen_h - th - widget_h - 4
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
            'CreateToastNotifier("Copilot Usage").Show($n)'
        )
        subprocess.Popen(
            ["powershell", "-WindowStyle", "Hidden", "-Command", ps],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

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
            self._last_bars: list = []
            self._last_reset: str = ""

            self._frame = tk.Frame(self.root, bg=BG)
            self._frame.pack(padx=PAD, pady=PAD)
            self._bar_widgets: list[dict] = []
            self._drag_x = 0
            self._drag_y = 0

            self.root.after(100, self._post_init_win32)

        def _bind_widgets(self, widget: tk.Widget) -> None:
            """Recursively bind right-click and drag to widget and all children."""
            widget.bind("<Button-3>", self._show_context_menu)
            widget.bind("<ButtonPress-1>", self._start_drag)
            widget.bind("<B1-Motion>", self._do_drag)
            for child in widget.winfo_children():
                self._bind_widgets(child)

        def _start_drag(self, event: tk.Event) -> None:
            self._drag_x = event.x_root - self.root.winfo_x()
            self._drag_y = event.y_root - self.root.winfo_y()

        def _do_drag(self, event: tk.Event) -> None:
            x = event.x_root - self._drag_x
            y = event.y_root - self._drag_y
            self.root.geometry(f"+{x}+{y}")

        def _post_init_win32(self):
            hwnd = int(self.root.wm_frame(), 16)
            setup_window_flags(hwnd)
            self._hwnd = hwnd
            self._taskbar_progress = self._setup_taskbar_progress()
            # Position will be set on first update_bars call

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

        def _rebuild_essential_frame(self, bars: list[QuotaBar]):
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
            self._dot_lbl = tk.Label(self._frame, bg=BG, width=DOT_SIZE, height=DOT_SIZE)
            self._dot_lbl.grid(row=0, column=len(bars), padx=(PAD, 0), sticky="s")
            self._bind_widgets(self._frame)

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
            menu = tk.Menu(self.root, tearoff=0, bg="#2d2d2d", fg=FG, activebackground="#444444")
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
                            "Copilot Usage",
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
                reset_text = f"reset {reset_date_utc[:10]} ({calc_reset_countdown(reset_date_utc)})" if reset_date_utc else "reset unknown"
                w["reset_lbl"].configure(text=reset_text)

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
    _app.root.after(500, _app._poll_once)
    _app.run()
