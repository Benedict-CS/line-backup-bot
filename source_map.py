"""
Source map (number -> folder name) and per-user source state.
"""
import json
import logging
import os
from pathlib import Path

import config

log = logging.getLogger(__name__)


def safe_folder_name(name: str) -> str:
    """Allow only alphanumeric, underscore, hyphen; max 32 chars."""
    s = "".join(c if c.isalnum() or c in "_-" else "_" for c in name)
    return s[:32] or "other"


# Source list: number -> folder name. Loaded from file or env.
SOURCE_MAP: dict[str, str] = {}

# Per-user last chosen source: user_id -> folder name. Default "other".
user_source: dict[str, str] = {}


def load_source_map() -> None:
    """Load SOURCE_MAP from file (if SOURCE_MAP_FILE set and exists) or from SOURCE_MAP env."""
    SOURCE_MAP.clear()
    if config.SOURCE_MAP_FILE:
        path = Path(config.SOURCE_MAP_FILE)
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    for k, v in data.items():
                        if k and v and isinstance(k, str) and isinstance(v, str):
                            SOURCE_MAP[k.strip()] = safe_folder_name(v.strip())
                    log.info("Loaded source map from %s (%d entries)", config.SOURCE_MAP_FILE, len(SOURCE_MAP))
                    return
            except Exception as e:
                log.warning("Could not load source map from %s: %s", config.SOURCE_MAP_FILE, e)
    for part in (os.getenv("SOURCE_MAP", "") or "").strip().split(","):
        part = part.strip()
        if ":" in part:
            k, v = part.split(":", 1)
            k, v = k.strip(), v.strip()
            if k and v:
                SOURCE_MAP[k] = safe_folder_name(v)


def load_source_state() -> None:
    """Load per-user source state from file if SOURCE_STATE_FILE set."""
    if not config.SOURCE_STATE_FILE:
        return
    path = Path(config.SOURCE_STATE_FILE)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                user_source.update(data)
                log.info("Loaded source state from %s (%d entries)", config.SOURCE_STATE_FILE, len(data))
        except Exception as e:
            log.warning("Could not load source state from %s: %s", config.SOURCE_STATE_FILE, e)


def save_source_state() -> None:
    """Persist per-user source state to file."""
    if not config.SOURCE_STATE_FILE:
        return
    path = Path(config.SOURCE_STATE_FILE)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(user_source, ensure_ascii=False, indent=0), encoding="utf-8")
    except Exception as e:
        log.warning("Could not save source state to %s: %s", config.SOURCE_STATE_FILE, e)
