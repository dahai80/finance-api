# OpenClaw Finance API

Python 后端中枢，为 openclaw-mission-macos 提供 A 股数据、IPO 评分、行业情报、K 线预测等能力。

## 架构

```
Next.js Frontend → API Proxy → finance-api (FastAPI) → PostgreSQL + Redis + AkShare
```

## 快速开始

### 1. 安装依赖

```bash
cd /Users/dahai/solution/finance-api
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 初始化数据库

```bash
psql -U dahai -d openclaw_finance -f sql/init.sql
```

创建 6 张表：
- `fc_ipo_factory` - IPO 新股工厂
- `fc_stock_snapshot` - 股票快照（回测数据源）
- `fc_industry_events` - 行业事件
- `fc_money_flow` - 资金流向
- `fc_alerts` - 异动预警
- `fc_predictions` - 预测记录

### 3. 配置环境变量

```bash
# ~/.zshrc 或项目 .env
export TUSHARE_TOKEN="your_token_here"
export FINANCE_AKSHARE_MOCK=1  # 1=mock模式, 0=实时数据
export FINANCE_LLM_BASE_URL="http://localhost:8080"  # mlx OpenAI兼容API
export FINANCE_LLM_MODEL="qwen2.5-7b-instruct"
```

### 4. 启动服务

```bash
# 启动 finance-api
uvicorn main:app --reload --port 8000

# 启动 facecat-kronos 微服务（可选）
cd /Users/dahai/solution/facecat-kronos/kronos-api
uvicorn main:app --port 8001
```

### 5. 验证

```bash
# 健康检查
curl http://localhost:8000/health

# 同步新股（mock模式）
curl -X POST http://localhost:8000/api/ipo/sync

# 查询新股
curl http://localhost:8000/api/ipo
```

## API 路由

### IPO 新股

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/ipo` | 查询新股列表，支持分页、搜索、评分筛选 |
| POST | `/api/ipo/sync` | 同步新股数据并评分 |

**查询参数**:
- `limit` (int, default=50) - 返回条数
- `offset` (int, default=0) - 偏移量
- `status` (str) - 状态筛选
- `min_score` (int) - 最低评分筛选
- `search` (str) - 按股票代码或名称搜索

### Market 行情

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/market/money-flow` | 板块资金流向（Redis ZSET） |
| GET | `/api/market/alerts` | 异动预警列表（fc_market_alerts） |
| POST | `/api/market/alerts` | 创建异动预警 |
| GET | `/api/market/sentiment` | 市场情绪分析（fc_market_sentiment_snapshot） |
| POST | `/api/market/sentiment/snapshot` | 保存当日情绪快照 |
| GET | `/api/market/kline/predict` | K线预测（需 kronos 服务） |
| GET | `/api/market/kronos/health` | Kronos 服务健康检查 |
| GET | `/api/market/snapshots` | 股票快照列表（fc_stock_snapshot） |

### Industry 行业

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/industry/events` | 行业事件列表 |
| POST | `/api/industry/events` | 创建行业事件 |

**创建事件请求体**:
```json
{
  "event_title": "半导体行业政策利好",
  "industry_tags": ["半导体", "芯片"],
  "impact_analysis": "正面影响",
  "related_stock_codes": ["301800", "688700"]
}
```

### Backtest 回测

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/backtest/accuracy` | 预测准确率曲线（30天） |

## IPO 五维雷达评分

每只新股生成 0-100 综合评分，5 个维度各 20 分：

| 维度 | 权重 | 计算公式 |
|------|------|----------|
| 估值折扣 | 20 | `(行业PE - 发行PE) / 行业PE * 100` |
| 财务成长 | 20 | 中签率倒数作为需求代理 |
| 行业热度 | 20 | 板块资金净流入排名（AkShare） |
| 机构态度 | 20 | 询价倍数 × 报价家数 |
| 破发风险 | 20 | `100 - (发行PE/行业PE * 50)` |

**推荐等级**:
- `HIGH`: 总分 ≥ 70
- `MID`: 总分 ≥ 50
- `LOW`: 总分 < 50

## 定时任务 (APScheduler)

3 个内置调度任务：

| 任务 | 时间 | 说明 |
|------|------|------|
| `ipo_sync` | 每天 08:00 | 同步新股数据并评分 |
| `money_flow` | 盘中每 5 分钟 (9:30-15:00) | 更新板块资金流向 |
| `daily_content` | 每天 15:15 | 高评分新股生成短视频脚本（LLM） |

## 前端集成

Next.js 代理路由：`src/app/api/finance/[...path]/route.ts`

前端页面（4 个 Tab）：
- **Dashboard** - 异动预警 + 资金流向 + 市场情绪
- **Industry** - 行业热度卡片 + 事件时间轴
- **IPO** - 新股看板 + 五维雷达图（recharts）
- **Backtest** - 预测准确率曲线 + 转化率图

## 测试

```bash
# 运行所有测试
.venv/bin/python -m pytest tests/ -v

# 测试结果：22 passed, 1 skipped
```

## 依赖

- **Python 3.14+**
- **FastAPI 0.115+** - Web 框架
- **asyncpg** - 异步 PostgreSQL 驱动
- **redis.asyncio** - 异步 Redis 客户端
- **akshare 1.18.64** - A 股数据源
- **tushare 1.4.29** - 备用数据源（需 Token）
- **APScheduler** - 内嵌定时任务调度

## 目录结构

```
finance-api/
├── main.py                 # FastAPI 应用入口
├── config.py              # 配置与日志
├── storage.py             # PostgreSQL + Redis 存储层
├── scheduler.py           # APScheduler 定时任务
├── routers/               # API 路由
│   ├── health.py          # 健康检查
│   ├── ipo.py             # IPO 新股
│   ├── market.py          # 市场行情
│   ├── industry.py        # 行业情报
│   ├── backtest.py        # 策略回测
│   └── ws.py              # WebSocket 实时推送
├── data_provider/         # 数据源与算法
│   ├── akshare_fetcher.py # AkShare 数据抓取
│   ├── ipo_scorer.py      # IPO 五维评分
│   ├── industry_map.py    # 行业热度映射
│   ├── llm_generator.py   # LLM 脚本生成
│   ├── kronos_client.py   # Kronos K线预测客户端
│   └── backtest_engine.py # 回测引擎
├── sql/                   # 数据库脚本
│   └── init.sql           # DDL 建表语句
├── tests/                 # 测试用例
│   ├── test_api.py        # IPO API 测试
│   ├── test_db.py         # 数据库测试
│   ├── test_fetcher.py    # 数据抓取测试
│   ├── test_industry.py   # 行业 API 测试
│   ├── test_market.py     # 市场 API 测试
│   └── test_backtest.py   # 回测 API 测试
├── requirements.txt       # Python 依赖
└── README.md            # 本文档
```

## 本地服务端口

| 服务 | 端口 | 说明 |
|------|------|------|
| finance-api | 8000 | FastAPI 主服务 |
| facecat-kronos | 8001 | K线预测微服务 |
| Next.js | 3000 | 前端开发服务器 |
| PostgreSQL | 5432 | 数据库 |
| Redis | 6379 | 缓存与实时推送 |

## 许可证

Internal use only.
