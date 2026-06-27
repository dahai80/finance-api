import pytest
from fastapi.testclient import TestClient

from config import settings
from main import app


@pytest.fixture(scope="module")
def client():
    settings.akshare_mock = True
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "finance-api"


def test_root(client):
    r = client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert "finance-api" in body["service"]


def test_ipo_list(client):
    r = client.get("/api/ipo")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, dict)
    assert isinstance(body["data"], list)
    assert isinstance(body["total"], int)
    assert body["limit"] == 50
    assert body["offset"] == 0


def test_ipo_sync(client):
    r = client.post("/api/ipo/sync")
    assert r.status_code == 200
    body = r.json()
    assert body["mock"] is True
    assert body["synced"] >= 1
    assert body["scored"] == body["synced"]


def test_ipo_list_after_sync(client):
    client.post("/api/ipo/sync")
    r = client.get("/api/ipo")
    assert r.status_code == 200
    rows = r.json()["data"]
    assert len(rows) >= 1
    first = rows[0]
    assert "stock_code" in first
    assert "stock_name" in first
