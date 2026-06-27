from __future__ import annotations

import os

import httpx

from config import get_logger

log = get_logger("finance.llm")

LLM_BASE = os.environ.get("FINANCE_LLM_BASE_URL", "http://localhost:8080")
LLM_MODEL = os.environ.get("FINANCE_LLM_MODEL", "qwen2.5-7b-instruct")
LLM_TIMEOUT = float(os.environ.get("FINANCE_LLM_TIMEOUT", "60"))

SCRIPT_PROMPT = """为新股 {name}({code}) 生成短视频分镜脚本。

基本信息:
- 发行价: {price}
- 发行市盈率: {pe}
- 行业市盈率: {industry_pe}
- 综合评分: {score}/100
- 推荐等级: {rec}

要求:
1. 5个分镜,每个50字
2. 包含: 开场钩子、核心卖点、风险提示、行动号召
3. 语言风格: 财经博主,通俗易懂
"""


async def generate_ipo_script(stock: dict) -> str | None:
    fm = stock.get("fundamental_metrics") or {}
    prompt = SCRIPT_PROMPT.format(
        name=stock.get("stock_name", "未知"),
        code=stock.get("stock_code", "未知"),
        price=fm.get("price", "未知"),
        pe=fm.get("pe", "未知"),
        industry_pe=fm.get("industry_pe", "未知"),
        score=stock.get("valuation_score", 0),
        rec=stock.get("recommendation_level", "未知"),
    )

    log.info("llm request: %s(%s) score=%s", stock.get("stock_name"), stock.get("stock_code"), stock.get("valuation_score"))

    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(
                f"{LLM_BASE}/v1/chat/completions",
                json={
                    "model": LLM_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 1200,
                    "temperature": 0.7,
                },
                timeout=LLM_TIMEOUT,
            )
            res.raise_for_status()
            data = res.json()
            content = data["choices"][0]["message"]["content"]
            log.info("llm response ok: %d chars", len(content))
            return content
    except httpx.ConnectError:
        log.warning("llm not available at %s (is mlx running?)", LLM_BASE)
        return None
    except Exception as exc:
        log.error("llm generation failed: %s", exc)
        return None


async def generate_batch(stocks: list[dict], min_score: int = 60) -> list[dict]:
    results = []
    for stock in stocks:
        if stock.get("valuation_score", 0) < min_score:
            continue
        script = await generate_ipo_script(stock)
        if script:
            results.append({
                "stock_code": stock.get("stock_code"),
                "stock_name": stock.get("stock_name"),
                "script": script,
            })
    log.info("batch generation: %d/%d scripts created", len(results), len(stocks))
    return results
