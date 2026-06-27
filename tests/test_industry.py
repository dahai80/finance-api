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


def test_industry_events_list(client):
    r = client.get("/api/industry/events", params={"limit": 10})
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)


def test_industry_events_create(client):
    r = client.post("/api/industry/events", json={
        "event_title": "test event",
        "industry_tags": ["半导体"],
        "impact_analysis": "positive",
        "related_stock_codes": ["301800"],
    })
    assert r.status_code == 200
    body = r.json()
    assert "event_id" in body


def test_industry_events_list_after_create(client):
    client.post("/api/industry/events", json={
        "event_title": "test event 2",
        "industry_tags": ["光伏"],
    })
    r = client.get("/api/industry/events", params={"limit": 10})
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)