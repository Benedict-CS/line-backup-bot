"""Tests for hash_store module."""
import pytest
from pathlib import Path

import hash_store


@pytest.fixture(autouse=True)
def temp_hash_file(monkeypatch, tmp_path):
    f = tmp_path / "hashes.json"
    monkeypatch.setattr("hash_store.config.UPLOADED_HASHES_FILE", str(f))
    monkeypatch.setattr("hash_store._loaded", False)
    monkeypatch.setattr("hash_store._hashes", set())
    yield f


def test_file_sha256(tmp_path):
    p = tmp_path / "f.txt"
    p.write_text("hello")
    h = hash_store.file_sha256(p)
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_contains_add():
    assert hash_store.contains("id-123") is False
    hash_store.add("id-123")
    assert hash_store.contains("id-123") is True
    hash_store.add("id-456")
    assert hash_store.contains("id-456") is True
