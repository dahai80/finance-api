from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from config import settings
from main import app


@pytest.fixture(scope="module")
def client():
    settings.akshare_mock = True
    with TestClient(app) as c:
        yield c


def test_market_money_flow(client):
    r = client.get("/api/market/money-flow", params={"limit": 20})
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)


def test_market_alerts_list(client):
    r = client.get("/api/market/alerts", params={"limit": 10})
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)


def test_market_alerts_create(client):
    r = client.post("/api/market/alerts", json={
        "stock_code": "301800",
        "alert_type": "TECHNICAL",
        "direction": 1,
        "severity": "WARNING",
        "event_description": "test alert: volume spike detected",
    })
    assert r.status_code == 200
    body = r.json()
    assert "alert_id" in body


def test_market_alerts_after_create(client):
    """Verify alerts are queryable after creation."""
    client.post("/api/market/alerts", json={
        "stock_code": "688700",
        "alert_type": "FUNDAMENTAL",
        "direction": -1,
        "severity": "CRITICAL",
        "event_description": "test alert: earnings miss",
    })
    r = client.get("/api/market/alerts", params={"limit": 10})
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)


def test_market_sentiment(client):
    r = client.get("/api/market/sentiment")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, dict)
    assert "top_inflow" in body
    assert "top_outflow" in body
    assert "high_score_ipos" in body
    assert "market_phase" in body


def test_market_sentiment_snapshot(client):
    r = client.post("/api/market/sentiment/snapshot")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"


def test_market_sentiment_with_snapshot(client):
    """Verify sentiment includes snapshot data after saving one."""
    client.post("/api/market/sentiment/snapshot")
    r = client.get("/api/market/sentiment")
    assert r.status_code == 200
    body = r.json()
    assert "snapshot_date" in body


def test_kronos_health(client):
    r = client.get("/api/market/kronos/health")
    assert r.status_code == 200


@pytest.mark.skip(reason="requires kronos service on :8001")
def test_kline_predict(client):
    r = client.get("/api/market/kline/predict", params={"stock_code": "301800"})
    assert r.status_code == 200


def test_stock_snapshots(client):
    r = client.get("/api/market/snapshots", params={"limit": 10})
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
