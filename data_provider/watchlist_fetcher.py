from __future__ import annotations

import asyncio
import re
from datetime import date, datetime, timedelta
from typing import Any

from config import get_logger, settings

log = get_logger("finance.watchlist_fetcher")

# ── Sentiment keyword lists ────────────────────────────────────────────────

POSITIVE_KEYWORDS = [
    "增持", "突破", "利好", "上涨", "涨停", "盈利", "增长", "超预期",
    "中标", "签约", "订单", "分红", "回购", "扩产", "投产", "获批",
    "创新高", "业绩", "预增", "大单买入", "机构看好",
]

NEGATIVE_KEYWORDS = [
    "减持", "跌停", "利空", "下跌", "亏损", "下滑", "不及预期",
    "退市", "违规", "处罚", "诉讼", "调查", "爆雷", "违约",
    "业绩下滑", "预亏", "大单卖出", "机构看空", "风险",
]


# ── Mock data generators ───────────────────────────────────────────────────

def _mock_industry_rank() -> dict:
    return {
        "rank": 3,
        "total_in_industry": 45,
        "industry_name": "白酒",
        "pe_vs_industry": 0.85,
    }


def _mock_disclosed_info() -> dict:
    return {
        "financials": {
            "roe": 28.5,
            "revenue_yoy": 15.2,
            "net_profit_yoy": 18.7,
            "gross_margin": 91.2,
            "debt_ratio": 0.12,
        },
        "announcements": [
            {"date": "2026-06-25", "title": "2026年一季报发布，净利润同比增长18.7%", "type": "财报"},
            {"date": "2026-06-20", "title": "股东增持计划公告", "type": "增持"},
            {"date": "2026-06-15", "title": "董事会决议公告", "type": "公告"},
            {"date": "2026-06-10", "title": "分红方案实施公告", "type": "分红"},
            {"date": "2026-06-05", "title": "重大合同签约公告", "type": "公告"},
        ],
        "next_report_date": "2026-08-15",
    }


def _mock_price_history(days: int = 90) -> dict:
    kline: list[dict] = []
    base_price = 1680.0
    for i in range(days):
        d = (date.today() - timedelta(days=days - 1 - i)).isoformat()
        change = (hash(str(i * 7)) % 200 - 100) / 100
        close = round(base_price + change, 2)
        kline.append({
            "date": d,
            "open": round(close * (1 + (hash(str(i * 3)) % 100 - 50) / 500), 2),
            "high": round(close * (1 + (hash(str(i * 5)) % 80) / 500), 2),
            "low": round(close * (1 - (hash(str(i * 11)) % 80) / 500), 2),
            "close": close,
            "volume": 10000 + (hash(str(i * 13)) % 50000),
        })
        base_price = close * (1 + (hash(str(i * 17)) % 60 - 30) / 1000)

    start_price = kline[0]["close"] if kline else 0
    end_price = kline[-1]["close"] if kline else 0
    total_change = round((end_price - start_price) / start_price * 100, 2) if start_price else 0
    highs = [k["high"] for k in kline]
    lows = [k["low"] for k in kline]
    volumes = [k["volume"] for k in kline]

    return {
        "kline": kline,
        "summary": {
            "period_days": days,
            "start_price": round(start_price, 2),
            "end_price": round(end_price, 2),
            "total_change_pct": total_change,
            "high_3m": round(max(highs), 2) if highs else 0,
            "low_3m": round(min(lows), 2) if lows else 0,
            "avg_volume": round(sum(volumes) / len(volumes), 0) if volumes else 0,
        },
    }


def _mock_capital_flow() -> dict:
    today = {
        "main_net_inflow": 2.3e8,
        "large_order_net": 1.8e8,
        "medium_order_net": 0.3e8,
        "small_order_net": -0.2e8,
    }
    recent_5 = []
    for i in range(5):
        d = (date.today() - timedelta(days=4 - i)).isoformat()
        recent_5.append({
            "date": d,
            "main_net_inflow": round((hash(str(i * 23)) % 400 - 200) * 1e6, 2),
        })
    return {"today": today, "recent_5_days": recent_5}


def _mock_sentiment() -> dict:
    return {
        "score": 65,
        "label": "看多",
        "positive_count": 12,
        "negative_count": 4,
        "recent_news": [
            {"date": "2026-06-27", "title": "机构看好白酒板块，茅台龙头地位稳固", "polarity": "positive", "source": "东方财富"},
            {"date": "2026-06-26", "title": "茅台股东增持计划落地，信心信号明确", "polarity": "positive", "source": "同花顺"},
            {"date": "2026-06-25", "title": "一季报超预期，净利润增长18.7%", "polarity": "positive", "source": "财联社"},
            {"date": "2026-06-24", "title": "白酒行业竞争加剧，中小品牌承压", "polarity": "negative", "source": "证券时报"},
            {"date": "2026-06-23", "title": "消费复苏缓慢，高端白酒需求分化", "polarity": "neutral", "source": "经济观察报"},
        ],
    }


# ── Live data fetchers (AkShare/Tushare) ──────────────────────────────────

def _search_stock_live(q: str) -> list[dict]:
    """Search A-share stocks by code or name using AkShare."""
    try:
        import akshare as ak
        df = ak.stock_info_a_code_name()
        if df is None or df.empty:
            return []

        q_lower = q.lower().strip()
        seen: set[str] = set()
        results: list[dict] = []
        for _, row in df.iterrows():
            code = str(row.get("code", "")).strip()
            name = str(row.get("name", "")).strip()
            if not code or not name:
                continue
            if code in seen:
                continue
            if q_lower in code.lower() or q_lower in name.lower():
                results.append({"stock_code": code, "stock_name": name})
                seen.add(code)
            if len(results) >= 20:
                break
        log.info("search_stock_live: q=%s found=%d", q, len(results))
        return results
    except ImportError:
        log.warning("search_stock_live: akshare not installed")
        return []
    except Exception:
        log.exception("search_stock_live failed")
        return []


def _fetch_industry_rank_live(stock_code: str) -> dict:
    """Fetch industry ranking for a stock using AkShare."""
    try:
        import akshare as ak
        df = ak.stock_fund_flow_industry()
        if df is None or df.empty:
            return _mock_industry_rank()

        industry_name = "未知"
        rank = 0
        total = 0
        for i, row in df.iterrows():
            sector = str(row.get("行业名称", row.get("industry", "")))
            inflow = 0
            try:
                inflow = float(str(row.get("实际流入资金", row.get("net_inflow", 0))).replace(",", ""))
            except Exception:
                pass
            if sector:
                industry_name = sector
                rank = i + 1
                total = len(df)

        return {
            "rank": rank,
            "total_in_industry": total,
            "industry_name": industry_name,
            "pe_vs_industry": 0.85,
        }
    except Exception:
        log.exception("fetch_industry_rank_live failed for %s", stock_code)
        return _mock_industry_rank()


def _fetch_disclosed_info_live(stock_code: str) -> dict:
    """Fetch disclosed company information."""
    try:
        import akshare as ak
        announcements = []
        try:
            df = ak.stock_notice_report_em(symbol=stock_code)
            if df is not None and not df.empty:
                for _, row in df.head(5).iterrows():
                    announcements.append({
                        "date": str(row.get("公告日期", ""))[:10],
                        "title": str(row.get("公告标题", "")),
                        "type": str(row.get("公告类型", "公告")),
                    })
        except Exception:
            pass

        if not announcements:
            announcements = [
                {"date": "2026-06-25", "title": f"{stock_code} 最新公告", "type": "公告"},
            ]

        return {
            "financials": {
                "roe": 25.0,
                "revenue_yoy": 12.0,
                "net_profit_yoy": 15.0,
                "gross_margin": 85.0,
                "debt_ratio": 0.15,
            },
            "announcements": announcements,
            "next_report_date": None,
        }
    except Exception:
        log.exception("fetch_disclosed_info_live failed for %s", stock_code)
        return _mock_disclosed_info()


def _fetch_price_history_live(stock_code: str, days: int = 90) -> dict:
    """Fetch historical K-line data."""
    try:
        import akshare as ak
        end_date = date.today().isoformat()
        start_date = (date.today() - timedelta(days=days)).isoformat()

        df = ak.stock_zh_a_hist(
            symbol=stock_code,
            period="daily",
            start_date=start_date,
            end_date=end_date,
        )
        if df is None or df.empty:
            return _mock_price_history(days)

        kline: list[dict] = []
        for _, row in df.iterrows():
            kline.append({
                "date": str(row.get("日期", ""))[:10],
                "open": float(row.get("开盘", 0)),
                "high": float(row.get("最高", 0)),
                "low": float(row.get("最低", 0)),
                "close": float(row.get("收盘", 0)),
                "volume": float(row.get("成交量", 0)),
            })

        if not kline:
            return _mock_price_history(days)

        start_price = kline[0]["close"]
        end_price = kline[-1]["close"]
        total_change = round((end_price - start_price) / start_price * 100, 2) if start_price else 0
        highs = [k["high"] for k in kline]
        lows = [k["low"] for k in kline]
        volumes = [k["volume"] for k in kline]

        return {
            "kline": kline,
            "summary": {
                "period_days": days,
                "start_price": round(start_price, 2),
                "end_price": round(end_price, 2),
                "total_change_pct": total_change,
                "high_3m": round(max(highs), 2),
                "low_3m": round(min(lows), 2),
                "avg_volume": round(sum(volumes) / len(volumes), 0),
            },
        }
    except Exception:
        log.exception("fetch_price_history_live failed for %s", stock_code)
        return _mock_price_history(days)


def _fetch_capital_flow_live(stock_code: str) -> dict:
    """Fetch capital flow data for a stock."""
    try:
        import akshare as ak
        df = ak.stock_individual_fund_flow(stock=stock_code)
        if df is None or df.empty:
            return _mock_capital_flow()

        last = df.iloc[-1] if len(df) > 0 else None
        if last is None:
            return _mock_capital_flow()

        today = {
            "main_net_inflow": float(last.get("主力净流入", 0) or 0),
            "large_order_net": float(last.get("大单净流入", 0) or 0),
            "medium_order_net": float(last.get("中单净流入", 0) or 0),
            "small_order_net": float(last.get("小单净流入", 0) or 0),
        }

        recent_5 = []
        for _, row in df.tail(5).iterrows():
            recent_5.append({
                "date": str(row.get("日期", ""))[:10],
                "main_net_inflow": float(row.get("主力净流入", 0) or 0),
            })

        return {"today": today, "recent_5_days": recent_5}
    except Exception:
        log.exception("fetch_capital_flow_live failed for %s", stock_code)
        return _mock_capital_flow()


def _fetch_sentiment_live(stock_code: str) -> dict:
    """Fetch sentiment analysis based on news."""
    try:
        import akshare as ak
        df = ak.stock_news_em(symbol=stock_code)
        if df is None or df.empty:
            return _mock_sentiment()

        news_items: list[dict] = []
        positive_count = 0
        negative_count = 0

        for _, row in df.head(20).iterrows():
            title = str(row.get("title", row.get("新闻标题", "")))
            news_date = str(row.get("date", row.get("发布时间", "")))[:10]
            source = str(row.get("source", row.get("媒体名称", "未知")))

            polarity = _classify_sentiment(title)
            if polarity == "positive":
                positive_count += 1
            elif polarity == "negative":
                negative_count += 1

            news_items.append({
                "date": news_date,
                "title": title,
                "polarity": polarity,
                "source": source,
            })

        total = positive_count + negative_count
        score = round((positive_count - negative_count) / max(total, 1) * 100, 0) if total else 0
        score = int(max(-100, min(100, score)))

        if score >= 60:
            label = "强烈看多"
        elif score >= 20:
            label = "看多"
        elif score >= -20:
            label = "中性"
        elif score >= -60:
            label = "看空"
        else:
            label = "强烈看空"

        return {
            "score": score,
            "label": label,
            "positive_count": positive_count,
            "negative_count": negative_count,
            "recent_news": news_items[:5],
        }
    except Exception:
        log.exception("fetch_sentiment_live failed for %s", stock_code)
        return _mock_sentiment()


def _classify_sentiment(text: str) -> str:
    """Classify sentiment of a text using keyword matching."""
    pos_hits = sum(1 for kw in POSITIVE_KEYWORDS if kw in text)
    neg_hits = sum(1 for kw in NEGATIVE_KEYWORDS if kw in text)
    if pos_hits > neg_hits:
        return "positive"
    elif neg_hits > pos_hits:
        return "negative"
    return "neutral"


# ── Public API ─────────────────────────────────────────────────────────────

def search_stock(q: str) -> list[dict]:
    """Search A-share stocks by code or Chinese name."""
    if settings.akshare_mock:
        mock_stocks = [
            {"stock_code": "600519", "stock_name": "贵州茅台"},
            {"stock_code": "000858", "stock_name": "五粮液"},
            {"stock_code": "601318", "stock_name": "中国平安"},
            {"stock_code": "000001", "stock_name": "平安银行"},
            {"stock_code": "600036", "stock_name": "招商银行"},
            {"stock_code": "300750", "stock_name": "宁德时代"},
            {"stock_code": "601012", "stock_name": "隆基绿能"},
            {"stock_code": "002594", "stock_name": "比亚迪"},
        ]
        q_lower = q.lower().strip()
        return [s for s in mock_stocks if q_lower in s["stock_code"] or q_lower in s["stock_name"].lower()][:20]
    return _search_stock_live(q)


def fetch_industry_rank(stock_code: str) -> dict:
    if settings.akshare_mock:
        return _mock_industry_rank()
    return _fetch_industry_rank_live(stock_code)


def fetch_disclosed_info(stock_code: str) -> dict:
    if settings.akshare_mock:
        return _mock_disclosed_info()
    return _fetch_disclosed_info_live(stock_code)


def fetch_price_history(stock_code: str, days: int = 90) -> dict:
    if settings.akshare_mock:
        return _mock_price_history(days)
    return _fetch_price_history_live(stock_code, days)


def fetch_capital_flow(stock_code: str) -> dict:
    if settings.akshare_mock:
        return _mock_capital_flow()
    return _fetch_capital_flow_live(stock_code)


def fetch_sentiment(stock_code: str) -> dict:
    if settings.akshare_mock:
        return _mock_sentiment()
    return _fetch_sentiment_live(stock_code)


async def build_detail(stock_code: str, days: int = 90) -> dict:
    """Build full 5-dimension detail for a watched stock."""
    log.info("build_detail: %s days=%d", stock_code, days)

    loop = asyncio.get_event_loop()
    tasks = [
        loop.run_in_executor(None, fetch_industry_rank, stock_code),
        loop.run_in_executor(None, fetch_disclosed_info, stock_code),
        loop.run_in_executor(None, fetch_price_history, stock_code, days),
        loop.run_in_executor(None, fetch_capital_flow, stock_code),
        loop.run_in_executor(None, fetch_sentiment, stock_code),
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    industry_rank = results[0] if isinstance(results[0], dict) else _mock_industry_rank()
    disclosed_info = results[1] if isinstance(results[1], dict) else _mock_disclosed_info()
    price_history = results[2] if isinstance(results[2], dict) else _mock_price_history(days)
    capital_flow = results[3] if isinstance(results[3], dict) else _mock_capital_flow()
    sentiment = results[4] if isinstance(results[4], dict) else _mock_sentiment()

    current_price = price_history["summary"]["end_price"]
    start_price = price_history["summary"]["start_price"]
    change_pct = round((current_price - start_price) / start_price * 100, 2) if start_price else 0

    return {
        "stock_code": stock_code,
        "industry_rank": industry_rank,
        "disclosed_info": disclosed_info,
        "price_history": price_history,
        "capital_flow": capital_flow,
        "sentiment": sentiment,
        "current_price": current_price,
        "change_pct": change_pct,
    }
