import pytest
from data_provider.akshare_fetcher import fetch_upcoming_ipo_mock


def test_mock_fetch_returns_rows():
    rows = fetch_upcoming_ipo_mock()
    assert len(rows) >= 3
    for row in rows:
        assert "stock_code" in row
        assert "stock_name" in row
        assert "ipo_date" in row
        assert "fundamental_metrics" in row
        metrics = row["fundamental_metrics"]
        assert "pe" in metrics
        assert "industry_pe" in metrics


def test_mock_fetch_is_copy():
    a = fetch_upcoming_ipo_mock()
    b = fetch_upcoming_ipo_mock()
    assert a[0] is not b[0]
