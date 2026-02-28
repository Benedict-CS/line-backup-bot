"""
Backup stats: last backup time, backups today. Persisted to JSON for /status page.
"""
import json
import logging
from datetime import datetime
from pathlib import Path

import config

log = logging.getLogger(__name__)

STATS_FILE = "data/backup_stats.json"

_last_at: datetime | None = None
_today_count: int = 0
_today_date: str = ""


def _load() -> None:
    global _last_at, _today_count, _today_date
    path = Path(STATS_FILE)
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data.get("last_at"), str):
            _last_at = datetime.fromisoformat(data["last_at"].replace("Z", "+00:00"))
        _today_date = (data.get("date") or "")[:10]
        _today_count = int(data.get("count", 0)) if isinstance(data.get("count"), (int, float)) else 0
    except Exception as e:
        log.warning("Could not load backup stats: %s", e)


def _save() -> None:
    path = Path(STATS_FILE)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "last_at": _last_at.isoformat() if _last_at else None,
                    "date": _today_date,
                    "count": _today_count,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except Exception as e:
        log.warning("Could not save backup stats: %s", e)


def record_backup() -> None:
    """Call after a successful backup (file, link, or text)."""
    global _last_at, _today_count, _today_date
    now = datetime.now(config.TZ)
    today = now.strftime("%Y-%m-%d")
    if _today_date != today:
        _today_date = today
        _today_count = 0
    _today_count += 1
    _last_at = now
    _save()


def get_last_backup_at() -> datetime | None:
    if _last_at is None:
        _load()
    return _last_at


def get_backups_today() -> int:
    global _today_date, _today_count
    today = datetime.now(config.TZ).strftime("%Y-%m-%d")
    if _today_date != today:
        _load()
    if _today_date != today:
        return 0
    return _today_count


# Load on first use
_load()
