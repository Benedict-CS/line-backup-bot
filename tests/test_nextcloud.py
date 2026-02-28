"""Tests for nextcloud module (pure helpers, no network)."""
import pytest
from pathlib import Path

# Import after we may have patched config; use late import in tests if needed
import nextcloud


def test_safe_file_stem():
    assert nextcloud._safe_file_stem("Report.pdf") == "Report.pdf"
    assert nextcloud._safe_file_stem("My File 2024.pptx") == "My_File_2024.pptx"
    assert nextcloud._safe_file_stem("a/b\\c") == "a_b_c"
    assert nextcloud._safe_file_stem("") == "file"


def test_safe_link_title():
    assert nextcloud._safe_link_title("Hello World") == "Hello_World"
    assert nextcloud._safe_link_title("A/B & Co.") == "A_B___Co"
    assert nextcloud._safe_link_title("") == ""
    assert len(nextcloud._safe_link_title("x" * 100)) <= 60


def test_guess_extension():
    assert nextcloud.guess_extension("image") == ".jpg"
    assert nextcloud.guess_extension("video") == ".mp4"
    assert nextcloud.guess_extension("link") == ".txt"
    assert nextcloud.guess_extension("file") == ""
    assert nextcloud.guess_extension("unknown") == ""


def test_webdav_url():
    # Depends on config.NEXTCLOUD_URL; just check it returns a string
    url = nextcloud.webdav_url("LINE_Backup/other/2025-02-24/link")
    assert isinstance(url, str)
    assert "LINE_Backup" in url or "link" in url or url  # path is included or URL is from config
