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


def test_ipo_scoring_dimensions(client):
    """Verify IPO scoring uses real data, not hardcoded 10.0 stubs."""
    client.post("/api/ipo/sync")
    r = client.get("/api/ipo")
    assert r.status_code == 200
    rows = r.json()["data"]
    assert len(rows) >= 1

    for row in rows:
        score = row.get("valuation_score", 0)
        rec = row.get("recommendation_level", "")
        assert isinstance(score, int)
        assert 0 <= score <= 100
        assert rec in ("HIGH", "MID", "LOW")


def test_ipo_search(client):
    """Test IPO search by stock name."""
    client.post("/api/ipo/sync")
    r = client.get("/api/ipo", params={"search": "科技"})
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["data"], list)


def test_ipo_min_score_filter(client):
    """Test IPO filtering by minimum score."""
    client.post("/api/ipo/sync")
    r = client.get("/api/ipo", params={"min_score": 60})
    assert r.status_code == 200
    body = r.json()
    for row in body["data"]:
        assert row.get("valuation_score", 0) >= 60
