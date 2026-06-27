import pytest
import pytest_asyncio
import httpx
import asyncpg

from config import settings

BASE_URL = "http://127.0.0.1:8000"


@pytest.fixture
def client():
    return httpx.Client(base_url=BASE_URL, timeout=10)


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
    assert isinstance(r.json(), list)


def test_ipo_sync(client):
    r = client.post("/api/ipo/sync")
    assert r.status_code == 200
    body = r.json()
    assert body["mock"] is True
    assert body["synced"] >= 1


def test_ipo_list_after_sync(client):
    client.post("/api/ipo/sync")
    r = client.get("/api/ipo")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) >= 1
    first = rows[0]
    assert "stock_code" in first
    assert "stock_name" in first
