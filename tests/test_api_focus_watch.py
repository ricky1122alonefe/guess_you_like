"""FastAPI focus-watch 端点测试。"""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def client(tmp_path):
    from fastapi.testclient import TestClient

    from apps.api.main import create_app

    app = create_app(tmp_path)
    return TestClient(app)


class TestFocusWatchApi:
    def test_get_empty(self, client):
        r = client.get("/api/focus-watch")
        assert r.status_code == 200
        assert r.json()["fids"] == []

    def test_add_remove(self, client):
        r = client.post("/api/focus-watch", json={"action": "add", "fids": ["123"]})
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert "123" in r.json()["focus_watch"]["fids"]

        r = client.post("/api/focus-watch", json={"action": "remove", "fids": ["123"]})
        assert r.status_code == 200
        assert "123" not in r.json()["focus_watch"]["fids"]

    def test_set_and_limit(self, client, monkeypatch):
        monkeypatch.setattr("focus_watch.max_focus_limit", lambda: 2)
        r = client.post("/api/focus-watch", json={"action": "set", "fids": ["1", "2", "3"]})
        assert r.status_code == 400
        assert "最多关注" in r.json()["detail"]

    def test_clear(self, client):
        client.post("/api/focus-watch", json={"action": "add", "fids": ["1"]})
        r = client.post("/api/focus-watch", json={"action": "clear"})
        assert r.status_code == 200
        assert r.json()["focus_watch"]["fids"] == []
