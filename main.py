"""
LINE Bot: File transfer & archive relay to Nextcloud.
Receives image/video/audio/file messages, downloads content, uploads to Nextcloud via WebDAV.
"""
import base64
import hmac
import hashlib
import asyncio
import json
import logging
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

import config
import source_map
import nextcloud
import auth
import handlers
import stats

from fastapi import FastAPI, Request, HTTPException, Form
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from linebot import LineBotApi, WebhookHandler
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# Load state at startup
source_map.load_source_map()
source_map.load_source_state()

line_bot_api = LineBotApi(config.LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(config.LINE_CHANNEL_SECRET)
handlers.register(handler, line_bot_api)

app = FastAPI(title="LINE to Nextcloud Backup Bot")

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def _render_template(name: str, **kwargs: str) -> str:
    path = _TEMPLATES_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Template {name} not found at {path}")
    t = path.read_text(encoding="utf-8")
    for k, v in kwargs.items():
        t = t.replace("{{ " + k + " }}", (v or ""))
    return t


def _html_esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _validate_line_signature(body: bytes, signature: str) -> bool:
    """Validate X-Line-Signature (HMAC-SHA256 of body, base64). Return True if valid."""
    if not signature or not config.LINE_CHANNEL_SECRET:
        return False
    gen = hmac.new(
        config.LINE_CHANNEL_SECRET.encode("utf-8"),
        body,
        hashlib.sha256,
    ).digest()
    expected = base64.b64encode(gen).decode("utf-8")
    return hmac.compare_digest(signature.encode("utf-8"), expected.encode("utf-8"))


def _run_webhook_handlers(body_str: str, signature: str) -> None:
    """Run LINE webhook handlers (sync, blocking). Call from executor only."""
    try:
        handler.handle(body_str, signature)
    except Exception as e:
        log.exception("Webhook handler error: %s", e)


def _config_check_html() -> str:
    """HTML block for missing .env (required + recommended). Empty if all set."""
    missing_req, missing_rec = config.get_missing_config()
    if not missing_req and not missing_rec:
        return ""
    parts = []
    if missing_req:
        parts.append("<strong>Missing required:</strong> " + ", ".join(missing_req))
    if missing_rec:
        parts.append("<strong>Recommended:</strong> " + ", ".join(missing_rec))
    return '<div class="config-check"><p>' + " · ".join(parts) + "</p><p>Set these in <code>.env</code> and restart.</p></div>"


def _landing_html() -> str:
    nextcloud_link = ""
    if config.NEXTCLOUD_URL:
        nextcloud_link = f'<a href="{_html_esc(config.NEXTCLOUD_URL)}" class="btn btn--primary" target="_blank" rel="noopener">Open Nextcloud ↗</a>'
    github_foot = ""
    if config.GITHUB_REPO:
        github_foot = f' · <a href="{_html_esc(config.GITHUB_REPO)}" target="_blank" rel="noopener">GitHub</a>'
    config_check = _config_check_html()
    return _render_template("landing.html", nextcloud_link=nextcloud_link, github_foot=github_foot, config_check=config_check)


def _admin_html(message: str = "", is_error: bool = False) -> str:
    def _sort_key(item: tuple[str, str]):
        k = item[0]
        return (0, int(k)) if k.isdigit() else (1, k)
    rows_data = sorted(source_map.SOURCE_MAP.items(), key=_sort_key) if source_map.SOURCE_MAP else [("1", "Amigo"), ("2", "Ben")]
    rows_json = json.dumps([[k, v] for k, v in rows_data])
    msg_html = f'<p class="msg msg--{"error" if is_error else "ok"}">{message}</p>' if message else ""
    auth_warn = ""
    if not config.ADMIN_PASSWORD:
        auth_warn = '<p class="msg msg--warn">Admin password not set. Set <code>ADMIN_PASSWORD</code> in .env to protect this page.</p>'
    logout_link = '<span class="logout"><a href="/admin/logout">Log out</a></span>' if config.ADMIN_PASSWORD else ""
    config_check = _config_check_html()
    return _render_template(
        "admin.html",
        logout_note="",
        auth_warn=auth_warn,
        msg_html=msg_html,
        rows_json=rows_json,
        logout_link=logout_link,
        session_seconds=str(config.ADMIN_SESSION_SECONDS) if config.ADMIN_PASSWORD else "0",
        config_check=config_check,
    )


@app.get("/")
def root(request: Request):
    if "application/json" in (request.headers.get("accept") or ""):
        return {"service": "LINE to Nextcloud Backup Bot", "health": "ok"}
    return HTMLResponse(content=_landing_html())


@app.get("/health")
async def health():
    nextcloud_ok = await nextcloud.check_nextcloud_async(timeout=10.0)
    if nextcloud_ok:
        return {"status": "ok", "nextcloud": "ok"}
    return JSONResponse(status_code=503, content={"status": "degraded", "nextcloud": "error"})


@app.get("/status", response_class=HTMLResponse)
async def status_page(request: Request):
    """Simple status: LINE config, Nextcloud, last backup, backups today."""
    line_ok = bool(config.LINE_CHANNEL_SECRET and config.LINE_CHANNEL_ACCESS_TOKEN)
    nextcloud_ok = await nextcloud.check_nextcloud_async(timeout=8.0)
    last_at = stats.get_last_backup_at()
    last_backup_str = last_at.strftime("%Y-%m-%d %H:%M") if last_at else "—"
    backups_today = stats.get_backups_today()
    return HTMLResponse(
        content=_render_template(
            "status.html",
            line_ok="OK" if line_ok else "Missing",
            nextcloud_ok="OK" if nextcloud_ok else "Error",
            line_class="ok" if line_ok else "err",
            nextcloud_class="ok" if nextcloud_ok else "err",
            last_backup=last_backup_str,
            backups_today=str(backups_today),
        )
    )


@app.get("/admin/logout")
def admin_logout():
    r = RedirectResponse(url="/", status_code=302)
    r.delete_cookie(config.ADMIN_COOKIE_NAME, path="/")
    return r


@app.get("/admin/login", response_class=HTMLResponse)
def admin_login_get(request: Request):
    if auth.admin_authenticated(request):
        return RedirectResponse(url="/admin", status_code=302)
    return HTMLResponse(content=_render_template("login.html", error_html=""))


@app.post("/admin/login", response_class=HTMLResponse)
def admin_login_post(request: Request, password: str = Form("")):
    if not config.ADMIN_PASSWORD:
        return RedirectResponse(url="/admin", status_code=302)
    lock_err = auth.get_login_lock_error_html(request)
    if lock_err:
        return HTMLResponse(content=_render_template("login.html", error_html=lock_err))
    success, err_html = auth.check_login_and_update(request, password)
    if success:
        r = RedirectResponse(url="/admin", status_code=302)
        r.set_cookie(
            config.ADMIN_COOKIE_NAME,
            auth.admin_session_token(),
            max_age=config.ADMIN_SESSION_SECONDS,
            path="/",
            httponly=True,
            samesite="lax",
        )
        return r
    return HTMLResponse(content=_render_template("login.html", error_html=err_html))


@app.get("/admin", response_class=HTMLResponse)
def admin_get(request: Request):
    if not auth.admin_authenticated(request):
        return RedirectResponse(url="/admin/login", status_code=302)
    return auth.refresh_admin_cookie(HTMLResponse(content=_admin_html()))


@app.post("/admin", response_class=HTMLResponse)
def admin_post(request: Request, mapping: str = Form("")):
    if not auth.admin_authenticated(request):
        return RedirectResponse(url="/admin/login", status_code=302)
    if not config.SOURCE_MAP_FILE:
        return auth.refresh_admin_cookie(HTMLResponse(content=_admin_html("SOURCE_MAP_FILE not set; cannot save.")))
    data: dict[str, str] = {}
    for line in mapping.strip().splitlines():
        line = line.strip()
        if ":" in line:
            k, v = line.split(":", 1)
            k, v = k.strip(), v.strip()
            if k and v:
                data[k] = source_map.safe_folder_name(v)
    try:
        path = Path(config.SOURCE_MAP_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        source_map.load_source_map()
        return auth.refresh_admin_cookie(HTMLResponse(content=_admin_html("Saved. Mapping is active.")))
    except PermissionError as e:
        log.warning("Permission denied saving source map: %s", e)
        hint = "On the server run: sudo chown -R $(id -u):$(id -g) data  then restart the container (docker compose restart)."
        return auth.refresh_admin_cookie(HTMLResponse(content=_admin_html(f"Cannot save: permission denied. {hint}", is_error=True)))
    except Exception as e:
        log.exception("Failed to save source map")
        return auth.refresh_admin_cookie(HTMLResponse(content=_admin_html(f"Error: {e}", is_error=True)))


@app.get("/debug-webdav")
def debug_webdav():
    steps = []
    try:
        base = (config.NEXTCLOUD_BASE_PATH or "LINE_Backup").strip("/")
        url_base = nextcloud.webdav_url(base + "/")
        steps.append({"step": "config", "url_base_dir": url_base})
        r = requests.request(
            "MKCOL", url_base,
            auth=(config.NEXTCLOUD_USER, config.NEXTCLOUD_PASSWORD),
            timeout=30
        )
        steps.append({"step": "mkdir_base", "status_code": r.status_code, "reason": r.reason})
        if r.status_code not in (201, 204, 405):
            steps.append({"step": "mkdir_base_error", "text": r.text[:300]})
        return {"ok": True, "steps": steps}
    except Exception as e:
        steps.append({"step": "exception", "error": str(e)})
        return {"ok": False, "steps": steps}


@app.post("/callback")
async def callback(request: Request):
    body = await request.body()
    signature = request.headers.get("X-Line-Signature", "")

    if not signature or not config.LINE_CHANNEL_SECRET or not config.LINE_CHANNEL_ACCESS_TOKEN:
        raise HTTPException(status_code=500, detail="LINE credentials not configured")

    if not _validate_line_signature(body, signature):
        raise HTTPException(status_code=400, detail="Invalid signature")

    body_str = body.decode("utf-8")
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, lambda: _run_webhook_handlers(body_str, signature))
    return "OK"
