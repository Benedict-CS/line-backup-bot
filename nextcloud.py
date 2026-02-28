"""
Nextcloud WebDAV: upload files, create folders.
"""
import time
from datetime import datetime
from pathlib import Path

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


def guess_extension(message_type: str) -> str:
    """Guess file extension from LINE message type."""
    m = {"image": ".jpg", "video": ".mp4", "audio": ".m4a", "file": "", "link": ".txt"}
    return m.get(message_type, "")


# Subfolder under date: image, video, link, files
_TYPE_SUBFOLDER = {"image": "image", "video": "video", "link": "link", "audio": "files", "file": "files"}


def upload_to_nextcloud(
    suggested_name: str,
    message_type: str,
    source_folder: str = "other",
    *,
    content: bytes | None = None,
    file_path: Path | None = None,
) -> str:
    """
    Upload to Nextcloud under LINE_Backup/{source}/YYYY-MM-DD/{type}/.
    Provide either content (bytes) or file_path; file_path is streamed.
    """
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
    else:
        prefix = {"image": "img", "video": "vid", "audio": "aud", "link": "link"}.get(message_type, "file")
        safe_name = f"{prefix}_{date_compact}_{time_compact}_{ms}{ext}"
    base = (config.NEXTCLOUD_BASE_PATH or "LINE_Backup").strip("/")
    source_safe = source_map.safe_folder_name(source_folder) or "other"
    type_subfolder = _TYPE_SUBFOLDER.get(message_type, "files")
    remote_dir = f"{base}/{source_safe}/{date_folder}/{type_subfolder}"
    remote_path = f"{remote_dir}/{safe_name}"

    auth = (config.NEXTCLOUD_USER, config.NEXTCLOUD_PASSWORD)
    last_err = None
    for attempt in range(3):
        try:
            for part in [base, f"{base}/{source_safe}", f"{base}/{source_safe}/{date_folder}", remote_dir]:
                url_dir = webdav_url(part + "/")
                r = requests.request("MKCOL", url_dir, auth=auth, timeout=30)
                if r.status_code not in (201, 204, 405):
                    raise RuntimeError(f"MKCOL {part}: {r.status_code} {r.text[:200]}")
            url_file = webdav_url(remote_path)
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


def append_to_daily_notes(source_folder: str, text: str) -> str:
    """
    Append plain text to LINE_Backup/{source}/YYYY-MM-DD/notes.txt.
    Creates file if missing. Returns remote path.
    """
    now = datetime.now(TZ)
    date_folder = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")
    base = (config.NEXTCLOUD_BASE_PATH or "LINE_Backup").strip("/")
    source_safe = source_map.safe_folder_name(source_folder) or "other"
    remote_dir = f"{base}/{source_safe}/{date_folder}"
    remote_path = f"{remote_dir}/notes.txt"
    auth = (config.NEXTCLOUD_USER, config.NEXTCLOUD_PASSWORD)
    url_file = webdav_url(remote_path)
    existing = ""
    try:
        r = requests.get(url_file, auth=auth, timeout=30)
        if r.status_code == 200:
            existing = r.text or ""
    except Exception:
        pass
    new_block = f"\n---\n{time_str}\n{text.strip()}\n"
    content = (existing + new_block).strip().encode("utf-8")
    for part in [base, f"{base}/{source_safe}", f"{base}/{source_safe}/{date_folder}"]:
        url_dir = webdav_url(part + "/")
        requests.request("MKCOL", url_dir, auth=auth, timeout=30)
    r = requests.put(url_file, data=content, auth=auth, timeout=30)
    if r.status_code not in (200, 201, 204):
        raise RuntimeError(f"PUT notes.txt: {r.status_code} {r.text[:200]}")
    return remote_path
