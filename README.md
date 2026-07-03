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
- **实时价鲜活标志**：自选股详情额外返回 `price_live: bool`。`current_price` 必须来自新浪实时报价才置 `true`；实时取价失败时回落到昨日收盘价并置 `price_live=false`，前端显示「价格非实时」徽标。`ok` 同时要求 `price_live`——缓存中的旧收盘价绝不会被当成当前价呈现给交易决策。
- **字段名对齐数据源**：个股资金流使用 akshare 真实列名（`主力净流入-净额`/`大单净流入-净额`/`中单净流入-净额`/`小单净流入-净额`），行业资金流使用 `行业`/`净额`；行业排名按个股**真实所属行业**（`stock_individual_info_em`）在资金流表中定位并排序，不再取最后一条或硬编码 `pe_vs_industry`；`disclosed_info` 的财务指标无实盘来源，恒为 `is_mock=true`，且不伪造公告文本。
- **并发安全**：DB/Redis 连接池采用 `asyncio.Lock` 双检锁单例；`storage.close()` 同样在锁内执行并吞异常，避免并发关闭双释放；`upsert_ipo` 包在事务内，单行失败整体回滚；熔断器、行业动态缓存均用 `threading.Lock` 保护；WebSocket 广播先快照连接集合避免「迭代中修改」。
- **超时不阻塞事件循环**：所有同步 akshare 调用统一走 `async_utils.call_with_timeout`（daemon 线程 + `queue.Queue`，`signal.alarm` 仅主线程可用故替换），既不阻塞事件循环也不泄漏执行器线程；`build_detail` 每个维度外加 15s `wait_for`，任一维度超时即降级 mock 不拖垮整体。
- **后台任务强引用**：`async_utils.spawn_background_task` 持有 `asyncio.Task` 强引用集合并回调清理，避免 `asyncio.create_task` 返回的 Task 被 GC 中途回收（路由层 cache-first 刷新全部改用此助手）。
- **优雅关闭**：lifespan 以 `try/finally` 包裹，`sched.shutdown(wait=False)` 不等待挂起任务，`storage.close()` 限时 10s，确保进程能快速退出不被卡死。
- **调度健壮性**：所有 `add_job` 带 `replace_existing=True`（重复启动不崩）、`misfire_grace_time=300`、`coalesce=True`（积压合并执行）；IPO 同步的逐行评分独立 try/except，单行失败不影响其余。
- **输入边界**：`/api/ipo` 列表对 `limit/offset/min_score/search/status` 做上下界裁剪，防止无界结果集与负偏移；WebSocket 连接上限 100，超出礼貌关闭。
- **错误不外泄**：全局异常中间件返回通用 `{"error":"internal_error","ok":false}`，不向客户端暴露异常类型与消息文本。
- **优雅降级**：Redis 不可用时资金流接口返回空数组并告警，而非抛 500；调度任务全部 try/except，单任务失败不影响其他任务。
- **真实健康检查**：`/health` 实际探测 DB（`SELECT 1`）与 Redis（`ping`），每探测加 2-3s `wait_for` 超时防半开连接挂起；任一依赖不可用即返回 `degraded` **并置 HTTP 503**，负载均衡只看状态码时绝不把流量路由到依赖掉线的节点（伪健康检查比没有更糟）。错误信息只暴露异常类型，不泄露连接串。
- **缓存优先 + 实时价覆盖**：高耗时接口（行业 Top 股票、行业动态、个股资金流）采用进程内 TTL 缓存 + 路由层 cache-first，命中即 <10ms 返回，缓存为空时立即返回 mock（`ok:false`）绝不阻塞用户请求，后台异步刷新填充。自选股详情缓存命中时仍用新浪实时价覆盖 `current_price` 并重算 `change_pct`，保证缓存期间价格零时延——流畅性与准确性兼得。
- **生产时延**：全量接口实测 P50 < 30ms（行情直连新浪 ~30ms，其余缓存命中 < 10ms），冷启动不阻塞。

### 第二轮全量评审加固（round 2）

第二轮对全量代码做的纵深加固，聚焦股价零容忍与配置漂移：

- **NaN 绕过防御**：`watchlist_fetcher._f` 把 akshare 单元格统一解析为 float，NaN/inf/非法一律归 0；K 线解析用 `if not (close > 0): continue`（`NaN <= 0` 为 False，旧 `<= 0` 守卫放过 NaN 污染股价）。所有 open/high/low/close/volume 字段必经 `_f`。
- **section 级 source 诚实**：`build_detail` 的 `any_mock` 排除 `disclosed_info`——该维度无实盘来源恒为 mock 是设计如此，不应因此把整条详情打成 `source=mock`（旧逻辑让 `price_live` 徽标成为死代码，实时价永远显示成模拟）。
- **overlay 价格鲜活重算**：`_overlay_live_price` 进入即置 `price_live=false`（缓存价最久 2h 前），仅当新浪实时价为正时置 true，并在所有返回路径（早退/异常/正常）重算 `ok = source!=mock and price_live`——缓存里的旧收盘价绝不冒充当前价。
- **唯一约束补齐**：`fc_stock_snapshot` 加 `UNIQUE(stock_code, trade_date)`，`backtest_engine.record_prediction` 的 `ON CONFLICT` 依赖它，否则运行时炸 500；`init.sql` 既在 `CREATE TABLE` 内声明，又追加幂等 `DO $$ ... ADD CONSTRAINT` 给既有库打补丁。
- **配置单源**：`kronos_client`/`llm_generator` 原各自读 `FINANCE_KRONOS_*`/`FINANCE_LLM_*` 环境变量，与 `config.py` 的 `KRONOS_URL`/`LLM_URL` 双源漂移、生产静默连错主机；统一改读 `settings.*`，并新增 `settings.kronos_timeout`。
- **kronos 预测校验**：`_valid_pred` 丢弃 open/high/low/close 非有限正数的预测，脏数据不透传客户端。
- **Redis socket 超时**：`aioredis.from_url` 显式 `socket_timeout=2, socket_connect_timeout=2`，Redis 卡死时快速失败而非堆积挂起。
- **close() 竞态修复**：`storage.close()` 先把全局 `_pool`/`_redis` 置空再 `await close()`，避免关闭期间 `get_pg` fast-path 把半关池子发给并发请求。
- **回测天数边界**：`/api/backtest` 的 `days` 裁到 `[1, 365]`，极端值不再触发 `OverflowError→500`。
- **行业 Top 股票 stale 标志**：`ok` 跟随缓存 `stale` 状态，盘后/调度挂掉时陈旧价不标 `ok=true`。
- **tushare 行情留空**：`_fetch_industry_top_stocks_tushare` 的 `price/change_pct` 留 `None`（tushare ths_cons 只给分类不给行情），不再用 `0.0` 冒充真实价。
- **coroutine 关闭**：`spawn_background_task` 在无运行 loop 分支补 `coro.close()`，消除「coroutine was never awaited」告警。
- **IPO 评分舍入**：`score_ipo` 总分 `int(round(...))`，修正 69.9 被截成 69 误判 HIGH→MID。

### 第三轮全量评审加固（round 3）

第三轮聚焦回测正确性、静默数据丢失、shutdown 竞态与异常脱敏：

- **回测准确率结构性 0%**：`get_backtest_accuracy` 的 SQL 比对 `kronos_prediction->>'direction'`，但 `kronos_client` 只输出 ohlc 无 `direction` 字段 → 预测方向恒 NULL → accuracy 永远 0%。改为从 `close vs open` 推导预测方向（UP/DOWN/FLAT）再比对 `actual_direction`；分母由 `total` 改 `completed`（旧把 PENDING 计入分母压低准确率）。
- **kronos 桩数据地雷**：`routers/kronos.py` ImportError 分支原返回捏造价格（`stub:True`，违反股价零容忍）。该路由未在 main.py 注册（孤立），但仍是地雷；改为返回 503 绝不捏造价，并补 `PredictRequest.days` 边界、统一 sys.path、异常脱敏。
- **静默丢数据：个股资金流历史**：`upsert_sentiment_snapshot` 接收 `prev_day_individual_flow` 参数却从不写入 SQL，调度器/trigger 传入的个股资金流被静默丢弃；`init.sql` 补 `prev_day_individual_flow JSONB` 列（CREATE TABLE 声明 + 既有库幂等 ALTER），upsert 的 INSERT/ON CONFLICT 补该列，`get_sentiment_snapshot` 反序列化也补该列。
- **JSONB 字符串反序列化**：asyncpg 默认未注册 JSONB codec，`get_industry_events`（industry_tags/related_stock_codes）与 `get_stock_snapshots`（macro_signals/fundamental_data/kronos_prediction）的 JSONB 列可能以 str 返回；补 `isinstance(str)` 守卫 + `json.loads`，与 `list_ipo` 一致。
- **资金流写失败谎报成功**：`replace_live_money_flow` 改返回 `bool`；`_job_money_flow` 与 `trigger_money_flow` 检查返回值，写 Redis 失败不广播/不谎报 `status:ok`（改 `degraded`），并加 zset TTL 3600s 防调度中断后陈旧数据无限残留。
- **IPO 评分两条路径分歧**：`routers/ipo.py` 的 `_score_with_industry_heat` 用 `int(sum())` 截断，与 `ipo_scorer.score_ipo` 的 `int(round())` 不一致 → 同一 IPO 经不同入口评分不同；统一为 `int(round())`。调度器 `_job_ipo_sync` 改用同一 `_score_with_industry_heat`（含真实行业热度），消除调度用启发式、路由用真实热度的分歧。
- **情绪快照 0.0 冒充真实价**：`save_sentiment_snapshot` 默认 `us_markets={"sp500":0.0,...}` 把 0 当真实美股指数价写入；改 `{"status":"no_data"}`。
- **市场阶段误判**：`get_sentiment` 的 `market_phase` 原靠 money_flow 是否为空判断（Redis 空=盘前），误判；改用实际交易时段（9:30-11:30 / 13:00-15:00，周一至周五）。
- **资金流出榜与流入榜重叠**：`top_outflow` 原取 `money_flow[-3:] if len>=3`，3≤len<6 时与 `top_inflow[:3]` 重叠；改 `len>=6`。
- **shutdown 竞态**：`storage` 加 `_closing` 标志，`close()` 置 True，`get_pg`/`get_redis` fast-path 与锁内双重检查，关闭期间新请求直接抛 RuntimeError 而非拿到半关连接。
- **Redis URL 脱敏**：`get_redis` 日志原打印含密码的完整 URL；改只记 `host:port`，与 pg_dsn 一致。
- **WS 广播 head-of-line blocking**：`broadcast_alert` 原串行 `send_text`，一个慢/半开客户端阻塞全部；改 `asyncio.gather` + 单客户端 5s 超时。ping 探活同样加 5s 发送超时，半开连接不再挂住。
- **cron 缺 15:00 收盘窗**：`money_flow`/`individual_money_flow` 原 `hour="9-14"`（最后 14:55），漏 15:00 收盘；改 `9-15`。
- **daily_content 半写**：`_job_daily_content` 的 UPDATE 循环无事务，中途失败留半写；改事务包裹全成功或全回滚。
- **mock 污染缓存**：`watchlist_detail`/`refresh_all`/`refresh_watchlist_item` 原无条件缓存 `build_detail` 结果（含 mock）2h；改仅 `source != "mock"` 才缓存。`datetime.utcnow()`（3.12+ 弃用且与 PG `NOW()` 时区错配致缓存永不过期）改 `datetime.now()`。
- **Pydantic 字段边界**：`MarketAlertCreate`/`WatchlistAddRequest`/`IndustryEventCreate` 原字段无长度/范围限制（DoS/脏写面）；补 `max_length`/`ge`/`le`。
- **异常脱敏**：`trigger_money_flow`/`trigger_sentiment`/`trigger_industry_top_stocks` 原返回 `message=str(exc)` 泄露内部细节；改脱敏固定串。
- **get_event_loop 弃用**：13 处 `asyncio.get_event_loop()`（3.12+ 无运行 loop 时抛 RuntimeError）改 `get_running_loop()`。

### 已知技术债（已评估，非股价关键，留待后续）

- 写端点鉴权：所有 POST/DELETE 路由无鉴权（CRITICAL）。系统部署在 Next.js API 代理后，鉴权可能由前端层承担；直接加 auth 可能破坏前端，留待部署架构确认后实施。当前以 Pydantic 字段边界 + 6 位代码校验作纵深防御。
- `record_prediction` 无调用方：回测录入路径未接调度/路由，`fc_stock_snapshot` 预测数据为空，`get_backtest_accuracy` 返回空直至录入路径接通。
- 评分路径未完全统一：`_score_with_industry_heat` 仍位于 `routers/ipo.py`，调度器跨模块 import；后续移至 `ipo_scorer.py`。
- `generate_batch` 串行调 LLM，量大时慢；非股价路径，暂未并发化。
- 缺索引：`fc_industry_events(event_time)`、`fc_ipo_factory(ipo_date)`——数据量增大后需补。
- `TIMESTAMPTZ` 与 `TIMESTAMP` 在 `init.sql` 中混用，后续统一为带时区。
- tushare 同步调用未加超时（分支休眠，需 `TUSHARE_TOKEN` 才生效）。
- 连接池 `max_size=5` 偏小，高并发可调 10；`get_pg`/`get_redis` 共用 `_init_lock`（非重入），首请求串行，可拆分两把锁。
- 缓存刷新无 per-key 去重：并发请求可能触发 N 个后台刷新任务（industry_top_stocks / industry_news / individual_money_flow）。
- `quotes`/`sentiment` 端点未加 `{ok,source}` 信封（契约变更需前端协同，未改；价格路径已无 mock 兜底）。
- IPO 详情 `price=0.0` 可能被当真实（`akshare_fetcher.py`，MEDIUM）——非实时交易路径。
- 测试套件 40 例中约 18 例偏轻量，关键路径（overlay price_live、close 竞态、kronos 校验、backtest 方向推导）尚无专测，后续补强。

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

8 个内置调度任务（均为工作日）：

| 任务 | 时间 | 说明 |
|------|------|------|
| `ipo_sync` | 08:00 | 同步新股数据并评分 |
| `premarket_sentiment` | 08:30 | 盘前情绪快照（美股/概念/A50） |
| `money_flow` | 盘中每 5 分钟 (9:30-15:00) | 更新板块资金流向 |
| `industry_news` | 每 10 分钟 (8:30-16:00) | 刷新各行业动态缓存 |
| `industry_top_stocks` | 每 10 分钟 (8:30-16:00) | 刷新各行业 Top 股票缓存 |
| `individual_money_flow` | 盘中每 5 分钟 (9:00-15:00) | 刷新个股资金流缓存 |
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
├── async_utils.py               # 后台任务强引用 + 同步调用超时（共享助手）
├── scheduler.py                 # APScheduler 定时任务（8 个）
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
