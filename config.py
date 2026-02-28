"""
Configuration from environment. Call load_dotenv() before importing this module.
"""
import os
from zoneinfo import ZoneInfo

# All times in Taipei (folder date + filename time)
TZ = ZoneInfo("Asia/Taipei")

# LINE
LINE_CHANNEL_SECRET = (os.getenv("LINE_CHANNEL_SECRET") or "").strip()
LINE_CHANNEL_ACCESS_TOKEN = (os.getenv("LINE_CHANNEL_ACCESS_TOKEN") or "").strip()

# Nextcloud WebDAV
NEXTCLOUD_URL = (os.getenv("NEXTCLOUD_URL") or "").rstrip("/")
NEXTCLOUD_USER = (os.getenv("NEXTCLOUD_USER") or "").strip()
NEXTCLOUD_PASSWORD = (os.getenv("NEXTCLOUD_PASSWORD") or "").strip()
NEXTCLOUD_BASE_PATH = (os.getenv("NEXTCLOUD_BASE_PATH", "LINE_Backup") or "LINE_Backup").strip("/")

# When true: reply "收到檔案..." and push success/error. When false: silent.
ENABLE_LINE_REPLIES = (os.getenv("ENABLE_LINE_REPLIES", "false") or "").strip().lower() in ("1", "true", "yes")

# Optional: persist source selection to file. Empty = disabled.
SOURCE_STATE_FILE = (os.getenv("SOURCE_STATE_FILE", "data/source_state.json") or "").strip()

# Optional: max file size in MB (0 = no limit).
MAX_FILE_SIZE_MB = float(os.getenv("MAX_FILE_SIZE_MB", "0") or "0")

# Optional: file to store source map (number -> folder). Editable via /admin.
SOURCE_MAP_FILE = (os.getenv("SOURCE_MAP_FILE", "data/source_map.json") or "").strip()

# Optional: password to access /admin. Empty = no auth.
ADMIN_PASSWORD = (os.getenv("ADMIN_PASSWORD") or "").strip()

# Optional: GitHub repo URL for footer link.
GITHUB_REPO = (os.getenv("GITHUB_REPO") or "").strip()

# Optional: backup plain text (no URL) to daily notes.txt in Nextcloud.
ENABLE_TEXT_BACKUP = (os.getenv("ENABLE_TEXT_BACKUP", "false") or "").strip().lower() in ("1", "true", "yes")

# Optional: file to store uploaded file hashes for duplicate skip. Empty = disabled.
UPLOADED_HASHES_FILE = (os.getenv("UPLOADED_HASHES_FILE", "data/uploaded_hashes.json") or "").strip()

# Admin session
ADMIN_COOKIE_NAME = "admin_session"
ADMIN_SESSION_SECONDS = 3600  # 1 hour

# Login rate limit: same IP, 5 consecutive failures -> lock 15 minutes
LOGIN_MAX_FAILED = 5
LOGIN_LOCK_SECONDS = 15 * 60

# Keys we consider required vs recommended for config check
REQUIRED_ENV_KEYS = ("LINE_CHANNEL_SECRET", "LINE_CHANNEL_ACCESS_TOKEN", "NEXTCLOUD_URL", "NEXTCLOUD_USER", "NEXTCLOUD_PASSWORD")
RECOMMENDED_ENV_KEYS = ("ADMIN_PASSWORD", "SOURCE_MAP_FILE")


def get_missing_config() -> tuple[list[str], list[str]]:
    """Return (missing_required, missing_recommended) for config check UI."""
    def get(key: str) -> str:
        v = os.getenv(key)
        return (v or "").strip()
    missing_required = [k for k in REQUIRED_ENV_KEYS if not get(k)]
    missing_recommended = [k for k in RECOMMENDED_ENV_KEYS if not get(k)]
    return (missing_required, missing_recommended)
