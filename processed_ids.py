"""
Persist processed LINE webhook message IDs to avoid duplicate handling after restart.
Batch save: every SAVE_EVERY_N adds or SAVE_INTERVAL_SEC seconds to reduce I/O.
"""
import json
import logging
import time
from pathlib import Path

import config

log = logging.getLogger(__name__)

PROCESSED_IDS_FILE = config.PROCESSED_IDS_FILE
_MAX_IDS = 10000
SAVE_EVERY_N = 50
SAVE_INTERVAL_SEC = 60.0

_ids: set[str] = set()
_loaded = False
_dirty = 0
_last_save_at = 0.0


def _path() -> Path | None:
    if not PROCESSED_IDS_FILE:
        return None
    return Path(PROCESSED_IDS_FILE)


def _load() -> None:
    global _loaded, _ids, _last_save_at
    if _loaded:
        return
    _loaded = True
    p = _path()
    if not p or not p.exists():
        _last_save_at = time.time()
        return
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, list):
            _ids = set(data[-_MAX_IDS:])
        elif isinstance(data, dict) and isinstance(data.get("ids"), list):
            _ids = set(data["ids"][-_MAX_IDS:])
        _last_save_at = time.time()
        log.info("Loaded %d processed message IDs from %s", len(_ids), p)
    except Exception as e:
        log.warning("Could not load processed IDs from %s: %s", p, e)
        _last_save_at = time.time()


def _save() -> None:
    global _dirty, _last_save_at
    p = _path()
    if not p:
        return
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        lst = list(_ids)[-_MAX_IDS:]
        p.write_text(json.dumps(lst, ensure_ascii=False), encoding="utf-8")
        _dirty = 0
        _last_save_at = time.time()
    except Exception as e:
        log.warning("Could not save processed IDs to %s: %s", p, e)


def _save_if_needed() -> None:
    """Persist when batch size or interval reached."""
    global _dirty
    if _dirty >= SAVE_EVERY_N or (_dirty > 0 and (time.time() - _last_save_at) >= SAVE_INTERVAL_SEC):
        _save()


def contains(message_id: str) -> bool:
    if not message_id:
        return False
    _load()
    return message_id in _ids


def add(message_id: str) -> None:
    global _ids, _dirty
    if not message_id:
        return
    _load()
    _ids.add(message_id)
    if len(_ids) > _MAX_IDS:
        _ids = set(list(_ids)[-_MAX_IDS:])
    _dirty += 1
    _save_if_needed()
