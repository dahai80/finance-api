# OpenClaw Finance API

Python 后端中枢，为 openclaw-mission-macos 提供 A 股数据、IPO 评分、行业情报、自选股、K 线预测等能力。

## 架构

```
Next.js Frontend → API Proxy → finance-api (FastAPI) → PostgreSQL + Redis + 多数据源(Sina/AkShare/Tushare)
```

## 可靠性与可信度

股票系统对数据准确性与可用性要求极高。本服务在代码层落实以下策略：

- **多源回退 + 熔断**：`data_provider/multi_source_fetcher.py` 维护线程安全的熔断器（`_CircuitBreaker`），单源连续失败自动熔断，自动切换备用源；全部失效时返回 mock 并打标。
- **数据可信度信封**：所有可能回退 mock 的接口统一返回 `{data, source: "real"|"mock", ok: bool}`，前端据此显示「模拟数据」徽标，绝不把伪造数据当真实数据呈现。
- **股价零伪造**：`/api/market/quotes` 只返回真实行情（新浪 hq 实时报价），无 mock 分支；部分获取失败时返回已得部分，不编造价格。
- **并发安全**：DB/Redis 连接池采用 `asyncio.Lock` 双检锁单例；熔断器、行业动态缓存均用 `threading.Lock` 保护；WebSocket 广播先快照连接集合避免「迭代中修改」。
- **超时不阻塞事件循环**：同步数据源调用通过 daemon 线程 + `queue.Queue` 实现超时（`signal.alarm` 仅主线程可用，故替换）。
- **优雅降级**：Redis 不可用时资金流接口返回空数组并告警，而非抛 500；调度任务全部 try/except，单任务失败不影响其他任务。
- **真实健康检查**：`/health` 实际探测 DB（`SELECT 1`）与 Redis（`ping`），返回 `ok`/`degraded` 就绪状态。

> 单实例无法物理保证 99.99999% 可用性，以上为代码层的稳定性与可信度保障。

## 快速开始

### 1. 安装依赖

```bash
cd /Users/dahai/solution/openclaw-mission-macos/finance-api
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
- `fc_alerts` / `fc_market_alerts` - 异动预警
- `fc_predictions` - 预测记录
- `fc_watchlist` - 自选股
- `fc_market_sentiment_snapshot` - 情绪快照
- `fc_workflow_config` - 工作流配置

### 3. 配置环境变量

```bash
# ~/.zshrc 或项目 .env
export TUSHARE_TOKEN="your_token_here"
export FINANCE_AKSHARE_MOCK=1  # 1=mock模式, 0=实时数据
export FINANCE_FORCE_REAL_DATA=0  # 1=mock 不可用时直接 503，不降级
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
# 健康检查（含 DB/Redis 探活）
curl http://localhost:8000/health

# 同步新股（mock模式）
curl -X POST http://localhost:8000/api/ipo/sync

# 查询新股
curl http://localhost:8000/api/ipo

# 实时行情（多只，股价零伪造）
curl "http://localhost:8000/api/market/quotes?codes=600519,000001"
```

## API 路由

> 返回信封 `{data, source, ok}` 的接口会在数据源失效时降级为 mock 并标记 `source:"mock"`；`/quotes` 例外，绝不伪造股价。

### Health 健康检查

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 就绪探活，探测 DB + Redis，返回 `{status, service, akshare_mock, checks}` |

### IPO 新股

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/ipo` | 查询新股列表，支持分页、搜索、评分筛选 |
| POST | `/api/ipo/sync` | 同步新股数据并评分 |

**查询参数**: `limit`(默认50) / `offset`(默认0) / `status` / `min_score` / `search`

### Market 行情

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/market/money-flow` | 板块资金流向（Redis ZSET） |
| GET | `/api/market/individual-money-flow` | 个股资金流排名（信封） |
| GET | `/api/market/quotes?codes=` | 实时行情，最多 50 只，**零伪造** |
| GET | `/api/market/alerts` | 异动预警列表 |
| POST | `/api/market/alerts` | 创建异动预警 |
| GET | `/api/market/sentiment` | 市场情绪分析 |
| POST | `/api/market/sentiment/snapshot` | 保存当日情绪快照 |
| GET | `/api/market/kline/predict` | K线预测（需 kronos 服务） |
| GET | `/api/market/kronos/health` | Kronos 服务健康检查 |
| GET | `/api/market/snapshots` | 股票快照列表 |
| POST | `/api/market/trigger/money-flow` | 手动触发资金流刷新 |
| POST | `/api/market/trigger/sentiment` | 手动触发情绪刷新 |
| POST | `/api/market/trigger/all` | 手动触发资金流 + 情绪 |

### Industry 行业

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/industry/events` | 行业事件列表 |
| POST | `/api/industry/events` | 创建行业事件 |
| GET | `/api/industry/top-stocks` | 各行业 Top 股票（信封） |
| GET | `/api/industry/news` | 各行业最新动态（信封） |

### Watchlist 自选股

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/watchlist` | 列出全部自选股 |
| POST | `/api/watchlist` | 添加自选股 |
| GET | `/api/watchlist/search?q=` | 按代码/名称搜索 A 股 |
| POST | `/api/watchlist/refresh-all` | 强制刷新全部自选股 |
| DELETE | `/api/watchlist/{stock_code}` | 移除自选股 |
| GET | `/api/watchlist/{stock_code}/detail` | 五维详情（缓存优先，过期则实时刷新） |
| POST | `/api/watchlist/{stock_code}/refresh` | 强制刷新单只自选股 |

详情返回包含 `sources`（各维度 real/mock）与全局 `source`/`ok`，前端据此显示「模拟数据」徽标。

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

**推荐等级**: `HIGH`(≥70) / `MID`(≥50) / `LOW`(<50)

## 定时任务 (APScheduler)

6 个内置调度任务（均为工作日）：

| 任务 | 时间 | 说明 |
|------|------|------|
| `ipo_sync` | 08:00 | 同步新股数据并评分 |
| `premarket_sentiment` | 08:30 | 盘前情绪快照（美股/概念/A50） |
| `money_flow` | 盘中每 5 分钟 (9:30-15:00) | 更新板块资金流向 |
| `industry_news` | 每 10 分钟 (8:30-16:00) | 刷新各行业动态缓存 |
| `daily_content` | 15:15 | 高评分新股生成短视频脚本（LLM） |
| `watchlist_refresh` | 15:30 | 盘后自选股数据刷新 |

## 前端集成

Next.js 代理路由：`src/app/api/finance/[...path]/route.ts`

前端页面（4 个 Tab）：
- **Dashboard** - 异动预警 + 资金流向 + 市场情绪
- **Industry** - 行业热度卡片 + 事件时间轴 + 各行业 Top 股票/动态
- **IPO** - 新股看板 + 五维雷达图（recharts）
- **Backtest** - 预测准确率曲线 + 转化率图
- **Watchlist** - 自选股五维详情 + 模拟数据徽标

## 测试

```bash
.venv/bin/python -m pytest tests/ -v
# 测试结果：40 passed, 1 skipped
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
├── main.py                      # FastAPI 应用入口 + 全局异常中间件 + CORS
├── config.py                    # 配置与日志
├── storage.py                   # PostgreSQL + Redis 存储层（双检锁单例）
├── scheduler.py                 # APScheduler 定时任务（6 个）
├── routers/                     # API 路由
│   ├── health.py                # 健康检查（DB/Redis 探活）
│   ├── ipo.py                   # IPO 新股
│   ├── market.py                # 市场行情 + 触发器
│   ├── industry.py              # 行业情报 + Top 股票/动态
│   ├── watchlist.py             # 自选股
│   ├── backtest.py              # 策略回测
│   ├── kronos.py                # Kronos 健康检查
│   └── ws.py                    # WebSocket 实时推送
├── data_provider/               # 数据源与算法
│   ├── multi_source_fetcher.py  # 多源回退 + 熔断 + 缓存（核心）
│   ├── watchlist_fetcher.py     # 自选股五维详情（含 source 标记）
│   ├── akshare_fetcher.py       # AkShare 实时数据抓取
│   ├── tushare_fetcher.py       # Tushare 历史数据抓取
│   ├── ipo_scorer.py            # IPO 五维评分
│   ├── industry_map.py          # 行业热度映射
│   ├── llm_generator.py         # LLM 脚本生成
│   ├── kronos_client.py         # Kronos K线预测客户端
│   └── backtest_engine.py       # 回测引擎
├── sql/                         # 数据库脚本
│   └── init.sql                 # DDL 建表语句
├── tests/                       # 测试用例 (40 passed, 1 skipped)
└── requirements.txt             # Python 依赖
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

MIT License.
