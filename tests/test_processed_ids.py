"""Tests for processed_ids module."""
import pytest
import json

import processed_ids


@pytest.fixture(autouse=True)
def temp_processed_file(monkeypatch, tmp_path):
    f = tmp_path / "processed.json"
    monkeypatch.setattr("processed_ids.config.PROCESSED_IDS_FILE", str(f))
    monkeypatch.setattr("processed_ids._loaded", False)
    monkeypatch.setattr("processed_ids._ids", set())
    monkeypatch.setattr("processed_ids._dirty", 0)
    monkeypatch.setattr("processed_ids._last_save_at", 0.0)
    yield f


def test_contains_add():
    assert processed_ids.contains("msg-1") is False
    processed_ids.add("msg-1")
    assert processed_ids.contains("msg-1") is True
    processed_ids.add("msg-2")
    assert processed_ids.contains("msg-2") is True


def test_persist_and_load(monkeypatch, tmp_path):
    f = tmp_path / "processed.json"
    monkeypatch.setattr("processed_ids.config.PROCESSED_IDS_FILE", str(f))
    monkeypatch.setattr("processed_ids._loaded", False)
    processed_ids._ids.clear()
    processed_ids._dirty = 0
    processed_ids.add("a")
    processed_ids.add("b")
    processed_ids._save()
    assert f.exists()
    data = json.loads(f.read_text())
    assert isinstance(data, list)
    assert "a" in data and "b" in data
    monkeypatch.setattr("processed_ids._loaded", False)
    processed_ids._ids.clear()
    processed_ids._load()
    assert processed_ids.contains("a")
    assert processed_ids.contains("b")
