"""
Nextcloud WebDAV: upload files, create folders.
Async implementation with aiohttp for non-blocking I/O; sync wrappers for callers in threads.
"""
import asyncio
import time
from datetime import datetime
from pathlib import Path

import aiohttp
import requests

import config
import source_map

# All times from config.TZ
TZ = config.TZ


def _webdav_root() -> str:
    """User's WebDAV root."""
    return f"{config.NEXTCLOUD_URL.rstrip('/')}/remote.php/webdav/"


def webdav_url(path: str) -> str:
    """Build full WebDAV URL (path = folder/file under user root)."""
    root = _webdav_root()
    path = path.strip("/")
    return f"{root.rstrip('/')}/{path}" if path else root


def _safe_file_stem(name: str, max_len: int = 80) -> str:
    """Sanitize filename stem for 'files' type: alphanumeric, space, underscore, hyphen, dot."""
    p = Path(name)
    stem = (p.stem or p.name or "file").strip()
    s = "".join(c if c.isalnum() or c in " _-." else "_" for c in stem)
    s = "_".join(s.split())
    return (s[:max_len] or "file").strip("._")


def _safe_link_title(title: str, max_len: int = 60) -> str:
    """Sanitize page title for link filename: alphanumeric, space, underscore, hyphen."""
    s = "".join(c if c.isalnum() or c in " _-" else "_" for c in (title or ""))
    s = "_".join(s.split()).strip("_")
    return (s[:max_len] or "").strip()


def guess_extension(message_type: str) -> str:
    """Guess file extension from LINE message type."""
    m = {"image": ".jpg", "video": ".mp4", "audio": ".m4a", "file": "", "link": ".txt"}
    return m.get(message_type, "")


# Subfolder under date: image, video, link, files
_TYPE_SUBFOLDER = {"image": "image", "video": "video", "link": "link", "audio": "files", "file": "files"}

_TIMEOUT_MKCOL = aiohttp.ClientTimeout(total=30)
_TIMEOUT_PUT = aiohttp.ClientTimeout(total=120)


async def _upload_to_nextcloud_async(
    suggested_name: str,
    message_type: str,
    source_folder: str = "other",
    *,
    content: bytes | None = None,
    file_path: Path | None = None,
    link_title: str | None = None,
) -> str:
    """Async upload via aiohttp (non-blocking)."""
    if (content is None) == (file_path is None):
        raise ValueError("Provide exactly one of content or file_path")
    now = datetime.now(TZ)
    date_folder = now.strftime("%Y-%m-%d")
    date_compact = now.strftime("%Y%m%d")
    time_compact = now.strftime("%H%M%S")
    ms = now.strftime("%f")[:3]
    ext = guess_extension(message_type)
    if not ext and suggested_name:
        ext = Path(suggested_name).suffix or ""
    if message_type == "file":
        stem = _safe_file_stem(suggested_name)
        safe_name = f"{stem}{ext}"
    elif message_type == "link" and link_title:
        safe = _safe_link_title(link_title)
        part = f"link_{date_compact}_{time_compact}_{ms}{ext}"
        safe_name = f"[{safe}] {part}" if safe else part
    else:
        prefix = {"image": "img", "video": "vid", "audio": "aud", "link": "link"}.get(message_type, "file")
        safe_name = f"{prefix}_{date_compact}_{time_compact}_{ms}{ext}"
    base = (config.NEXTCLOUD_BASE_PATH or "LINE_Backup").strip("/")
    source_safe = source_map.safe_folder_name(source_folder) or "other"
    type_subfolder = _TYPE_SUBFOLDER.get(message_type, "files")
    remote_dir = f"{base}/{source_safe}/{date_folder}/{type_subfolder}"
    remote_path = f"{remote_dir}/{safe_name}"

    auth = aiohttp.BasicAuth(config.NEXTCLOUD_USER, config.NEXTCLOUD_PASSWORD)
    last_err = None
    for attempt in range(3):
        try:
            async with aiohttp.ClientSession() as session:
                for part in [base, f"{base}/{source_safe}", f"{base}/{source_safe}/{date_folder}", remote_dir]:
                    url_dir = webdav_url(part + "/")
                    async with session.request("MKCOL", url_dir, auth=auth, timeout=_TIMEOUT_MKCOL) as r:
                        if r.status not in (201, 204, 405):
                            text = await r.text()
                            raise RuntimeError(f"MKCOL {part}: {r.status} {text[:200]}")
                url_file = webdav_url(remote_path)
                if file_path is not None:
                    data = file_path.read_bytes()
                else:
                    data = content
                async with session.put(url_file, data=data, auth=auth, timeout=_TIMEOUT_PUT) as r3:
                    if r3.status not in (200, 201, 204):
                        text = await r3.text()
                        raise RuntimeError(f"PUT {remote_path}: {r3.status} {text[:200]}")
            return remote_path
        except Exception as e:
            last_err = e
            if attempt < 2:
                await asyncio.sleep(1.5 * (attempt + 1))
    raise last_err


def upload_to_nextcloud(
    suggested_name: str,
    message_type: str,
    source_folder: str = "other",
    *,
    content: bytes | None = None,
    file_path: Path | None = None,
    link_title: str | None = None,
) -> str:
    """
    Upload to Nextcloud under LINE_Backup/{source}/YYYY-MM-DD/{type}/.
    Uses aiohttp in background; safe to call from sync code (e.g. handler thread).
    link_title: optional page title for link type (used in filename when set).
    """
    return asyncio.run(
        _upload_to_nextcloud_async(
            suggested_name, message_type, source_folder,
            content=content, file_path=file_path, link_title=link_title,
        )
    )


async def _append_to_daily_notes_async(source_folder: str, text: str) -> str:
    """Async append notes via aiohttp."""
    now = datetime.now(TZ)
    date_folder = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")
    base = (config.NEXTCLOUD_BASE_PATH or "LINE_Backup").strip("/")
    source_safe = source_map.safe_folder_name(source_folder) or "other"
    remote_dir = f"{base}/{source_safe}/{date_folder}"
    remote_path = f"{remote_dir}/notes.txt"
    auth = aiohttp.BasicAuth(config.NEXTCLOUD_USER, config.NEXTCLOUD_PASSWORD)
    url_file = webdav_url(remote_path)
    existing = ""
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url_file, auth=auth, timeout=_TIMEOUT_MKCOL) as r:
                if r.status == 200:
                    existing = await r.text() or ""
        except Exception:
            pass
        new_block = f"\n---\n{time_str}\n{text.strip()}\n"
        content = (existing + new_block).strip().encode("utf-8")
        for part in [base, f"{base}/{source_safe}", f"{base}/{source_safe}/{date_folder}"]:
            url_dir = webdav_url(part + "/")
            async with session.request("MKCOL", url_dir, auth=auth, timeout=_TIMEOUT_MKCOL) as _:
                pass
        async with session.put(url_file, data=content, auth=auth, timeout=_TIMEOUT_MKCOL) as r:
            if r.status not in (200, 201, 204):
                t = await r.text()
                raise RuntimeError(f"PUT notes.txt: {r.status} {t[:200]}")
    return remote_path


def append_to_daily_notes(source_folder: str, text: str) -> str:
    """
    Append plain text to LINE_Backup/{source}/YYYY-MM-DD/notes.txt.
    Creates file if missing. Returns remote path.
    """
    return asyncio.run(_append_to_daily_notes_async(source_folder, text))


async def check_nextcloud_async(timeout: float = 10.0) -> bool:
    """PROPFIND root; return True if Nextcloud is reachable (for /health, /status)."""
    try:
        auth = aiohttp.BasicAuth(config.NEXTCLOUD_USER, config.NEXTCLOUD_PASSWORD)
        url = webdav_url("")
        async with aiohttp.ClientSession() as session:
            async with session.request(
                "PROPFIND", url, auth=auth,
                timeout=aiohttp.ClientTimeout(total=timeout),
                headers={"Depth": "0"},
            ) as r:
                return r.status in (200, 207)
    except Exception:
        return False
