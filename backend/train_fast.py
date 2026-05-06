"""
Fast training — uses ONLY data already in Supabase.
No API calls. Builds features purely from earnings history.
"""

import numpy as np
import pandas as pd
import xgboost as xgb
import joblib
from pathlib import Path
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import accuracy_score, roc_auc_score, mean_absolute_error
from app.core.config import get_settings
from app.db.supabase_client import get_supabase

settings = get_settings()


def build_features(prior_events: list) -> dict | None:
    """Build features from prior earnings events only (no API calls)."""
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

    if len(surprises) >= 3:
        features["surprise_trend"] = np.mean(surprises[:2]) - np.mean(surprises[2:])
    else:
        features["surprise_trend"] = 0

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

    # Estimate direction
    estimates = [e.get("eps_estimate") for e in prior_events[:4] if e.get("eps_estimate")]
    if len(estimates) >= 2 and estimates[-1] != 0:
        features["estimate_change"] = ((estimates[0] - estimates[-1]) / abs(estimates[-1])) * 100
    else:
        features["estimate_change"] = 0

    # Beat-to-move correlation
    beat_up = sum(1 for e in prior_events if (e.get("eps_surprise_pct") or 0) > 0 and (e.get("price_change_pct") or 0) > 0)
    total_with_both = sum(1 for e in prior_events if e.get("eps_surprise_pct") is not None and e.get("price_change_pct") is not None)
    features["beat_up_rate"] = beat_up / max(total_with_both, 1)

    return features


def main():
    print("Fast XGBoost Training (DB only, no API calls)")
    print("=" * 50)

    sb = get_supabase()

    # Get all stocks with enough data
    stocks = sb.table("stocks").select("id, ticker").execute()
    print(f"Stocks in DB: {len(stocks.data)}")

    all_features = []
    y_beat = []
    y_direction = []
    y_magnitude = []

    for stock in stocks.data:
        # Get all earnings for this stock
        events = (
            sb.table("earnings_events")
            .select("report_date, eps_actual, eps_estimate, eps_surprise_pct, price_change_pct")
            .eq("stock_id", stock["id"])
            .order("report_date", desc=True)
            .limit(12)
            .execute()
        )

        earnings = events.data
        if len(earnings) < 3:
            continue

        # Build training samples from each event (using prior as features)
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
                y_direction.append(1 if event["eps_surprise_pct"] > 0 else 0)  # Proxy
                y_magnitude.append(event["eps_surprise_pct"] * 0.3)  # Rough proxy

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

    # Train beat model
    beat_model = xgb.XGBClassifier(
        n_estimators=300, max_depth=5, learning_rate=0.06,
        subsample=0.8, colsample_bytree=0.8,
        reg_alpha=0.3, reg_lambda=1.5, random_state=42, verbosity=0,
    )
    beat_model.fit(X_train, y_beat[train_idx],
                   eval_set=[(X_val, y_beat[val_idx])], verbose=False)

    # Train direction model
    direction_model = xgb.XGBClassifier(
        n_estimators=300, max_depth=5, learning_rate=0.06,
        subsample=0.8, colsample_bytree=0.8,
        reg_alpha=0.3, reg_lambda=1.5, random_state=42, verbosity=0,
    )
    direction_model.fit(X_train, y_direction[train_idx],
                        eval_set=[(X_val, y_direction[val_idx])], verbose=False)

    # Train magnitude model
    magnitude_model = xgb.XGBRegressor(
        n_estimators=300, max_depth=4, learning_rate=0.06,
        subsample=0.8, colsample_bytree=0.8,
        reg_alpha=0.3, reg_lambda=1.5, random_state=42, verbosity=0,
    )
    magnitude_model.fit(X_train, y_magnitude[train_idx],
                        eval_set=[(X_val, y_magnitude[val_idx])], verbose=False)

    # Evaluate
    beat_pred = beat_model.predict(X_val)
    beat_prob = beat_model.predict_proba(X_val)[:, 1]
    dir_pred = direction_model.predict(X_val)
    dir_prob = direction_model.predict_proba(X_val)[:, 1]
    mag_pred = magnitude_model.predict(X_val)

    print(f"\nResults (validation):")
    print(f"  Beat accuracy:      {accuracy_score(y_beat[val_idx], beat_pred):.1%}")
    print(f"  Beat AUC:           {roc_auc_score(y_beat[val_idx], beat_prob):.3f}")
    print(f"  Direction accuracy: {accuracy_score(y_direction[val_idx], dir_pred):.1%}")
    print(f"  Direction AUC:      {roc_auc_score(y_direction[val_idx], dir_prob):.3f}")
    print(f"  Move MAE:           {mean_absolute_error(y_magnitude[val_idx], mag_pred):.2f}%")

    # Feature importance
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
    print(f"\nModels saved to {model_dir}")


if __name__ == "__main__":
    main()
