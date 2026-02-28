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
_hashes: set[str] = set()
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
        if isinstance(data, list):
            _hashes = set(data[-_MAX_HASHES:])
        elif isinstance(data, dict) and isinstance(data.get("hashes"), list):
            _hashes = set(data["hashes"][-_MAX_HASHES:])
    except Exception as e:
        log.warning("Could not load uploaded hashes: %s", e)


def _save() -> None:
    p = _path()
    if not p:
        return
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        lst = list(_hashes)[-_MAX_HASHES:]
        p.write_text(json.dumps(lst, ensure_ascii=False), encoding="utf-8")
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
    global _hashes
    if not config.UPLOADED_HASHES_FILE:
        return
    _load()
    _hashes.add(h)
    if len(_hashes) > _MAX_HASHES:
        _hashes = set(list(_hashes)[-_MAX_HASHES:])
    _save()
