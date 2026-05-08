-- EarningsEdge V3: T+1 and T+3 Predictions
-- Run these against your Supabase database

-- Add T+3 price data to earnings_events
ALTER TABLE earnings_events ADD COLUMN IF NOT EXISTS price_after_t3 DOUBLE PRECISION;
ALTER TABLE earnings_events ADD COLUMN IF NOT EXISTS price_change_pct_t3 DOUBLE PRECISION;

-- Add T+1/T+3 split fields to predictions
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS price_up_probability_t1 DOUBLE PRECISION;
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS price_up_probability_t3 DOUBLE PRECISION;
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS expected_move_pct_t1 DOUBLE PRECISION;
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS expected_move_pct_t3 DOUBLE PRECISION;
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS actual_move_pct_t3 DOUBLE PRECISION;
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS implied_move_pct DOUBLE PRECISION;

-- The existing price_up_probability and expected_move_pct become the "primary" (T+1)
-- T+3 fields are the extended outlook
