CREATE SCHEMA IF NOT EXISTS finance_control;

CREATE TABLE finance_control.fc_workflow_config (
    task_id VARCHAR(64) PRIMARY KEY,
    is_active BOOLEAN DEFAULT TRUE,
    cron_expression VARCHAR(30) NOT NULL,
    kronos_params JSONB DEFAULT '{"temperature": 0.3, "top_p": 0.85}'::jsonb,
    valuecell_filters JSONB DEFAULT '{"pe_max": 30, "min_inflow": 50000000}'::jsonb,
    llm_prompt_template TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE finance_control.fc_stock_snapshot (
    id BIGSERIAL PRIMARY KEY,
    stock_code VARCHAR(12) NOT NULL,
    trade_date DATE NOT NULL,
    macro_signals JSONB,
    fundamental_data JSONB,
    kronos_prediction JSONB,
    generated_content TEXT,
    status VARCHAR(20) DEFAULT 'PENDING',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_fc_snapshot_code_date UNIQUE (stock_code, trade_date)
);
CREATE INDEX idx_fc_snapshot_date_status ON finance_control.fc_stock_snapshot(trade_date, status);
CREATE INDEX idx_fc_snapshot_code ON finance_control.fc_stock_snapshot(stock_code);

CREATE TABLE finance_control.fc_market_alerts (
    alert_id BIGSERIAL PRIMARY KEY,
    stock_code VARCHAR(12) NOT NULL,
    alert_type VARCHAR(30) NOT NULL,
    direction INT NOT NULL,
    severity VARCHAR(20) NOT NULL,
    event_description TEXT NOT NULL,
    is_handled BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_fc_alerts_handling ON finance_control.fc_market_alerts(is_handled, severity);

CREATE TABLE finance_control.fc_industry_events (
    event_id BIGSERIAL PRIMARY KEY,
    event_title VARCHAR(255) NOT NULL,
    industry_tags JSONB NOT NULL,
    impact_analysis TEXT,
    related_stock_codes JSONB,
    event_time TIMESTAMP NOT NULL
);
CREATE INDEX idx_fc_ind_tags ON finance_control.fc_industry_events USING gin(industry_tags);

CREATE TABLE finance_control.fc_ipo_factory (
    stock_code VARCHAR(12) PRIMARY KEY,
    stock_name VARCHAR(40) NOT NULL,
    ipo_date DATE NOT NULL,
    fundamental_metrics JSONB,
    valuation_score INT DEFAULT 0,
    recommendation_level VARCHAR(20),
    ai_generated_script TEXT,
    status VARCHAR(20) DEFAULT 'PENDING'
);
CREATE INDEX idx_fc_ipo_score ON finance_control.fc_ipo_factory(recommendation_level, valuation_score);

CREATE TABLE finance_control.fc_market_sentiment_snapshot (
    trade_date DATE PRIMARY KEY,
    us_markets JSONB,
    china_concepts_idx JSONB,
    ftse_a50 JSONB,
    prev_day_money_flow JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE finance_control.fc_watchlist (
    id             SERIAL PRIMARY KEY,
    stock_code     VARCHAR(10) NOT NULL UNIQUE,
    stock_name     VARCHAR(50)  NOT NULL,
    industry       VARCHAR(50),
    note           TEXT,
    added_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    cached_details JSONB,
    cached_at      TIMESTAMPTZ
);

INSERT INTO finance_control.fc_workflow_config (task_id, cron_expression, llm_prompt_template)
VALUES ('ipo_sync_daily', '0 8 * * 1-5', '为新股 {stock_name}({stock_code}) 生成打新短视频分镜脚本。')
ON CONFLICT (task_id) DO NOTHING;

-- 既有库补丁：确保 fc_stock_snapshot 上存在 (stock_code, trade_date) 唯一约束，
-- 否则 backtest_engine.record_prediction 的 ON CONFLICT 会在运行时报错。
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uq_fc_snapshot_code_date'
    ) THEN
        ALTER TABLE finance_control.fc_stock_snapshot
            ADD CONSTRAINT uq_fc_snapshot_code_date UNIQUE (stock_code, trade_date);
    END IF;
END $$;
