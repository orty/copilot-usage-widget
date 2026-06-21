import subprocess
from unittest.mock import MagicMock, patch
import pytest


def test_get_gh_token_success(W):
    """Test successful token retrieval from gh auth token."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "gho_testtoken123\n"
    with patch("subprocess.run", return_value=mock_result) as mock_run:
        token = W.get_gh_token()
        assert token == "gho_testtoken123"
        # Exact-match would break on the platform-specific no-window kwargs,
        # so assert the command and core kwargs explicitly.
        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        assert args[0] == ["gh", "auth", "token"]
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True
        assert kwargs["timeout"] == 10


def test_get_gh_token_gh_not_found(W):
    """Test graceful failure when gh CLI is not installed."""
    with patch("subprocess.run", side_effect=FileNotFoundError()):
        token = W.get_gh_token()
        assert token is None


def test_get_gh_token_empty_output(W):
    """Test when gh returns empty output (not authenticated)."""
    mock_result = MagicMock(returncode=0, stdout=" \n")
    with patch("subprocess.run", return_value=mock_result):
        token = W.get_gh_token()
        assert token is None


def test_get_gh_token_timeout(W):
    """Test timeout handling when gh command takes too long."""
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("gh", 10)):
        token = W.get_gh_token()
        assert token is None


def test_ensure_authenticated_cached_token(W):
    """Test that cached token is returned without further calls."""
    config = W.AppConfig(oauth_token="gho_cached_token")
    with patch("subprocess.run") as mock_run:
        token = W.ensure_authenticated(config)
        assert token == "gho_cached_token"
        mock_run.assert_not_called()


def test_ensure_authenticated_via_gh_token(W):
    """Test obtaining token from gh when cache is empty."""
    config = W.AppConfig(oauth_token="")
    mock_result = MagicMock(returncode=0, stdout="gho_new_token\n")
    with patch("subprocess.run", return_value=mock_result):
        token = W.ensure_authenticated(config)
        assert token == "gho_new_token"
        assert config.oauth_token == "gho_new_token"


def test_ensure_authenticated_via_gh_login_fallback(W):
    """Test full fallback: login prompt then token retrieval."""
    config = W.AppConfig(oauth_token="")

    # Simulate: first token call returns empty, login succeeds, second token returns token
    call_count = [0]

    def subprocess_side_effect(*args, **kwargs):
        call_count[0] += 1
        if len(args[0]) > 1 and args[0][1] == "login":
            return MagicMock(returncode=0, stdout="")
        else:  # "token" command
            # Return empty on first call, token on second call
            if call_count[0] == 1:
                return MagicMock(returncode=0, stdout="")
            else:
                return MagicMock(returncode=0, stdout="gho_logged_in_token\n")

    with patch("subprocess.run", side_effect=subprocess_side_effect) as mock_run:
        token = W.ensure_authenticated(config)
        assert token == "gho_logged_in_token"
        assert config.oauth_token == "gho_logged_in_token"
        # Verify both calls were made: token (empty), login, then token (success)
        assert mock_run.call_count == 3


def test_ensure_authenticated_raises_on_failure(W):
    """Test RuntimeError when all authentication methods fail."""
    config = W.AppConfig(oauth_token="")

    # All subprocess calls return empty token
    mock_result = MagicMock(returncode=0, stdout="")
    with patch("subprocess.run", return_value=mock_result):
        with pytest.raises(RuntimeError) as exc_info:
            W.ensure_authenticated(config)
        assert "Could not obtain GitHub token" in str(exc_info.value)
        assert "gh auth login" in str(exc_info.value)
