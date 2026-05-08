/**
 * Core TypeScript types for EarningsEdge frontend.
 */

export interface Stock {
  id: number;
  ticker: string;
  company_name: string;
  sector?: string;
  industry?: string;
  market_cap?: number;
  exchange?: string;
}

export interface StockDetail extends Stock {
  pe_ratio?: number;
  forward_pe?: number;
  revenue_growth_yoy?: number;
  eps_growth_yoy?: number;
  gross_margin?: number;
  debt_to_equity?: number;
}

export interface EarningsEvent {
  id: number;
  ticker: string;
  company_name: string;
  report_date: string;
  fiscal_quarter?: string;
  report_time?: string;
  eps_estimate?: number;
  revenue_estimate?: number;
  eps_actual?: number;
  revenue_actual?: number;
  eps_surprise_pct?: number;
  price_change_pct?: number;
  is_confirmed: boolean;
}

export type Recommendation = "buy" | "sell" | "avoid";

export interface Prediction {
  id: number;
  ticker: string;
  company_name: string;
  description?: string;
  exchange?: string;
  earnings_date?: string;
  recommendation: Recommendation;
  confidence_score: number;
  beat_probability?: number;
  miss_probability?: number;
  price_up_probability?: number;
  price_down_probability?: number;
  expected_move_pct?: number;
  // T+1 and T+3 split predictions
  price_up_probability_t1?: number;
  price_up_probability_t3?: number;
  expected_move_pct_t1?: number;
  expected_move_pct_t3?: number;
  implied_move_pct?: number;
  expected_volatility?: number;
  predicted_direction?: string;
  feature_importance?: Record<string, any>;
  explanation_text?: string;
  actual_outcome?: string;
  actual_move_pct?: number;
  prediction_correct?: boolean;
  model_version: string;
  prediction_date: string;
}
