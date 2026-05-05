"""Feature engineering for the earnings prediction model."""

import pandas as pd
import numpy as np
from typing import Optional


def build_feature_vector(
    financial_metrics: dict,
    earnings_history: list[dict],
    sentiment: dict,
    macro: dict,
    analyst_data: dict,
) -> pd.DataFrame:
    """
    Build a feature vector for a single prediction.

    Features grouped by category:
    1. Financial fundamentals
    2. Earnings history patterns
    3. Analyst revisions
    4. Sentiment signals
    5. Macro environment
    6. Technical/momentum
    """
    features = {}

    # --- Financial Fundamentals ---
    features["revenue_growth_yoy"] = financial_metrics.get("revenue_growth_yoy", 0)
    features["eps_growth_yoy"] = financial_metrics.get("eps_growth_yoy", 0)
    features["revenue_growth_qoq"] = financial_metrics.get("revenue_growth_qoq", 0)
    features["gross_margin"] = financial_metrics.get("gross_margin", 0)
    features["operating_margin"] = financial_metrics.get("operating_margin", 0)
    features["net_margin"] = financial_metrics.get("net_margin", 0)
    features["pe_ratio"] = financial_metrics.get("pe_ratio", 0)
    features["forward_pe"] = financial_metrics.get("forward_pe", 0)
    features["ps_ratio"] = financial_metrics.get("ps_ratio", 0)
    features["debt_to_equity"] = financial_metrics.get("debt_to_equity", 0)

    # --- Earnings History Patterns ---
    if earnings_history:
        surprises = [e.get("eps_surprise_pct", 0) for e in earnings_history[:8]]
        features["avg_surprise_pct_4q"] = np.mean(surprises[:4]) if surprises else 0
        features["avg_surprise_pct_8q"] = np.mean(surprises) if surprises else 0
        features["beat_rate_4q"] = sum(1 for s in surprises[:4] if s > 0) / max(len(surprises[:4]), 1)
        features["beat_rate_8q"] = sum(1 for s in surprises if s > 0) / max(len(surprises), 1)
        features["surprise_trend"] = surprises[0] - surprises[-1] if len(surprises) > 1 else 0
        features["max_surprise"] = max(surprises) if surprises else 0
        features["min_surprise"] = min(surprises) if surprises else 0
        features["surprise_volatility"] = np.std(surprises) if len(surprises) > 1 else 0

        # Post-earnings price moves
        moves = [e.get("price_change_pct", 0) for e in earnings_history[:8]]
        features["avg_post_earnings_move"] = np.mean(moves) if moves else 0
        features["post_earnings_move_vol"] = np.std(moves) if len(moves) > 1 else 0
    else:
        for key in [
            "avg_surprise_pct_4q", "avg_surprise_pct_8q", "beat_rate_4q",
            "beat_rate_8q", "surprise_trend", "max_surprise", "min_surprise",
            "surprise_volatility", "avg_post_earnings_move", "post_earnings_move_vol",
        ]:
            features[key] = 0

    # --- Analyst Revisions ---
    features["analyst_count"] = analyst_data.get("analyst_count", 0)
    features["revision_ratio"] = (
        analyst_data.get("revisions_up", 0) /
        max(analyst_data.get("revisions_up", 0) + analyst_data.get("revisions_down", 0), 1)
    )
    features["price_vs_target"] = analyst_data.get("price_vs_target_pct", 0)

    # --- Sentiment ---
    features["news_sentiment"] = sentiment.get("news_sentiment", 0)
    features["reddit_sentiment"] = sentiment.get("reddit_sentiment", 0)
    features["social_volume"] = sentiment.get("total_mentions", 0)
    features["bullish_ratio"] = sentiment.get("bullish_ratio", 0.5)

    # --- Macro Environment ---
    features["vix"] = macro.get("vix", 20)
    features["sp500_return_30d"] = macro.get("sp500_return_30d", 0)
    features["treasury_10y"] = macro.get("treasury_10y", 4.0)
    features["sector_return_30d"] = macro.get("sector_return_30d", 0)

    return pd.DataFrame([features])
