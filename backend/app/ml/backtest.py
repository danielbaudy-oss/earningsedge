"""
Backtesting Engine for EarningsEdge

Instead of waiting months for new predictions to resolve, this module:
1. Takes historical earnings events where we KNOW the outcome
2. Reconstructs what the indicators would have been at that point
3. Runs the prediction logic against those historical snapshots
4. Compares predictions to actual outcomes
5. Reports accuracy metrics

This gives us immediate feedback on model changes without waiting for future earnings.

Usage:
    python -m app.ml.backtest
    python -m app.ml.backtest --ticker AAPL
    python -m app.ml.backtest --last-n 50
"""

import asyncio
import httpx
import numpy as np
import pandas as pd
from datetime import date, timedelta
from dataclasses import dataclass, field
from app.core.config import get_settings
from app.db.supabase_client import get_supabase
from app.ml.predict_with_model import (
    load_models,
    recency_weighted_beat_rate,
    recency_weighted_surprise,
    compute_direction_from_current_signals,
    compute_iv_signal,
    calculate_risk_score,
    generate_recommendation,
)
from app.ml.train_xgboost import build_features_from_history, fetch_finnhub

settings = get_settings()


@dataclass
class BacktestResult:
    """Result of a single backtested prediction."""
    ticker: str
    report_date: str
    predicted_beat: bool
    actual_beat: bool
    predicted_direction: str  # "up" or "down"
    actual_direction: str
    predicted_move: float
    actual_move: float
    recommendation: str
    total_score: int
    beat_prob: float
    direction_prob: float
    correct_beat: bool = field(init=False)
    correct_direction: bool = field(init=False)
    move_error: float = field(init=False)

    def __post_init__(self):
        self.correct_beat = self.predicted_beat == self.actual_beat
        self.correct_direction = self.predicted_direction == self.actual_direction
        self.move_error = abs(self.predicted_move - self.actual_move)


@dataclass
class BacktestSummary:
    """Aggregate metrics from backtesting."""
    total_events: int
    beat_accuracy: float
    direction_accuracy: float
    avg_move_error: float
    recommendation_accuracy: float  # buy=up, sell=down
    avg_score_when_correct: float
    avg_score_when_wrong: float
    results: list[BacktestResult]

    def print_report(self):
        print("\n" + "=" * 60)
        print("📊 BACKTEST RESULTS")
        print("=" * 60)
        print(f"  Events tested: {self.total_events}")
        print(f"  Beat prediction accuracy: {self.beat_accuracy:.1%}")
        print(f"  Direction accuracy: {self.direction_accuracy:.1%}")
        print(f"  Avg move error: {self.avg_move_error:.2f}%")
        print(f"  Recommendation accuracy: {self.recommendation_accuracy:.1%}")
        print(f"  Avg score (correct): {self.avg_score_when_correct:.0f}")
        print(f"  Avg score (wrong): {self.avg_score_when_wrong:.0f}")
        print("=" * 60)

        # Show worst misses
        wrong = [r for r in self.results if not r.correct_direction]
        if wrong:
            print(f"\n❌ Worst direction misses ({len(wrong)} total):")
            worst = sorted(wrong, key=lambda r: r.move_error, reverse=True)[:5]
            for r in worst:
                print(f"  {r.ticker} ({r.report_date}): predicted {r.predicted_direction} "
                      f"({r.direction_prob:.0%}), actual {r.actual_direction} "
                      f"({r.actual_move:+.1f}%), score={r.total_score}")

        # Show best calls
        right = [r for r in self.results if r.correct_direction]
        if right:
            print(f"\n✅ Best direction calls ({len(right)} total):")
            best = sorted(right, key=lambda r: abs(r.actual_move), reverse=True)[:5]
            for r in best:
                print(f"  {r.ticker} ({r.report_date}): predicted {r.predicted_direction} "
                      f"({r.direction_prob:.0%}), actual {r.actual_move:+.1f}%, score={r.total_score}")


async def backtest_single_event(
    client: httpx.AsyncClient,
    ticker: str,
    stock_id: int,
    event_index: int,
    all_earnings: list,
    metrics: dict,
    mode: str = "trader",
) -> BacktestResult | None:
    """
    Backtest a single historical earnings event.
    
    event_index: which event in the list we're "predicting" (0 = most recent)
    We use only data BEFORE this event (no lookahead).
    """
    event = all_earnings[event_index]

    # Must have actual outcome data
    if event.get("eps_surprise_pct") is None or event.get("price_change_pct") is None:
        return None

    # Build features from prior history (same as training)
    features = build_features_from_history(all_earnings, event_index)
    if features is None:
        return None

    # Prior earnings (for recency weighting)
    prior_earnings = all_earnings[event_index + 1:]

    # Recency-weighted beat metrics
    features["weighted_beat_rate"] = recency_weighted_beat_rate(prior_earnings)
    features["weighted_avg_surprise"] = recency_weighted_surprise(prior_earnings)

    # Add fundamental features from metrics (note: this uses current metrics,
    # which is a known limitation — we can't perfectly reconstruct past metrics)
    features["revenue_growth"] = metrics.get("revenueGrowthTTMYoy", 0) or 0
    features["eps_growth"] = metrics.get("epsGrowthTTMYoy", 0) or 0
    features["operating_margin"] = metrics.get("operatingMarginTTM", 0) or 0
    features["pe_ratio"] = metrics.get("peTTM", 0) or 0
    features["beta"] = metrics.get("beta", 1) or 1

    # Momentum — we CAN reconstruct this from price history
    # For now use current metrics (limitation noted)
    momentum_13w = metrics.get("13WeekPriceReturnDaily", 0) or 0
    momentum_mtd = metrics.get("monthToDatePriceReturnDaily", 0) or 0
    momentum_signal = momentum_13w if abs(momentum_13w) > abs(momentum_mtd) else momentum_mtd

    features["momentum_13w"] = momentum_13w
    features["momentum_26w"] = metrics.get("26WeekPriceReturnDaily", 0) or 0
    features["momentum_52w"] = metrics.get("52WeekPriceReturnDaily", 0) or 0
    features["momentum_mtd"] = momentum_mtd
    features["momentum_5d"] = metrics.get("5DayPriceReturnDaily", 0) or 0
    features["price_vs_sp500_13w"] = metrics.get("priceRelativeToS&P50013Week", 0) or 0
    features["ytd_return"] = metrics.get("yearToDatePriceReturnDaily", 0) or 0
    features["range_position_52w"] = 0.5  # Can't reconstruct easily

    # These signals we can't reconstruct for past events, so use neutral
    features["short_interest_pct"] = 0
    features["analyst_revision_signal"] = 0
    features["revenue_beat_rate"] = 0.5
    features["insider_signal"] = 0
    features["sector_relative_perf"] = 0

    # Reaction patterns from prior data
    beat_and_up = 0
    beat_and_down = 0
    miss_and_down = 0
    miss_and_up = 0
    for p in prior_earnings[:6]:
        surprise = p.get("eps_surprise_pct", 0) or 0
        move = p.get("price_change_pct")
        if move is not None:
            if surprise > 0 and move > 0:
                beat_and_up += 1
            elif surprise > 0 and move <= 0:
                beat_and_down += 1
            elif surprise <= 0 and move < 0:
                miss_and_down += 1
            elif surprise <= 0 and move >= 0:
                miss_and_up += 1

    total_with_moves = beat_and_up + beat_and_down + miss_and_down + miss_and_up
    if total_with_moves > 0:
        features["beat_leads_to_up_rate"] = beat_and_up / max(beat_and_up + beat_and_down, 1)
        features["miss_leads_to_down_rate"] = miss_and_down / max(miss_and_down + miss_and_up, 1)
        features["reaction_predictability"] = (beat_and_up + miss_and_down) / total_with_moves
    else:
        features["beat_leads_to_up_rate"] = 0.5
        features["miss_leads_to_down_rate"] = 0.5
        features["reaction_predictability"] = 0.5

    # Load models and predict
    beat_model, direction_model, magnitude_model, feature_names = load_models()
    if beat_model is None:
        return None

    X = pd.DataFrame([features])
    for col in feature_names:
        if col not in X.columns:
            X[col] = 0
    X = X[feature_names].fillna(0).replace([np.inf, -np.inf], 0)

    # ML predictions
    beat_prob_raw = float(beat_model.predict_proba(X)[0][1])
    direction_prob_raw = float(direction_model.predict_proba(X)[0][1])
    raw_move = float(magnitude_model.predict(X)[0])

    # Apply v2 improvements
    weighted_beat = features["weighted_beat_rate"]
    beat_prob = beat_prob_raw * 0.6 + weighted_beat * 0.4

    direction_prob = compute_direction_from_current_signals(
        features, direction_prob_raw, beat_prob, momentum_signal
    )

    # Expected move (magnitude only from history)
    prior_moves = [e.get("price_change_pct", 0) for e in prior_earnings
                   if e.get("price_change_pct") is not None]
    if prior_moves and len(prior_moves) >= 2:
        avg_abs_move = float(np.mean([abs(m) for m in prior_moves]))
        volatility = float(np.std(prior_moves))
    else:
        avg_abs_move = max(1.5, features.get("beta", 1) * 2.5)
        volatility = avg_abs_move * 1.2

    avg_abs_move = max(0.5, min(avg_abs_move, 20.0))

    if direction_prob > 0.55:
        expected_move = avg_abs_move * (direction_prob - 0.5) * 2
    elif direction_prob < 0.45:
        expected_move = -avg_abs_move * (0.5 - direction_prob) * 2
    else:
        expected_move = raw_move * 0.5

    expected_move = round(expected_move, 1)

    # Score and recommendation
    risk_score = calculate_risk_score(beat_prob, direction_prob, expected_move, volatility,
                                      features.get("beta", 1))

    fundamentals_signal = min(max((features.get("revenue_growth", 0) + 10) / 40, 0), 1)
    risk_bonus = (100 - risk_score) / 100
    signals_bonus = 0.5  # Neutral for backtest (can't reconstruct analyst/insider)

    total_score = int(
        signals_bonus * 40 +
        beat_prob * 20 +
        direction_prob * 20 +
        fundamentals_signal * 10 +
        risk_bonus * 10
    )
    total_score = max(5, min(95, total_score))

    recommendation = generate_recommendation(total_score, mode, risk_score, beat_prob, direction_prob)

    # Actual outcomes
    actual_beat = event["eps_surprise_pct"] > 0
    actual_move = event["price_change_pct"]
    actual_direction = "up" if actual_move > 0 else "down"

    return BacktestResult(
        ticker=ticker,
        report_date=event.get("report_date", "unknown"),
        predicted_beat=beat_prob > 0.5,
        actual_beat=actual_beat,
        predicted_direction="up" if direction_prob > 0.5 else "down",
        actual_direction=actual_direction,
        predicted_move=expected_move,
        actual_move=actual_move,
        recommendation=recommendation,
        total_score=total_score,
        beat_prob=beat_prob,
        direction_prob=direction_prob,
    )


async def run_backtest(ticker: str = None, last_n: int = None, mode: str = "trader") -> BacktestSummary:
    """
    Run backtest across all stocks (or a specific ticker).
    
    For each stock, we test on the most recent events where we have outcomes,
    using only prior data for features.
    """
    print("🔬 Running backtest...\n")
    sb = get_supabase()
    client = httpx.AsyncClient(timeout=30.0)

    # Get stocks to test
    if ticker:
        stocks = sb.table("stocks").select("id, ticker").eq("ticker", ticker).execute()
    else:
        stocks = sb.table("stocks").select("id, ticker").execute()

    results: list[BacktestResult] = []

    for stock in stocks.data:
        stk_ticker = stock["ticker"]

        # Get all historical earnings with outcomes
        events = (
            sb.table("earnings_events")
            .select("report_date, eps_actual, eps_estimate, eps_surprise_pct, price_change_pct")
            .eq("stock_id", stock["id"])
            .lte("report_date", date.today().isoformat())
            .order("report_date", desc=True)
            .limit(12)
            .execute()
        )

        earnings = events.data
        if len(earnings) < 4:  # Need at least 4: 1 to test + 2 for features + 1 buffer
            continue

        # Fetch metrics once per stock
        metrics_data = await fetch_finnhub(client, "stock/metric", {"symbol": stk_ticker, "metric": "all"})
        metrics = (metrics_data or {}).get("metric", {}) if isinstance(metrics_data, dict) else {}

        # Test on events 0 through N-3 (need at least 2 prior for features)
        test_range = min(len(earnings) - 3, 4)  # Test up to 4 most recent events
        for i in range(test_range):
            result = await backtest_single_event(
                client, stk_ticker, stock["id"], i, earnings, metrics, mode
            )
            if result:
                results.append(result)

        await asyncio.sleep(1.2)  # Rate limit

    await client.aclose()

    if not results:
        print("No events to backtest.")
        return BacktestSummary(
            total_events=0, beat_accuracy=0, direction_accuracy=0,
            avg_move_error=0, recommendation_accuracy=0,
            avg_score_when_correct=0, avg_score_when_wrong=0, results=[]
        )

    # Apply last_n filter
    if last_n:
        results = results[:last_n]

    # Calculate metrics
    beat_correct = sum(1 for r in results if r.correct_beat)
    dir_correct = sum(1 for r in results if r.correct_direction)
    move_errors = [r.move_error for r in results]

    # Recommendation accuracy: buy should go up, sell should go down
    rec_results = []
    for r in results:
        if r.recommendation == "buy":
            rec_results.append(r.actual_move > 0)
        elif r.recommendation == "sell":
            rec_results.append(r.actual_move < 0)
        # "avoid" is not counted

    rec_accuracy = sum(rec_results) / len(rec_results) if rec_results else 0

    correct_scores = [r.total_score for r in results if r.correct_direction]
    wrong_scores = [r.total_score for r in results if not r.correct_direction]

    summary = BacktestSummary(
        total_events=len(results),
        beat_accuracy=beat_correct / len(results),
        direction_accuracy=dir_correct / len(results),
        avg_move_error=np.mean(move_errors),
        recommendation_accuracy=rec_accuracy,
        avg_score_when_correct=np.mean(correct_scores) if correct_scores else 0,
        avg_score_when_wrong=np.mean(wrong_scores) if wrong_scores else 0,
        results=results,
    )

    summary.print_report()
    return summary


if __name__ == "__main__":
    import sys

    ticker = None
    last_n = None
    mode = "trader"

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--ticker" and i + 1 < len(args):
            ticker = args[i + 1]
            i += 2
        elif args[i] == "--last-n" and i + 1 < len(args):
            last_n = int(args[i + 1])
            i += 2
        elif args[i] == "--mode" and i + 1 < len(args):
            mode = args[i + 1]
            i += 2
        else:
            i += 1

    asyncio.run(run_backtest(ticker=ticker, last_n=last_n, mode=mode))
