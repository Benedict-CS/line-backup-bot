"""
LINE Bot: File transfer & archive relay to Nextcloud.
Receives image/video/audio/file messages, downloads content, uploads to Nextcloud via WebDAV.
"""
import json
import logging
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# All times in Taipei (folder date + filename time)
TZ = ZoneInfo("Asia/Taipei")

from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from linebot import LineBotApi, WebhookHandler
from linebot.models import (
    MessageEvent,
    ImageMessage,
    VideoMessage,
    AudioMessage,
    FileMessage,
    TextMessage,
    TextSendMessage,
)
from linebot.exceptions import InvalidSignatureError
import requests

load_dotenv()

# LINE
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "")
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")

# Nextcloud WebDAV
NEXTCLOUD_URL = os.getenv("NEXTCLOUD_URL", "").rstrip("/")
NEXTCLOUD_USER = os.getenv("NEXTCLOUD_USER", "")
NEXTCLOUD_PASSWORD = os.getenv("NEXTCLOUD_PASSWORD", "")
# Base path under user's WebDAV root, e.g. LINE_Backup (no leading/trailing slashes)
NEXTCLOUD_BASE_PATH = (os.getenv("NEXTCLOUD_BASE_PATH", "LINE_Backup") or "LINE_Backup").strip("/")
# When true: reply "收到檔案..." and push success/error (uses 2 sent messages per file). When false: silent, no reply/push (saves quota).
ENABLE_LINE_REPLIES = os.getenv("ENABLE_LINE_REPLIES", "false").strip().lower() in ("1", "true", "yes")
# Optional: persist source selection to file so it survives restart. Empty = disabled.
SOURCE_STATE_FILE = (os.getenv("SOURCE_STATE_FILE", "data/source_state.json") or "").strip()
# Optional: max file size in MB (0 = no limit). Larger files are skipped.
MAX_FILE_SIZE_MB = float(os.getenv("MAX_FILE_SIZE_MB", "0") or "0")


def _safe_folder_name(name: str) -> str:
    """Allow only alphanumeric, underscore, hyphen; max 32 chars."""
    s = "".join(c if c.isalnum() or c in "_-" else "_" for c in name)
    return s[:32] or "other"


# Source list: number -> folder name. e.g. 1:Amigo,2:Ben,3:Mom . No number / unknown = save under "other"
SOURCE_MAP: dict[str, str] = {}
for part in (os.getenv("SOURCE_MAP", "") or "").strip().split(","):
    part = part.strip()
    if ":" in part:
        k, v = part.split(":", 1)
        k, v = k.strip(), v.strip()
        if k and v:
            SOURCE_MAP[k] = _safe_folder_name(v)

# Per-user last chosen source: user_id -> folder name (e.g. Amigo). Default "other". Load from file if SOURCE_STATE_FILE set.
_user_source: dict[str, str] = {}


def _load_source_state() -> None:
    if not SOURCE_STATE_FILE:
        return
    path = Path(SOURCE_STATE_FILE)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                _user_source.update(data)
                log.info("Loaded source state from %s (%d entries)", SOURCE_STATE_FILE, len(data))
        except Exception as e:
            log.warning("Could not load source state from %s: %s", SOURCE_STATE_FILE, e)


def _save_source_state() -> None:
    if not SOURCE_STATE_FILE:
        return
    path = Path(SOURCE_STATE_FILE)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_user_source, ensure_ascii=False, indent=0), encoding="utf-8")
    except Exception as e:
        log.warning("Could not save source state to %s: %s", SOURCE_STATE_FILE, e)


_load_source_state()

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

app = FastAPI(title="LINE to Nextcloud Backup Bot")


def _nextcloud_webdav_root() -> str:
    """User's WebDAV root. Use legacy webdav endpoint so parent (root) is clearly the auth user's root."""
    return f"{NEXTCLOUD_URL.rstrip('/')}/remote.php/webdav/"


def _nextcloud_webdav_url(path: str) -> str:
    """Build full WebDAV URL (path = folder/file under user root, e.g. LINE_Backup/2026-02-24/file.jpg)."""
    root = _nextcloud_webdav_root()
    path = path.strip("/")
    return f"{root.rstrip('/')}/{path}" if path else root


def guess_extension(message_type: str) -> str:
    """Guess file extension from LINE message type."""
    m = {
        "image": ".jpg",
        "video": ".mp4",
        "audio": ".m4a",
        "file": "",
    }
    return m.get(message_type, "")


def upload_to_nextcloud(
    suggested_name: str,
    message_type: str,
    source_folder: str = "other",
    *,
    content: bytes | None = None,
    file_path: Path | None = None,
) -> str:
    """
    Upload to Nextcloud under LINE_Backup/{source_folder}/YYYY-MM-DD/ (Taipei time).
    Provide either content (bytes) or file_path; file_path is streamed to reduce memory.
    """
    if (content is None) == (file_path is None):
        raise ValueError("Provide exactly one of content or file_path")
    now = datetime.now(TZ)
    date_folder = now.strftime("%Y-%m-%d")
    date_compact = now.strftime("%Y%m%d")
    time_compact = now.strftime("%H%M%S")
    ms = now.strftime("%f")[:3]  # milliseconds
    ext = guess_extension(message_type)
    if not ext and suggested_name:
        ext = Path(suggested_name).suffix or ""
    prefix = {"image": "img", "video": "vid", "audio": "aud", "file": "file"}.get(message_type, "file")
    safe_name = f"{prefix}_{date_compact}_{time_compact}_{ms}{ext}"
    base = (NEXTCLOUD_BASE_PATH or "LINE_Backup").strip("/")
    source_safe = _safe_folder_name(source_folder) or "other"
    remote_dir = f"{base}/{source_safe}/{date_folder}"
    remote_path = f"{remote_dir}/{safe_name}"

    auth = (NEXTCLOUD_USER, NEXTCLOUD_PASSWORD)
    last_err = None
    for attempt in range(3):
        try:
            for part in [base, f"{base}/{source_safe}", remote_dir]:
                url_dir = _nextcloud_webdav_url(part + "/")
                r = requests.request("MKCOL", url_dir, auth=auth, timeout=30)
                if r.status_code not in (201, 204, 405):
                    raise RuntimeError(f"MKCOL {part}: {r.status_code} {r.text[:200]}")
            url_file = _nextcloud_webdav_url(remote_path)
            if file_path is not None:
                with open(file_path, "rb") as f:
                    r3 = requests.put(url_file, data=f, auth=auth, timeout=120)
            else:
                r3 = requests.put(url_file, data=content, auth=auth, timeout=120)
            if r3.status_code not in (200, 201, 204):
                raise RuntimeError(f"PUT {remote_path}: {r3.status_code} {r3.text[:200]}")
            return remote_path
        except Exception as e:
            last_err = e
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
    raise last_err


@app.get("/")
def root():
    return {"service": "LINE to Nextcloud Backup Bot", "health": "ok"}


@app.get("/health")
def health():
    """Check bot and Nextcloud connectivity. Returns 200 if Nextcloud reachable, else 503."""
    try:
        root_url = _nextcloud_webdav_root()
        auth = (NEXTCLOUD_USER, NEXTCLOUD_PASSWORD)
        r = requests.request("PROPFIND", root_url, auth=auth, timeout=10, headers={"Depth": "0"})
        if r.status_code in (200, 207):
            return {"status": "ok", "nextcloud": "ok"}
    except Exception as e:
        log.debug("Health check Nextcloud: %s", e)
    return JSONResponse(
        status_code=503,
        content={"status": "degraded", "nextcloud": "error"},
    )


@app.get("/debug-webdav")
def debug_webdav():
    """Test WebDAV connection and folder creation (uses same requests as upload)."""
    steps = []
    try:
        base = (NEXTCLOUD_BASE_PATH or "LINE_Backup").strip("/")
        url_base = _nextcloud_webdav_url(base + "/")
        steps.append({"step": "config", "url_base_dir": url_base})

        auth = (NEXTCLOUD_USER, NEXTCLOUD_PASSWORD)

        # MKCOL base folder
        r = requests.request("MKCOL", url_base, auth=auth, timeout=30)
        steps.append({"step": "mkdir_base", "status_code": r.status_code, "reason": r.reason})
        if r.status_code not in (201, 204, 405):
            steps.append({"step": "mkdir_base_error", "text": r.text[:300]})

        return {"ok": True, "steps": steps}
    except Exception as e:
        steps.append({"step": "exception", "error": str(e)})
        return {"ok": False, "steps": steps}


def _handle_media_message(event):
    """Handle image/video/audio/file: optional reply/push (ENABLE_LINE_REPLIES), download, upload to Nextcloud."""
    msg = event.message
    reply_token = event.reply_token
    message_id = msg.id
    message_type = msg.type
    user_id = getattr(event.source, "user_id", None) if hasattr(event, "source") else None

    if ENABLE_LINE_REPLIES:
        line_bot_api.reply_message(
            reply_token,
            TextSendMessage(text="收到檔案，準備下載..."),
        )

    tmp_path = None
    try:
        content_response = line_bot_api.get_message_content(message_id)
        fd, tmp_path = tempfile.mkstemp(prefix="line_backup_", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                for chunk in content_response.iter_content(chunk_size=65536):
                    f.write(chunk)
        except Exception:
            os.unlink(tmp_path)
            tmp_path = None
            raise
        tmp_path = Path(tmp_path)
        size = tmp_path.stat().st_size
        if size == 0:
            if ENABLE_LINE_REPLIES and user_id:
                line_bot_api.push_message(user_id, TextSendMessage(text="無法取得檔案內容。"))
            tmp_path.unlink(missing_ok=True)
            return

        if MAX_FILE_SIZE_MB > 0:
            size_mb = size / (1024 * 1024)
            if size_mb > MAX_FILE_SIZE_MB:
                log.warning("File too large: %.2f MB (max %.2f MB)", size_mb, MAX_FILE_SIZE_MB)
                if ENABLE_LINE_REPLIES and user_id:
                    line_bot_api.push_message(
                        user_id,
                        TextSendMessage(text=f"檔案過大 ({size_mb:.1f} MB)，已略過（上限 {MAX_FILE_SIZE_MB:.0f} MB）"),
                    )
                tmp_path.unlink(missing_ok=True)
                return

        suggested_name = getattr(msg, "file_name", None) or f"{message_type}_{message_id}"
        source_folder = _user_source.get(user_id, "other")
        try:
            remote_path = upload_to_nextcloud(
                suggested_name, message_type, source_folder=source_folder, file_path=tmp_path
            )
        finally:
            tmp_path.unlink(missing_ok=True)
        log.info("Backup ok: %s", remote_path)
        if ENABLE_LINE_REPLIES and user_id:
            line_bot_api.push_message(
                user_id,
                TextSendMessage(text="✅ 檔案已成功備份至 Nextcloud！"),
            )
    except Exception as e:
        log.exception("Backup failed")
        if ENABLE_LINE_REPLIES and user_id:
            line_bot_api.push_message(
                user_id,
                TextSendMessage(text=f"❌ 備份失敗：{str(e)[:500]}"),
            )


@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    """Set source folder for next media: send "1" -> Amigo, "2" -> Ben, ...; "0" or "other" -> other."""
    text = (event.message.text or "").strip()
    user_id = getattr(event.source, "user_id", None) if hasattr(event, "source") else None
    if not user_id:
        return
    if text.lower() in ("0", "other", "reset", "預設"):
        _user_source[user_id] = "other"
        _save_source_state()
        if ENABLE_LINE_REPLIES:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="已設為：other"))
        return
    if text in SOURCE_MAP:
        _user_source[user_id] = SOURCE_MAP[text]
        _save_source_state()
        if ENABLE_LINE_REPLIES:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=f"已設為：{SOURCE_MAP[text]}"),
            )


# Register handler for media messages (SDK 2.x uses WebhookHandler.add)
@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    _handle_media_message(event)


@handler.add(MessageEvent, message=VideoMessage)
def handle_video(event):
    _handle_media_message(event)


@handler.add(MessageEvent, message=AudioMessage)
def handle_audio(event):
    _handle_media_message(event)


@handler.add(MessageEvent, message=FileMessage)
def handle_file(event):
    _handle_media_message(event)


@app.post("/callback")
async def callback(request: Request):
    body = await request.body()
    signature = request.headers.get("X-Line-Signature", "")

    if not signature or not LINE_CHANNEL_SECRET or not LINE_CHANNEL_ACCESS_TOKEN:
        raise HTTPException(status_code=500, detail="LINE credentials not configured")

    try:
        handler.handle(body.decode("utf-8"), signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    return "OK"
