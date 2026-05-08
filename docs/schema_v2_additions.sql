-- EarningsEdge V2 Schema Additions
-- Run these against your Supabase database

-- Store options-implied moves at prediction time
-- This builds our own historical IV dataset for backtesting
CREATE TABLE IF NOT EXISTS iv_snapshots (
    id SERIAL PRIMARY KEY,
    stock_id INTEGER NOT NULL REFERENCES stocks(id),
    earnings_event_id INTEGER NOT NULL REFERENCES earnings_events(id),
    snapshot_date DATE NOT NULL DEFAULT CURRENT_DATE,
    
    -- Options data at time of prediction
    implied_move_pct DOUBLE PRECISION,       -- ATM straddle implied move %
    atm_iv DOUBLE PRECISION,                 -- ATM implied volatility %
    current_price DOUBLE PRECISION,          -- Stock price at snapshot time
    straddle_price DOUBLE PRECISION,         -- ATM straddle cost
    
    -- After earnings resolves, we fill these in
    actual_move_pct DOUBLE PRECISION,        -- What actually happened
    iv_accuracy_ratio DOUBLE PRECISION,      -- actual/implied (>1 = underpriced)
    
    -- Metadata
    data_source VARCHAR(50) DEFAULT 'marketdata_app',
    created_at TIMESTAMP DEFAULT NOW(),
    
    UNIQUE(stock_id, earnings_event_id)
);

CREATE INDEX ix_iv_snapshots_stock ON iv_snapshots(stock_id);
CREATE INDEX ix_iv_snapshots_event ON iv_snapshots(earnings_event_id);

-- Add new columns to predictions for v2 tracking
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS implied_move_pct DOUBLE PRECISION;
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS iv_vs_actual_ratio DOUBLE PRECISION;

-- Add weighted_beat_rate to feature tracking
-- (stored in feature_importance JSONB, no schema change needed)

-- Add avg_abs_move_prior for magnitude reference
ALTER TABLE earnings_events ADD COLUMN IF NOT EXISTS revenue_actual DOUBLE PRECISION;
ALTER TABLE earnings_events ADD COLUMN IF NOT EXISTS revenue_estimate DOUBLE PRECISION;
