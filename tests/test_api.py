import json
import pytest
from unittest.mock import MagicMock, patch


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


def test_humanize_label_in_map(W):
    """humanize_label returns mapped value if quota_id in LABEL_MAP."""
    result = W.humanize_label("premium_interactions")
    assert result == "Premium"


def test_humanize_label_fallback(W):
    """humanize_label converts unmapped quota_id to title case."""
    result = W.humanize_label("custom_quota_name")
    assert result == "Custom Quota Name"


def test_humanize_label_single_word(W):
    """humanize_label handles single-word quota_id."""
    result = W.humanize_label("chat")
    assert result == "Chat"


def test_fetch_user_data_success(W):
    """fetch_user_data calls curl with correct headers and returns parsed JSON."""
    mock_result = MagicMock(returncode=0, stdout=json.dumps(SAMPLE_RESPONSE).encode())
    with patch("subprocess.run", return_value=mock_result):
        data = W.fetch_user_data("gho_token")
        assert data["login"] == "testuser"
        assert "quota_snapshots" in data


def test_fetch_user_data_curl_failure(W):
    """fetch_user_data raises RuntimeError on curl failure."""
    mock_result = MagicMock(returncode=22, stderr=b"404 Not Found")
    with patch("subprocess.run", return_value=mock_result):
        with pytest.raises(RuntimeError, match="curl failed"):
            W.fetch_user_data("gho_bad_token")


def test_parse_quotas_skips_unlimited(W):
    """parse_quotas skips snapshots where unlimited == True."""
    data = SAMPLE_RESPONSE
    quotas = W.parse_quotas(data)
    assert len(quotas) == 1
    assert quotas[0].id == "premium_interactions"


def test_parse_quotas_computes_percent_used(W):
    """parse_quotas computes percent_used from percent_remaining."""
    data = SAMPLE_RESPONSE
    quotas = W.parse_quotas(data)
    quota = quotas[0]
    assert quota.percent_used == 98.2  # 100.0 - 1.8


def test_parse_quotas_sets_all_fields(W):
    """parse_quotas populates all QuotaBar fields correctly."""
    data = SAMPLE_RESPONSE
    quotas = W.parse_quotas(data)
    quota = quotas[0]
    assert quota.id == "premium_interactions"
    assert quota.label == "Premium"
    assert quota.entitlement == 5000
    assert quota.remaining == 90
    assert quota.overage_count == 3
    assert quota.overage_permitted is True


def test_quota_bar_dataclass(W):
    """QuotaBar is a dataclass with all required fields."""
    qb = W.QuotaBar(
        id="test_quota",
        label="Test Quota",
        entitlement=1000,
        remaining=100,
        percent_used=90.0,
        overage_count=5,
        overage_permitted=False,
    )
    assert qb.id == "test_quota"
    assert qb.label == "Test Quota"
    assert qb.entitlement == 1000
    assert qb.remaining == 100
    assert qb.percent_used == 90.0
    assert qb.overage_count == 5
    assert qb.overage_permitted is False
