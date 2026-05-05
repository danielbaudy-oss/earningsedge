-- EarningsEdge Database Schema
-- PostgreSQL 16+

-- Stocks master table
CREATE TABLE stocks (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) UNIQUE NOT NULL,
    company_name VARCHAR(255) NOT NULL,
    sector VARCHAR(100),
    industry VARCHAR(100),
    market_cap DOUBLE PRECISION,
    exchange VARCHAR(20),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX ix_stocks_ticker ON stocks(ticker);
CREATE INDEX ix_stocks_sector ON stocks(sector);
CREATE INDEX ix_stocks_name_search ON stocks(company_name);

-- Earnings events
CREATE TABLE earnings_events (
    id SERIAL PRIMARY KEY,
    stock_id INTEGER NOT NULL REFERENCES stocks(id),
    report_date DATE NOT NULL,
    fiscal_quarter VARCHAR(10),
    fiscal_year INTEGER,
    report_time VARCHAR(20),
    eps_estimate DOUBLE PRECISION,
    revenue_estimate DOUBLE PRECISION,
    eps_actual DOUBLE PRECISION,
    revenue_actual DOUBLE PRECISION,
    eps_surprise DOUBLE PRECISION,
    eps_surprise_pct DOUBLE PRECISION,
    revenue_surprise DOUBLE PRECISION,
    revenue_surprise_pct DOUBLE PRECISION,
    price_before DOUBLE PRECISION,
    price_after DOUBLE PRECISION,
    price_change_pct DOUBLE PRECISION,
    volume_change_pct DOUBLE PRECISION,
    is_confirmed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX ix_earnings_date ON earnings_events(report_date);
CREATE INDEX ix_earnings_stock_date ON earnings_events(stock_id, report_date);

-- Financial metrics (quarterly)
CREATE TABLE financial_metrics (
    id SERIAL PRIMARY KEY,
    stock_id INTEGER NOT NULL REFERENCES stocks(id),
    period_date DATE NOT NULL,
    fiscal_quarter VARCHAR(10),
    revenue DOUBLE PRECISION,
    net_income DOUBLE PRECISION,
    eps DOUBLE PRECISION,
    gross_margin DOUBLE PRECISION,
    operating_margin DOUBLE PRECISION,
    net_margin DOUBLE PRECISION,
    revenue_growth_yoy DOUBLE PRECISION,
    eps_growth_yoy DOUBLE PRECISION,
    revenue_growth_qoq DOUBLE PRECISION,
    total_assets DOUBLE PRECISION,
    total_debt DOUBLE PRECISION,
    cash_and_equivalents DOUBLE PRECISION,
    debt_to_equity DOUBLE PRECISION,
    pe_ratio DOUBLE PRECISION,
    forward_pe DOUBLE PRECISION,
    ps_ratio DOUBLE PRECISION,
    pb_ratio DOUBLE PRECISION,
    analyst_count INTEGER,
    analyst_mean_target DOUBLE PRECISION,
    analyst_revision_up INTEGER,
    analyst_revision_down INTEGER,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX ix_financials_stock_period ON financial_metrics(stock_id, period_date);

-- ML Predictions
CREATE TABLE predictions (
    id SERIAL PRIMARY KEY,
    stock_id INTEGER NOT NULL REFERENCES stocks(id),
    earnings_event_id INTEGER NOT NULL REFERENCES earnings_events(id),
    model_version VARCHAR(50) NOT NULL,
    prediction_date TIMESTAMP DEFAULT NOW(),
    recommendation VARCHAR(10) NOT NULL CHECK (recommendation IN ('buy', 'sell', 'avoid')),
    confidence_score DOUBLE PRECISION NOT NULL CHECK (confidence_score BETWEEN 0 AND 1),
    beat_probability DOUBLE PRECISION,
    miss_probability DOUBLE PRECISION,
    price_up_probability DOUBLE PRECISION,
    price_down_probability DOUBLE PRECISION,
    expected_move_pct DOUBLE PRECISION,
    expected_volatility DOUBLE PRECISION,
    predicted_direction VARCHAR(10),
    feature_importance JSONB,
    explanation_text TEXT,
    actual_outcome VARCHAR(20),
    actual_move_pct DOUBLE PRECISION,
    prediction_correct BOOLEAN,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX ix_predictions_stock_event ON predictions(stock_id, earnings_event_id);
CREATE INDEX ix_predictions_date ON predictions(prediction_date);

-- Sentiment data
CREATE TABLE sentiment_data (
    id SERIAL PRIMARY KEY,
    stock_id INTEGER NOT NULL REFERENCES stocks(id),
    source VARCHAR(50) NOT NULL,
    collected_at TIMESTAMP DEFAULT NOW(),
    sentiment_score DOUBLE PRECISION,
    sentiment_magnitude DOUBLE PRECISION,
    bullish_count INTEGER DEFAULT 0,
    bearish_count INTEGER DEFAULT 0,
    neutral_count INTEGER DEFAULT 0,
    total_mentions INTEGER DEFAULT 0,
    sample_headlines JSONB
);

CREATE INDEX ix_sentiment_stock_date ON sentiment_data(stock_id, collected_at);

-- Macro indicators
CREATE TABLE macro_indicators (
    id SERIAL PRIMARY KEY,
    indicator_date DATE NOT NULL,
    vix DOUBLE PRECISION,
    sp500_return_30d DOUBLE PRECISION,
    treasury_10y DOUBLE PRECISION,
    fed_funds_rate DOUBLE PRECISION,
    unemployment_rate DOUBLE PRECISION,
    cpi_yoy DOUBLE PRECISION,
    sector_etf_returns JSONB
);

CREATE INDEX ix_macro_date ON macro_indicators(indicator_date);

-- User alerts
CREATE TABLE alerts (
    id SERIAL PRIMARY KEY,
    stock_id INTEGER NOT NULL REFERENCES stocks(id),
    user_email VARCHAR(255) NOT NULL,
    days_before INTEGER DEFAULT 3,
    is_active BOOLEAN DEFAULT TRUE,
    last_sent_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX ix_alerts_user ON alerts(user_email);

-- Model performance tracking (feedback loop)
CREATE TABLE model_metrics (
    id SERIAL PRIMARY KEY,
    model_version VARCHAR(50) NOT NULL,
    trained_at TIMESTAMP DEFAULT NOW(),
    training_samples INTEGER,
    accuracy DOUBLE PRECISION,
    precision_beat DOUBLE PRECISION,
    recall_beat DOUBLE PRECISION,
    f1_score DOUBLE PRECISION,
    auc_roc DOUBLE PRECISION,
    direction_accuracy DOUBLE PRECISION,
    mean_absolute_error_move DOUBLE PRECISION,
    top_features JSONB,
    is_active BOOLEAN DEFAULT FALSE
);
