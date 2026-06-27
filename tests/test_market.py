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


def test_market_alerts(client):
    r = client.get("/api/market/alerts", params={"limit": 10})
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)


def test_market_sentiment(client):
    r = client.get("/api/market/sentiment")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, dict)


def test_kronos_health(client):
    r = client.get("/api/market/kronos/health")
    assert r.status_code == 200


@pytest.mark.skip(reason="requires kronos service on :8001")
def test_kline_predict(client):
    r = client.get("/api/market/kline/predict", params={"stock_code": "301800"})
    assert r.status_code == 200