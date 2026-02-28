"""
Fetch page <title> from URL for link backup (lightweight GET, cap size). Uses aiohttp.
"""
import asyncio
import re
import logging
from html import unescape

import aiohttp

log = logging.getLogger(__name__)

_TITLE_TIMEOUT = aiohttp.ClientTimeout(total=3)
_TITLE_MAX_BYTES = 100 * 1024  # 100 KB
_TITLE_RE = re.compile(r"<title[^>]*>([^<]+)</title>", re.IGNORECASE | re.DOTALL)
_TITLE_MAX_LEN = 200


async def _fetch_page_title_async(url: str) -> str:
    """Async GET url, parse <title>. Returns stripped title or empty string."""
    if not url or not url.startswith(("http://", "https://")):
        return ""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                timeout=_TITLE_TIMEOUT,
                headers={"User-Agent": "LINE-Backup-Bot/1.0 (link metadata)"},
            ) as r:
                r.raise_for_status()
                raw = b""
                async for chunk in r.content.iter_chunked(8192):
                    raw += chunk
                    if len(raw) >= _TITLE_MAX_BYTES:
                        break
        text = raw.decode("utf-8", errors="ignore")
        m = _TITLE_RE.search(text)
        if not m:
            return ""
        title = unescape(m.group(1)).strip()
        title = " ".join(title.split())
        return title[:_TITLE_MAX_LEN] if title else ""
    except Exception as e:
        log.debug("Fetch title for %s: %s", url[:50], e)
        return ""


def fetch_page_title(url: str) -> str:
    """Sync wrapper: run async fetch in new loop (for use from handler thread)."""
    return asyncio.run(_fetch_page_title_async(url))
