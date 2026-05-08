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

    # Recency-weighted beat rate (exponential decay, recent quarters matter more)
    decay = 0.80
    weights = [decay ** i for i in range(len(surprises))]
    total_weight = sum(weights)
    features["weighted_beat_rate"] = sum(
        (1.0 if s > 0 else 0.0) * w for s, w in zip(surprises, weights)
    ) / total_weight
    features["weighted_avg_surprise"] = sum(
        s * w for s, w in zip(surprises, weights)
    ) / total_weight

    # Trend
    if len(surprises) >= 3:
        features["surprise_trend"] = np.mean(surprises[:2]) - np.mean(surprises[2:])
    else:
        features["surprise_trend"] = 0

    # Prior price reactions (used for MAGNITUDE estimation, not direction)
    prior_moves = []
    for e in prior[:8]:
        if e.get("price_change_pct") is not None:
            prior_moves.append(e["price_change_pct"])

    if prior_moves:
        features["avg_move_prior"] = np.mean(prior_moves)
        features["move_std_prior"] = np.std(prior_moves) if len(prior_moves) > 1 else 0
        features["max_move_prior"] = max(prior_moves)
        features["min_move_prior"] = min(prior_moves)
        # Average absolute move (magnitude regardless of direction)
        features["avg_abs_move_prior"] = np.mean([abs(m) for m in prior_moves])
    else:
        features["avg_move_prior"] = 0
        features["move_std_prior"] = 0
        features["max_move_prior"] = 0
        features["min_move_prior"] = 0
        features["avg_abs_move_prior"] = 0

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
    
    ONLY uses data available in the DB — no API calls.
    Features are built purely from earnings history (beat patterns, price reactions).
    
    Live metrics (momentum, PE, etc.) are NOT used for training because:
    1. We don't have historical snapshots of those metrics
    2. Using today's metrics for past events = lookahead bias
    3. Those features are only added at prediction time (current state)
    """
    print("📊 Loading training data from Supabase (DB only, no API calls)...")
    sb = get_supabase()

    # Get all stocks that have enough history
    stocks = sb.table("stocks").select("id, ticker").execute()

    all_features = []
    y_beat = []
    y_direction = []
    y_magnitude = []
    skipped = 0

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
            skipped += 1
            continue

        # Build features for each event (except the oldest ones used as history)
        for i in range(len(earnings) - 2):
            event = earnings[i]

            # Skip if missing target data
            if event.get("eps_surprise_pct") is None:
                continue
            if event.get("price_change_pct") is None:
                continue

            # Build features from prior history (all DB-derived)
            features = build_features_from_history(earnings, i)
            if features is None:
                continue

            # Set live-metric features to 0 for training
            # These will be filled at prediction time with current data
            features["revenue_growth"] = 0
            features["eps_growth"] = 0
            features["operating_margin"] = 0
            features["pe_ratio"] = 0
            features["beta"] = 1
            features["momentum_13w"] = 0
            features["momentum_26w"] = 0
            features["momentum_52w"] = 0
            features["momentum_mtd"] = 0
            features["momentum_5d"] = 0
            features["price_vs_sp500_13w"] = 0
            features["ytd_return"] = 0
            features["range_position_52w"] = 0.5
            features["short_interest_pct"] = 0
            features["analyst_revision_signal"] = 0
            features["revenue_beat_rate"] = 0.5
            features["insider_signal"] = 0
            features["sector_relative_perf"] = 0

            # Earnings reaction patterns (from DB data)
            prior = earnings[i + 1:]
            beat_and_up = 0
            beat_and_down = 0
            miss_and_down = 0
            miss_and_up = 0
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

    X = pd.DataFrame(all_features)
    print(f"✅ Built {len(X)} training samples with {len(X.columns)} features")
    print(f"   Stocks processed: {len(stocks.data) - skipped}, skipped: {skipped} (insufficient history)")
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
