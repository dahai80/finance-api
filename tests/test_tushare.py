"""Tests for Tushare data provider module."""
from unittest.mock import patch, MagicMock

import pytest

from data_provider import tushare_fetcher


def test_to_float_normal():
    assert tushare_fetcher._to_float(42) == 42.0
    assert tushare_fetcher._to_float("3.14") == 3.14
    assert tushare_fetcher._to_float("1,000.5") == 1000.5


def test_to_float_none():
    assert tushare_fetcher._to_float(None) == 0.0


def test_to_float_nan():
    assert tushare_fetcher._to_float(float("nan")) == 0.0


def test_to_float_inf():
    assert tushare_fetcher._to_float(float("inf")) == 0.0


def test_to_float_invalid():
    assert tushare_fetcher._to_float("abc") == 0.0


def test_get_pro_no_token():
    with patch("data_provider.tushare_fetcher.settings") as mock_settings:
        mock_settings.tushare_token = None
        assert tushare_fetcher._get_pro() is None


def test_get_pro_no_tushare():
    with patch("data_provider.tushare_fetcher.settings") as mock_settings:
        mock_settings.tushare_token = "fake_token"
        with patch("builtins.__import__", side_effect=ImportError("no tushare")):
            assert tushare_fetcher._get_pro() is None


def test_get_pro_success():
    mock_pro = MagicMock()
    mock_ts = MagicMock()
    mock_ts.pro_api.return_value = mock_pro

    with patch("data_provider.tushare_fetcher.settings") as mock_settings:
        mock_settings.tushare_token = "test_token"
        with patch("builtins.__import__", return_value=mock_ts):
            pro = tushare_fetcher._get_pro()
            assert pro is mock_pro
            mock_ts.set_token.assert_called_once_with("test_token")


def test_fetch_daily_kline_no_pro():
    with patch("data_provider.tushare_fetcher._get_pro", return_value=None):
        result = tushare_fetcher.fetch_daily_kline("000001.SZ")
        assert result == []


def test_fetch_daily_kline_success():
    data = {
        "trade_date": "20260627",
        "open": 10.5,
        "high": 11.0,
        "low": 10.2,
        "close": 10.8,
        "vol": 1000,
        "pct_chg": 2.5,
    }
    mock_row = MagicMock()
    mock_row.get = lambda k, d=None: data.get(k, d)
    mock_df = MagicMock()
    mock_df.empty = False
    mock_df.iterrows.return_value = [(0, mock_row)]
    mock_pro = MagicMock()
    mock_pro.daily.return_value = mock_df

    with patch("data_provider.tushare_fetcher._get_pro", return_value=mock_pro):
        result = tushare_fetcher.fetch_daily_kline("000001.SZ", days=5)
        assert len(result) == 1
        assert result[0]["trade_date"] == "20260627"
        assert result[0]["close"] == 10.8


def test_fetch_money_flow_no_pro():
    with patch("data_provider.tushare_fetcher._get_pro", return_value=None):
        result = tushare_fetcher.fetch_money_flow_history()
        assert result == []


def test_fetch_financial_data_no_pro():
    with patch("data_provider.tushare_fetcher._get_pro", return_value=None):
        result = tushare_fetcher.fetch_financial_data("000001.SZ")
        assert result == {}


def test_fetch_index_daily_no_pro():
    with patch("data_provider.tushare_fetcher._get_pro", return_value=None):
        result = tushare_fetcher.fetch_index_daily()
        assert result == []
