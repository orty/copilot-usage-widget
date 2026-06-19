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
