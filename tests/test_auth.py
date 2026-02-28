"""Tests for auth module (login and rate limit)."""
import pytest
from unittest.mock import MagicMock

import auth


@pytest.fixture(autouse=True)
def auth_temp_file(monkeypatch, tmp_path):
    """Use temp file for rate limit state so tests don't touch real data."""
    monkeypatch.setattr("auth.config.LOGIN_RATE_LIMIT_FILE", str(tmp_path / "login_limit.json"))
    monkeypatch.setattr("auth._loaded", False)


def test_client_ip_from_request():
    req = MagicMock()
    req.headers = {"X-Forwarded-For": " 192.168.1.1 , 10.0.0.1"}
    req.client = None
    assert auth.client_ip(req) == "192.168.1.1"
    req.headers = {}
    req.client = MagicMock(host="127.0.0.1")
    assert auth.client_ip(req) == "127.0.0.1"


def test_admin_session_token_empty_when_no_password(monkeypatch):
    monkeypatch.setattr("auth.config.ADMIN_PASSWORD", "")
    assert auth.admin_session_token() == ""


def test_check_login_and_update_success(monkeypatch):
    monkeypatch.setattr("auth.config.ADMIN_PASSWORD", "secret")
    req = MagicMock()
    req.headers = {}
    req.client = MagicMock(host="1.2.3.4")
    ok, err = auth.check_login_and_update(req, "secret")
    assert ok is True
    assert err is None


def test_check_login_and_update_wrong_password(monkeypatch):
    monkeypatch.setattr("auth.config.ADMIN_PASSWORD", "secret")
    monkeypatch.setattr("auth.config.LOGIN_MAX_FAILED", 5)
    req = MagicMock()
    req.headers = {}
    req.client = MagicMock(host="1.2.3.5")
    ok, err = auth.check_login_and_update(req, "wrong")
    assert ok is False
    assert err is not None
    assert "Wrong password" in err or "attempt" in err
