"""
Admin session (cookie) and login rate limiting by IP.
State can be persisted to JSON so it survives restart (set LOGIN_RATE_LIMIT_FILE).
"""
import hmac
import json
import logging
import time
from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse

import config

log = logging.getLogger(__name__)

# Login rate limit state: ip -> {"failed": int, "locked_until": float}
_login_rate_limit: dict[str, dict] = {}
_loaded = False


def _rate_limit_path() -> Path | None:
    if not config.LOGIN_RATE_LIMIT_FILE:
        return None
    return Path(config.LOGIN_RATE_LIMIT_FILE)


def _load_rate_limit() -> None:
    global _loaded, _login_rate_limit
    if _loaded:
        return
    _loaded = True
    p = _rate_limit_path()
    if not p or not p.exists():
        return
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return
        now = time.time()
        for ip, rec in data.items():
            if isinstance(rec, dict) and isinstance(rec.get("locked_until"), (int, float)):
                if rec["locked_until"] > now:
                    _login_rate_limit[ip] = {"failed": int(rec.get("failed", 0)), "locked_until": float(rec["locked_until"])}
        if _login_rate_limit:
            log.info("Loaded login rate limit state for %d IP(s) from %s", len(_login_rate_limit), p)
    except Exception as e:
        log.warning("Could not load login rate limit from %s: %s", p, e)


def _save_rate_limit() -> None:
    p = _rate_limit_path()
    if not p:
        return
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(_login_rate_limit, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        log.warning("Could not save login rate limit to %s: %s", p, e)


def client_ip(request: Request) -> str:
    """Client IP for rate limiting (X-Forwarded-For when behind proxy)."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def admin_session_token() -> str:
    """Session cookie value when admin password is set (HMAC)."""
    if not config.ADMIN_PASSWORD:
        return ""
    return hmac.new(config.ADMIN_PASSWORD.encode(), b"line-backup-admin", "sha256").hexdigest()


def admin_authenticated(request: Request) -> bool:
    """True if request has valid admin session cookie."""
    if not config.ADMIN_PASSWORD:
        return True
    return request.cookies.get(config.ADMIN_COOKIE_NAME) == admin_session_token()


def refresh_admin_cookie(response: HTMLResponse) -> HTMLResponse:
    """Set session cookie on response (sliding: 1 hour)."""
    if not config.ADMIN_PASSWORD:
        return response
    response.set_cookie(
        config.ADMIN_COOKIE_NAME,
        admin_session_token(),
        max_age=config.ADMIN_SESSION_SECONDS,
        path="/",
        httponly=True,
        samesite="lax",
    )
    return response


def get_login_lock_error_html(request: Request) -> str | None:
    """
    If this IP is currently locked after too many failures, return error HTML fragment.
    Otherwise return None.
    """
    _load_rate_limit()
    ip = client_ip(request)
    now = time.time()
    rec = _login_rate_limit.get(ip, {"failed": 0, "locked_until": 0.0})
    if rec["locked_until"] <= now:
        return None
    mins = max(1, int((rec["locked_until"] - now) / 60))
    return f'<p class="msg msg--error">Too many failed attempts. Try again in {mins} minute(s).</p>'


def check_login_and_update(request: Request, password: str) -> tuple[bool, str | None]:
    """
    Check password and update rate limit state.
    Returns (success, error_html). If success is True, error_html is None and the IP record is cleared.
    """
    _load_rate_limit()
    ip = client_ip(request)
    now = time.time()
    rec = _login_rate_limit.get(ip, {"failed": 0, "locked_until": 0.0})
    if rec["locked_until"] > 0 and rec["locked_until"] <= now:
        rec = {"failed": 0, "locked_until": 0.0}
    if password and password == config.ADMIN_PASSWORD:
        _login_rate_limit.pop(ip, None)
        _save_rate_limit()
        return True, None
    rec["failed"] = rec.get("failed", 0) + 1
    if rec["failed"] >= config.LOGIN_MAX_FAILED:
        rec["locked_until"] = now + config.LOGIN_LOCK_SECONDS
        mins = config.LOGIN_LOCK_SECONDS // 60
        err = f'<p class="msg msg--error">Too many failed attempts. This IP is locked for {mins} minutes.</p>'
    else:
        left = config.LOGIN_MAX_FAILED - rec["failed"]
        err = f'<p class="msg msg--error">Wrong password. {left} attempt(s) left before lockout.</p>'
    _login_rate_limit[ip] = rec
    _save_rate_limit()
    return False, err
