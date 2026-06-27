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


def test_backtest_accuracy(client):
    r = client.get("/api/backtest/accuracy", params={"days": 30})
    assert r.status_code == 200
    body = r.json()
    # Returns list of accuracy data points
    assert isinstance(body, list)


def test_backtest_accuracy_default(client):
    r = client.get("/api/backtest/accuracy")
    assert r.status_code == 200
