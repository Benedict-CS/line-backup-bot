"""
LINE webhook event handlers: text (source switch + link backup), image, video, audio, file.
"""
import os
import re
import tempfile
from pathlib import Path

from linebot.models import (
    MessageEvent,
    ImageMessage,
    VideoMessage,
    AudioMessage,
    FileMessage,
    TextMessage,
    TextSendMessage,
)

import config
import nextcloud
import source_map
import stats
import hash_store

# Set by register(); handlers use this
line_bot_api = None

# Skip duplicate webhook delivery (LINE may retry)
_processed_message_ids: set[str] = set()
_MAX_PROCESSED_IDS = 10000

_URL_PATTERN = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)

import logging
log = logging.getLogger(__name__)


def _extract_urls(text: str) -> list[str]:
    return _URL_PATTERN.findall(text)


def _backup_links_to_nextcloud(text: str, source_folder: str, user_id: str | None) -> None:
    body = text.strip()
    if not body:
        return
    try:
        remote_path = nextcloud.upload_to_nextcloud(
            "link.txt", "link", source_folder=source_folder, content=body.encode("utf-8")
        )
        log.info("Link backup ok: %s", remote_path)
        stats.record_backup()
        if config.ENABLE_LINE_REPLIES and user_id and line_bot_api:
            line_bot_api.push_message(user_id, TextSendMessage(text="✅ 連結已備份至 Nextcloud！"))
    except Exception as e:
        log.exception("Link backup failed")
        if config.ENABLE_LINE_REPLIES and user_id and line_bot_api:
            line_bot_api.push_message(user_id, TextSendMessage(text=f"❌ 連結備份失敗：{str(e)[:500]}"))


def _handle_media_message(event):
    msg = event.message
    reply_token = event.reply_token
    message_id = msg.id
    message_type = msg.type
    user_id = getattr(event.source, "user_id", None) if hasattr(event, "source") else None

    if message_id in _processed_message_ids:
        log.info("Skip duplicate message_id: %s", message_id)
        return
    if len(_processed_message_ids) >= _MAX_PROCESSED_IDS:
        _processed_message_ids.clear()
    _processed_message_ids.add(message_id)

    if config.ENABLE_LINE_REPLIES and line_bot_api:
        line_bot_api.reply_message(reply_token, TextSendMessage(text="收到檔案，準備下載..."))

    try:
        content_response = line_bot_api.get_message_content(message_id)
        fd, tmp_path = tempfile.mkstemp(prefix="line_backup_", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                for chunk in content_response.iter_content(chunk_size=65536):
                    f.write(chunk)
        except Exception:
            os.unlink(tmp_path)
            raise
        tmp_path = Path(tmp_path)
        size = tmp_path.stat().st_size
        if size == 0:
            if config.ENABLE_LINE_REPLIES and user_id and line_bot_api:
                line_bot_api.push_message(user_id, TextSendMessage(text="無法取得檔案內容。"))
            tmp_path.unlink(missing_ok=True)
            return

        if config.MAX_FILE_SIZE_MB > 0:
            size_mb = size / (1024 * 1024)
            if size_mb > config.MAX_FILE_SIZE_MB:
                log.warning("File too large: %.2f MB (max %.2f MB)", size_mb, config.MAX_FILE_SIZE_MB)
                if config.ENABLE_LINE_REPLIES and user_id and line_bot_api:
                    line_bot_api.push_message(
                        user_id,
                        TextSendMessage(text=f"檔案過大 ({size_mb:.1f} MB)，已略過（上限 {config.MAX_FILE_SIZE_MB:.0f} MB）"),
                    )
                tmp_path.unlink(missing_ok=True)
                return

        file_hash = hash_store.file_sha256(tmp_path) if config.UPLOADED_HASHES_FILE else None
        if file_hash and hash_store.contains(file_hash):
            log.info("Skip duplicate file (hash): %s", file_hash[:16])
            if config.ENABLE_LINE_REPLIES and user_id and line_bot_api:
                line_bot_api.push_message(user_id, TextSendMessage(text="已備份過，略過"))
            tmp_path.unlink(missing_ok=True)
            return

        suggested_name = getattr(msg, "file_name", None) or f"{message_type}_{message_id}"
        source_folder = source_map.user_source.get(user_id, "other")
        try:
            remote_path = nextcloud.upload_to_nextcloud(
                suggested_name, message_type, source_folder=source_folder, file_path=tmp_path
            )
        finally:
            tmp_path.unlink(missing_ok=True)
        if file_hash:
            hash_store.add(file_hash)
        log.info("Backup ok: %s", remote_path)
        stats.record_backup()
        if config.ENABLE_LINE_REPLIES and user_id and line_bot_api:
            line_bot_api.push_message(
                user_id, TextSendMessage(text="✅ 檔案已成功備份至 Nextcloud！")
            )
    except Exception as e:
        log.exception("Backup failed")
        if config.ENABLE_LINE_REPLIES and user_id and line_bot_api:
            line_bot_api.push_message(
                user_id, TextSendMessage(text=f"❌ 備份失敗：{str(e)[:500]}")
            )


def _handle_text(event):
    text = (event.message.text or "").strip()
    user_id = getattr(event.source, "user_id", None) if hasattr(event, "source") else None
    if not user_id:
        return
    if text.lower() in ("0", "other", "reset", "預設"):
        source_map.user_source[user_id] = "other"
        source_map.save_source_state()
        if config.ENABLE_LINE_REPLIES and line_bot_api:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="已設為：other"))
        return
    if text in source_map.SOURCE_MAP:
        source_map.user_source[user_id] = source_map.SOURCE_MAP[text]
        source_map.save_source_state()
        if config.ENABLE_LINE_REPLIES and line_bot_api:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=f"已設為：{source_map.SOURCE_MAP[text]}"),
            )
        return
    urls = _extract_urls(text)
    if urls:
        message_id = getattr(event.message, "id", None)
        if message_id and message_id in _processed_message_ids:
            log.info("Skip duplicate link message_id: %s", message_id)
        else:
            if message_id:
                if len(_processed_message_ids) >= _MAX_PROCESSED_IDS:
                    _processed_message_ids.clear()
                _processed_message_ids.add(message_id)
            source_folder = source_map.user_source.get(user_id, "other")
            _backup_links_to_nextcloud(text, source_folder, user_id)
        return
    if config.ENABLE_TEXT_BACKUP and text:
        source_folder = source_map.user_source.get(user_id, "other")
        try:
            nextcloud.append_to_daily_notes(source_folder, text)
            stats.record_backup()
            log.info("Text backup ok: notes.txt")
            if config.ENABLE_LINE_REPLIES and line_bot_api and user_id:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="✅ 已寫入今日筆記"))
        except Exception as e:
            log.exception("Text backup failed")
            if config.ENABLE_LINE_REPLIES and line_bot_api and user_id:
                line_bot_api.push_message(user_id, TextSendMessage(text=f"❌ 筆記備份失敗：{str(e)[:200]}"))


def register(handler, api):
    """Register LINE event handlers. Call once after creating WebhookHandler and LineBotApi."""
    global line_bot_api
    line_bot_api = api
    handler.add(MessageEvent, message=TextMessage)(_handle_text)
    handler.add(MessageEvent, message=ImageMessage)(lambda e: _handle_media_message(e))
    handler.add(MessageEvent, message=VideoMessage)(lambda e: _handle_media_message(e))
    handler.add(MessageEvent, message=AudioMessage)(lambda e: _handle_media_message(e))
    handler.add(MessageEvent, message=FileMessage)(lambda e: _handle_media_message(e))
