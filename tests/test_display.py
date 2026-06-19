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
    now = datetime.now(timezone.utc)
    future = now + timedelta(days=11, hours=12)
    with patch('widget.datetime') as mock_dt:
        mock_dt.now.return_value = now
        mock_dt.fromisoformat = datetime.fromisoformat
        result = W.calc_reset_countdown(future.isoformat())
        assert result == "11d 12h"


def test_calc_reset_countdown_hours(W):
    now = datetime.now(timezone.utc)
    future = now + timedelta(hours=3, minutes=45)
    with patch('widget.datetime') as mock_dt:
        mock_dt.now.return_value = now
        mock_dt.fromisoformat = datetime.fromisoformat
        result = W.calc_reset_countdown(future.isoformat())
        assert result == "3h 45m"


def test_calc_reset_countdown_minutes(W):
    now = datetime.now(timezone.utc)
    future = now + timedelta(minutes=23)
    with patch('widget.datetime') as mock_dt:
        mock_dt.now.return_value = now
        mock_dt.fromisoformat = datetime.fromisoformat
        result = W.calc_reset_countdown(future.isoformat())
        assert result == "23m"


def test_calc_reset_countdown_past(W):
    now = datetime.now(timezone.utc)
    past = now - timedelta(minutes=1)
    with patch('widget.datetime') as mock_dt:
        mock_dt.now.return_value = now
        mock_dt.fromisoformat = datetime.fromisoformat
        assert W.calc_reset_countdown(past.isoformat()) == "reset now"


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
