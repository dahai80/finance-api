from __future__ import annotations

from datetime import date, timedelta

import asyncpg

from config import get_logger

log = get_logger("finance.backtest")


async def get_backtest_accuracy(days: int = 30) -> list[dict]:
    """
    Return daily prediction accuracy over the last N trading days.
    Reads from fc_stock_snapshot where status = 'COMPLETED'.
    """
    from storage import get_pg

    pg = await get_pg()
    cutoff = date.today() - timedelta(days=days)

    rows = await pg.fetch(
        """
        SELECT trade_date,
               COUNT(*)                                          AS total_predictions,
               COUNT(CASE WHEN status = 'COMPLETED' THEN 1 END)  AS completed,
               COUNT(CASE WHEN status = 'COMPLETED'
                          AND kronos_prediction IS NOT NULL
                          AND fundamental_data IS NOT NULL
                          AND (kronos_prediction->>'direction') = (fundamental_data->>'actual_direction')
                          THEN 1 END)                             AS correct
        FROM finance_control.fc_stock_snapshot
        WHERE trade_date >= $1
        GROUP BY trade_date
        ORDER BY trade_date
        """,
        cutoff,
    )
    results = []
    for r in rows:
        total = r["total_predictions"] or 0
        correct = r["correct"] or 0
        accuracy = round((correct / total * 100), 1) if total > 0 else 0
        results.append({
            "date": r["trade_date"].isoformat() if isinstance(r["trade_date"], date) else str(r["trade_date"]),
            "total_predictions": total,
            "correct": correct,
            "accuracy": accuracy,
        })
    log.info("backtest_accuracy: %d days returned", len(results))
    return results


async def record_prediction(
    stock_code: str,
    trade_date: date,
    prediction: dict,
    actual: dict | None = None,
) -> int:
    """Record a prediction and optionally the actual result."""
    from storage import get_pg

    pg = await get_pg()
    import json as _json

    row = await pg.fetchrow(
        """
        INSERT INTO finance_control.fc_stock_snapshot
            (stock_code, trade_date, kronos_prediction, fundamental_data, status)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (stock_code, trade_date) DO UPDATE SET
            kronos_prediction = EXCLUDED.kronos_prediction,
            fundamental_data  = EXCLUDED.fundamental_data,
            status            = EXCLUDED.status,
            updated_at        = CURRENT_TIMESTAMP
        RETURNING id
        """,
        stock_code,
        trade_date,
        _json.dumps(prediction) if prediction else None,
        _json.dumps(actual) if actual else None,
        "COMPLETED" if actual else "PENDING",
    )
    return row["id"] if row else 0
