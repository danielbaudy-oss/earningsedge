"""
Train XGBoost model on real earnings data.

Uses historical earnings events with:
- EPS surprise data (beat/miss)
- Post-earnings price reactions
- Enrichment from Finnhub (analyst data, financials)

Trains 3 models:
1. Beat classifier: P(EPS beat)
2. Direction classifier: P(stock goes up after earnings)
3. Move regressor: Expected % price change
"""

import asyncio
import httpx
import numpy as np
import pandas as pd
import xgboost as xgb
import joblib
from pathlib import Path
from datetime import date
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import accuracy_score, roc_auc_score, mean_absolute_error
from app.core.config import get_settings
from app.db.supabase_client import get_supabase

settings = get_settings()
FINNHUB_BASE = "https://finnhub.io/api/v1"


async def fetch_finnhub(client: httpx.AsyncClient, endpoint: str, params: dict):
    params["token"] = settings.finnhub_api_key
    try:
        resp = await client.get(f"{FINNHUB_BASE}/{endpoint}", params=params)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


def build_features_from_history(earnings: list, event_index: int) -> dict | None:
    """
    Build feature vector for a single earnings event using prior history.
    event_index: which event we're predicting (0 = most recent)
    Uses only data BEFORE this event (no lookahead).
    """
    # We need at least 2 prior events to build features
    prior = earnings[event_index + 1:]
    if len(prior) < 2:
        return None

    features = {}

    # Prior surprises
    surprises = []
    for e in prior[:8]:
        actual = e.get("eps_actual")
        estimate = e.get("eps_estimate")
        if actual is not None and estimate is not None and estimate != 0:
            surprises.append(((actual - estimate) / abs(estimate)) * 100)

    if not surprises:
        return None

    features["beat_rate_prior"] = sum(1 for s in surprises if s > 0) / len(surprises)
    features["avg_surprise_prior"] = np.mean(surprises)
    features["surprise_std_prior"] = np.std(surprises) if len(surprises) > 1 else 0
    features["max_surprise_prior"] = max(surprises)
    features["min_surprise_prior"] = min(surprises)
    features["num_prior_quarters"] = len(surprises)

    # Trend
    if len(surprises) >= 3:
        features["surprise_trend"] = np.mean(surprises[:2]) - np.mean(surprises[2:])
    else:
        features["surprise_trend"] = 0

    # Prior price reactions
    prior_moves = []
    for e in prior[:8]:
        if e.get("price_change_pct") is not None:
            prior_moves.append(e["price_change_pct"])

    if prior_moves:
        features["avg_move_prior"] = np.mean(prior_moves)
        features["move_std_prior"] = np.std(prior_moves) if len(prior_moves) > 1 else 0
        features["max_move_prior"] = max(prior_moves)
        features["min_move_prior"] = min(prior_moves)
    else:
        features["avg_move_prior"] = 0
        features["move_std_prior"] = 0
        features["max_move_prior"] = 0
        features["min_move_prior"] = 0

    # Estimate direction (are estimates going up or down?)
    estimates = [e.get("eps_estimate") for e in prior[:4] if e.get("eps_estimate") is not None]
    if len(estimates) >= 2 and estimates[-1] != 0:
        features["estimate_change_pct"] = ((estimates[0] - estimates[-1]) / abs(estimates[-1])) * 100
    else:
        features["estimate_change_pct"] = 0

    # Current event estimate vs prior actuals
    current = earnings[event_index]
    current_estimate = current.get("eps_estimate")
    prior_actuals = [e.get("eps_actual") for e in prior[:4] if e.get("eps_actual") is not None]
    if current_estimate and prior_actuals and prior_actuals[0]:
        features["estimate_vs_prior_actual"] = ((current_estimate - prior_actuals[0]) / abs(prior_actuals[0])) * 100
    else:
        features["estimate_vs_prior_actual"] = 0

    return features


async def load_training_data() -> tuple[pd.DataFrame, np.ndarray, np.ndarray, np.ndarray]:
    """
    Load training data from Supabase.
    For each stock, use its earnings history to build features for each event.
    """
    print("📊 Loading training data from Supabase...")
    sb = get_supabase()
    client = httpx.AsyncClient(timeout=30.0)

    # Get all stocks
    stocks = sb.table("stocks").select("id, ticker").execute()

    all_features = []
    y_beat = []
    y_direction = []
    y_magnitude = []

    for stock in stocks.data:
        ticker = stock["ticker"]

        # Get all historical earnings for this stock (ordered by date desc)
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
        if len(earnings) < 3:
            continue

        # Also fetch Finnhub metrics for enrichment
        metrics_data = await fetch_finnhub(client, "stock/metric", {"symbol": ticker, "metric": "all"})
        metrics = (metrics_data or {}).get("metric", {}) if isinstance(metrics_data, dict) else {}

        # Build features for each event (except the oldest ones used as history)
        for i in range(len(earnings) - 2):
            event = earnings[i]

            # Skip if missing target data
            if event.get("eps_surprise_pct") is None:
                continue
            if event.get("price_change_pct") is None:
                continue

            # Build features from prior history
            features = build_features_from_history(earnings, i)
            if features is None:
                continue

            # Add fundamental features (static for now, from latest metrics)
            features["revenue_growth"] = metrics.get("revenueGrowthTTMYoy", 0) or 0
            features["eps_growth"] = metrics.get("epsGrowthTTMYoy", 0) or 0
            features["operating_margin"] = metrics.get("operatingMarginTTM", 0) or 0
            features["pe_ratio"] = metrics.get("peTTM", 0) or 0
            features["beta"] = metrics.get("beta", 1) or 1

            # Price momentum / trend from Finnhub
            features["momentum_13w"] = metrics.get("13WeekPriceReturnDaily", 0) or 0
            features["momentum_26w"] = metrics.get("26WeekPriceReturnDaily", 0) or 0
            features["momentum_52w"] = metrics.get("52WeekPriceReturnDaily", 0) or 0
            features["momentum_mtd"] = metrics.get("monthToDatePriceReturnDaily", 0) or 0
            features["momentum_5d"] = metrics.get("5DayPriceReturnDaily", 0) or 0
            features["price_vs_sp500_13w"] = metrics.get("priceRelativeToS&P50013Week", 0) or 0
            features["ytd_return"] = metrics.get("yearToDatePriceReturnDaily", 0) or 0

            # 52-week range position (how close to high vs low)
            high_52w = metrics.get("52WeekHigh", 0) or 0
            low_52w = metrics.get("52WeekLow", 0) or 0
            if high_52w > 0 and low_52w > 0 and high_52w != low_52w:
                # Approximate current price from midpoint (we don't have exact current)
                # Use YTD return to estimate position
                features["range_position_52w"] = max(0, min(1, (high_52w - low_52w * 1.1) / (high_52w - low_52w)))
            else:
                features["range_position_52w"] = 0.5

            # Earnings target hit patterns
            # How often does this stock beat AND go up? (the correlation matters)
            beat_and_up = 0
            beat_and_down = 0
            miss_and_down = 0
            miss_and_up = 0
            prior = earnings[i + 1:]
            for p in prior[:6]:
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

            all_features.append(features)

            # Targets
            y_beat.append(1 if event["eps_surprise_pct"] > 0 else 0)
            y_direction.append(1 if event["price_change_pct"] > 0 else 0)
            y_magnitude.append(event["price_change_pct"])

        await asyncio.sleep(1.2)  # Finnhub rate limit

    await client.aclose()

    X = pd.DataFrame(all_features)
    print(f"✅ Built {len(X)} training samples with {len(X.columns)} features")
    print(f"   Beat rate: {np.mean(y_beat):.1%}, Up rate: {np.mean(y_direction):.1%}")
    print(f"   Avg move: {np.mean(y_magnitude):+.2f}%, Std: {np.std(y_magnitude):.2f}%")

    return X, np.array(y_beat), np.array(y_direction), np.array(y_magnitude)


def train_models(X: pd.DataFrame, y_beat: np.ndarray,
                 y_direction: np.ndarray, y_magnitude: np.ndarray) -> dict:
    """Train XGBoost models and return metrics."""
    print("\n🤖 Training XGBoost models...")

    # Handle any NaN/inf values
    X = X.fillna(0).replace([np.inf, -np.inf], 0)

    # Time-series split (no future leakage)
    tscv = TimeSeriesSplit(n_splits=3)
    splits = list(tscv.split(X))
    train_idx, val_idx = splits[-1]

    X_train, X_val = X.iloc[train_idx], X.iloc[val_idx]
    y_beat_train, y_beat_val = y_beat[train_idx], y_beat[val_idx]
    y_dir_train, y_dir_val = y_direction[train_idx], y_direction[val_idx]
    y_mag_train, y_mag_val = y_magnitude[train_idx], y_magnitude[val_idx]

    # --- Beat Model ---
    beat_model = xgb.XGBClassifier(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.08,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_alpha=0.5,
        reg_lambda=1.5,
        eval_metric="logloss",
        random_state=42,
        verbosity=0,
    )
    beat_model.fit(X_train, y_beat_train,
                   eval_set=[(X_val, y_beat_val)], verbose=False)

    # --- Direction Model ---
    direction_model = xgb.XGBClassifier(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.08,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_alpha=0.5,
        reg_lambda=1.5,
        eval_metric="logloss",
        random_state=42,
        verbosity=0,
    )
    direction_model.fit(X_train, y_dir_train,
                        eval_set=[(X_val, y_dir_val)], verbose=False)

    # --- Magnitude Model ---
    magnitude_model = xgb.XGBRegressor(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.08,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_alpha=0.5,
        reg_lambda=1.5,
        eval_metric="rmse",
        random_state=42,
        verbosity=0,
    )
    magnitude_model.fit(X_train, y_mag_train,
                        eval_set=[(X_val, y_mag_val)], verbose=False)

    # --- Evaluate ---
    beat_pred = beat_model.predict(X_val)
    beat_prob = beat_model.predict_proba(X_val)[:, 1]
    dir_pred = direction_model.predict(X_val)
    dir_prob = direction_model.predict_proba(X_val)[:, 1]
    mag_pred = magnitude_model.predict(X_val)

    metrics = {
        "beat_accuracy": accuracy_score(y_beat_val, beat_pred),
        "beat_auc": roc_auc_score(y_beat_val, beat_prob) if len(set(y_beat_val)) > 1 else 0,
        "direction_accuracy": accuracy_score(y_dir_val, dir_pred),
        "direction_auc": roc_auc_score(y_dir_val, dir_prob) if len(set(y_dir_val)) > 1 else 0,
        "move_mae": mean_absolute_error(y_mag_val, mag_pred),
        "training_samples": len(X_train),
        "validation_samples": len(X_val),
    }

    print(f"\n📈 Model Performance (validation set):")
    print(f"   Beat prediction:     {metrics['beat_accuracy']:.1%} accuracy, {metrics['beat_auc']:.3f} AUC")
    print(f"   Direction prediction: {metrics['direction_accuracy']:.1%} accuracy, {metrics['direction_auc']:.3f} AUC")
    print(f"   Move prediction:     {metrics['move_mae']:.2f}% MAE")

    # Feature importance
    print(f"\n🔑 Top features (beat model):")
    importance = dict(zip(X.columns, beat_model.feature_importances_))
    sorted_imp = sorted(importance.items(), key=lambda x: x[1], reverse=True)
    for feat, imp in sorted_imp[:8]:
        print(f"   {feat}: {imp:.3f}")

    # Save models
    model_dir = Path(settings.model_path)
    model_dir.mkdir(parents=True, exist_ok=True)

    joblib.dump(beat_model, model_dir / "beat_model.joblib")
    joblib.dump(direction_model, model_dir / "direction_model.joblib")
    joblib.dump(magnitude_model, model_dir / "magnitude_model.joblib")
    joblib.dump(list(X.columns), model_dir / "feature_names.joblib")
    print(f"\n💾 Models saved to {model_dir}")

    return metrics, beat_model, direction_model, magnitude_model


async def main():
    """Full training pipeline."""
    print("🚀 EarningsEdge XGBoost Training Pipeline\n" + "=" * 50)

    X, y_beat, y_direction, y_magnitude = await load_training_data()

    if len(X) < 20:
        print(f"❌ Not enough training data ({len(X)} samples). Need at least 20.")
        return

    metrics, _, _, _ = train_models(X, y_beat, y_direction, y_magnitude)

    print("\n" + "=" * 50)
    print("✅ Training complete!")
    return metrics


if __name__ == "__main__":
    asyncio.run(main())
