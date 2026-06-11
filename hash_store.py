"""
Store of uploaded file hashes to skip duplicate uploads. Persisted to JSON.
"""
import hashlib
import json
import logging
from pathlib import Path

import config

log = logging.getLogger(__name__)

_MAX_HASHES = 50000
# dict preserves insertion order — correct FIFO eviction (set does not).
_hashes: dict[str, None] = {}
_loaded = False


def _path() -> Path | None:
    if not config.UPLOADED_HASHES_FILE:
        return None
    return Path(config.UPLOADED_HASHES_FILE)


def _load() -> None:
    global _loaded, _hashes
    if _loaded:
        return
    _loaded = True
    p = _path()
    if not p or not p.exists():
        return
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        lst = data if isinstance(data, list) else (data.get("hashes") if isinstance(data, dict) else None)
        if isinstance(lst, list):
            _hashes = {h: None for h in lst[-_MAX_HASHES:]}
    except Exception as e:
        log.warning("Could not load uploaded hashes: %s", e)


def _save() -> None:
    p = _path()
    if not p:
        return
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(list(_hashes), ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        log.warning("Could not save uploaded hashes: %s", e)


def file_sha256(path: Path) -> str:
    """Compute SHA-256 of file content."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def contains(h: str) -> bool:
    """True if this hash was already uploaded (duplicate)."""
    if not config.UPLOADED_HASHES_FILE:
        return False
    _load()
    return h in _hashes


def add(h: str) -> None:
    """Record hash after successful upload."""
    if not config.UPLOADED_HASHES_FILE:
        return
    _load()
    if h in _hashes:
        return
    _hashes[h] = None
    # Evict oldest by insertion order.
    while len(_hashes) > _MAX_HASHES:
        _hashes.pop(next(iter(_hashes)))
    _save()
