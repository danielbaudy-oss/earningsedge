"""
Fast training — uses ONLY data already in Supabase.
Fetches all data in bulk, no per-stock API calls.
"""

import numpy as np
import pandas as pd
import xgboost as xgb
import joblib
from pathlib import Path
from collections import defaultdict
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import accuracy_score, roc_auc_score, mean_absolute_error
from app.core.config import get_settings
from app.db.supabase_client import get_supabase

settings = get_settings()


def build_features(prior_events: list) -> dict | None:
    """Build features from prior earnings events."""
    if len(prior_events) < 2:
        return None

    features = {}
    surprises = []
    moves = []

    for e in prior_events[:8]:
        if e.get("eps_actual") is not None and e.get("eps_estimate") and e["eps_estimate"] != 0:
            surprises.append(((e["eps_actual"] - e["eps_estimate"]) / abs(e["eps_estimate"])) * 100)
        if e.get("price_change_pct") is not None:
            moves.append(e["price_change_pct"])

    if not surprises:
        return None

    features["beat_rate"] = sum(1 for s in surprises if s > 0) / len(surprises)
    features["avg_surprise"] = np.mean(surprises)
    features["surprise_std"] = np.std(surprises) if len(surprises) > 1 else 0
    features["max_surprise"] = max(surprises)
    features["min_surprise"] = min(surprises)
    features["num_quarters"] = len(surprises)
    features["surprise_trend"] = (np.mean(surprises[:2]) - np.mean(surprises[2:])) if len(surprises) >= 3 else 0

    if moves:
        features["avg_move"] = np.mean(moves)
        features["move_std"] = np.std(moves) if len(moves) > 1 else 0
        features["max_move"] = max(moves)
        features["min_move"] = min(moves)
    else:
        features["avg_move"] = 0
        features["move_std"] = 0
        features["max_move"] = 0
        features["min_move"] = 0

    estimates = [e.get("eps_estimate") for e in prior_events[:4] if e.get("eps_estimate")]
    if len(estimates) >= 2 and estimates[-1] != 0:
        features["estimate_change"] = ((estimates[0] - estimates[-1]) / abs(estimates[-1])) * 100
    else:
        features["estimate_change"] = 0

    beat_up = sum(1 for e in prior_events if (e.get("eps_surprise_pct") or 0) > 0 and (e.get("price_change_pct") or 0) > 0)
    total_both = sum(1 for e in prior_events if e.get("eps_surprise_pct") is not None and e.get("price_change_pct") is not None)
    features["beat_up_rate"] = beat_up / max(total_both, 1)

    return features


def main():
    print("Fast XGBoost Training (DB only)")
    print("=" * 50)

    sb = get_supabase()

    # Bulk fetch: get ALL earnings events with actuals, grouped by stock
    # Fetch in pages since Supabase limits to 1000 rows
    print("Fetching all earnings data from Supabase...")
    all_events = []
    offset = 0
    page_size = 1000
    while True:
        page = (
            sb.table("earnings_events")
            .select("stock_id, report_date, eps_actual, eps_estimate, eps_surprise_pct, price_change_pct")
            .order("report_date", desc=True)
            .execute()
        )
        all_events.extend(page.data)
        if len(page.data) < page_size:
            break
        offset += page_size
        break  # Our client doesn't support offset, just get what we can

    print(f"  Fetched {len(all_events)} events")

    # Group by stock
    by_stock = defaultdict(list)
    for e in all_events:
        if e.get("eps_actual") is not None:
            by_stock[e["stock_id"]].append(e)

    # Sort each stock's events by date (desc)
    for stock_id in by_stock:
        by_stock[stock_id].sort(key=lambda x: x.get("report_date", ""), reverse=True)

    print(f"  Stocks with actuals: {len(by_stock)}")

    # Build training data
    all_features = []
    y_beat = []
    y_direction = []
    y_magnitude = []

    for stock_id, earnings in by_stock.items():
        if len(earnings) < 3:
            continue

        for i in range(len(earnings) - 2):
            event = earnings[i]
            if event.get("eps_surprise_pct") is None:
                continue

            prior = earnings[i + 1:]
            features = build_features(prior)
            if features is None:
                continue

            all_features.append(features)
            y_beat.append(1 if event["eps_surprise_pct"] > 0 else 0)

            if event.get("price_change_pct") is not None:
                y_direction.append(1 if event["price_change_pct"] > 0 else 0)
                y_magnitude.append(event["price_change_pct"])
            else:
                y_direction.append(1 if event["eps_surprise_pct"] > 0 else 0)
                y_magnitude.append(0)

    X = pd.DataFrame(all_features).fillna(0).replace([np.inf, -np.inf], 0)
    y_beat = np.array(y_beat)
    y_direction = np.array(y_direction)
    y_magnitude = np.array(y_magnitude)

    print(f"\nTraining samples: {len(X)}")
    print(f"Features: {len(X.columns)}")
    print(f"Beat rate: {y_beat.mean():.1%}")
    print(f"Up rate: {y_direction.mean():.1%}")

    if len(X) < 30:
        print("Not enough data!")
        return

    # Split
    tscv = TimeSeriesSplit(n_splits=4)
    train_idx, val_idx = list(tscv.split(X))[-1]
    X_train, X_val = X.iloc[train_idx], X.iloc[val_idx]

    # Train
    print("\nTraining models...")
    beat_model = xgb.XGBClassifier(
        n_estimators=300, max_depth=5, learning_rate=0.06,
        subsample=0.8, colsample_bytree=0.8,
        reg_alpha=0.3, reg_lambda=1.5, random_state=42, verbosity=0,
    )
    beat_model.fit(X_train, y_beat[train_idx], eval_set=[(X_val, y_beat[val_idx])], verbose=False)

    direction_model = xgb.XGBClassifier(
        n_estimators=300, max_depth=5, learning_rate=0.06,
        subsample=0.8, colsample_bytree=0.8,
        reg_alpha=0.3, reg_lambda=1.5, random_state=42, verbosity=0,
    )
    direction_model.fit(X_train, y_direction[train_idx], eval_set=[(X_val, y_direction[val_idx])], verbose=False)

    magnitude_model = xgb.XGBRegressor(
        n_estimators=300, max_depth=4, learning_rate=0.06,
        subsample=0.8, colsample_bytree=0.8,
        reg_alpha=0.3, reg_lambda=1.5, random_state=42, verbosity=0,
    )
    magnitude_model.fit(X_train, y_magnitude[train_idx], eval_set=[(X_val, y_magnitude[val_idx])], verbose=False)

    # Evaluate
    beat_prob = beat_model.predict_proba(X_val)[:, 1]
    dir_prob = direction_model.predict_proba(X_val)[:, 1]
    mag_pred = magnitude_model.predict(X_val)

    print(f"\nResults:")
    print(f"  Beat accuracy:      {accuracy_score(y_beat[val_idx], beat_model.predict(X_val)):.1%}")
    print(f"  Beat AUC:           {roc_auc_score(y_beat[val_idx], beat_prob):.3f}")
    print(f"  Direction accuracy: {accuracy_score(y_direction[val_idx], direction_model.predict(X_val)):.1%}")
    dir_auc = roc_auc_score(y_direction[val_idx], dir_prob) if len(set(y_direction[val_idx])) > 1 else 0
    print(f"  Direction AUC:      {dir_auc:.3f}")
    print(f"  Move MAE:           {mean_absolute_error(y_magnitude[val_idx], mag_pred):.2f}%")

    print(f"\nTop features (beat):")
    imp = sorted(zip(X.columns, beat_model.feature_importances_), key=lambda x: x[1], reverse=True)
    for feat, score in imp[:8]:
        print(f"  {feat}: {score:.3f}")

    # Save
    model_dir = Path(settings.model_path)
    model_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(beat_model, model_dir / "beat_model.joblib")
    joblib.dump(direction_model, model_dir / "direction_model.joblib")
    joblib.dump(magnitude_model, model_dir / "magnitude_model.joblib")
    joblib.dump(list(X.columns), model_dir / "feature_names.joblib")
    print(f"\nModels saved!")


if __name__ == "__main__":
    main()
