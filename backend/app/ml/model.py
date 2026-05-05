"""XGBoost model for earnings prediction."""

import xgboost as xgb
import numpy as np
import pandas as pd
import joblib
from pathlib import Path
from datetime import datetime
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score, f1_score, roc_auc_score
)
from app.core.config import get_settings

settings = get_settings()


class EarningsPredictionModel:
    """
    Multi-output XGBoost model for earnings predictions.

    Predicts:
    1. Beat probability (binary: beat vs miss/meet)
    2. Price direction (binary: up vs down)
    3. Expected move magnitude (regression)
    """

    def __init__(self):
        self.beat_model = None
        self.direction_model = None
        self.magnitude_model = None
        self.explainer = None
        self.feature_names = None
        self.version = None

    def train(self, X: pd.DataFrame, y_beat: np.ndarray,
              y_direction: np.ndarray, y_magnitude: np.ndarray):
        """Train all sub-models."""
        self.feature_names = list(X.columns)
        self.version = f"v{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # Beat prediction model (classification)
        self.beat_model = xgb.XGBClassifier(
            n_estimators=300,
            max_depth=6,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            reg_alpha=0.1,
            reg_lambda=1.0,
            eval_metric="logloss",
            early_stopping_rounds=20,
            random_state=42,
        )

        # Direction prediction model (classification)
        self.direction_model = xgb.XGBClassifier(
            n_estimators=300,
            max_depth=6,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            reg_alpha=0.1,
            reg_lambda=1.0,
            eval_metric="logloss",
            early_stopping_rounds=20,
            random_state=42,
        )

        # Magnitude prediction model (regression)
        self.magnitude_model = xgb.XGBRegressor(
            n_estimators=300,
            max_depth=5,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            reg_alpha=0.1,
            reg_lambda=1.0,
            eval_metric="rmse",
            early_stopping_rounds=20,
            random_state=42,
        )

        # Time-series aware split for validation
        tscv = TimeSeriesSplit(n_splits=5)
        train_idx, val_idx = list(tscv.split(X))[-1]

        X_train, X_val = X.iloc[train_idx], X.iloc[val_idx]
        y_beat_train, y_beat_val = y_beat[train_idx], y_beat[val_idx]
        y_dir_train, y_dir_val = y_direction[train_idx], y_direction[val_idx]
        y_mag_train, y_mag_val = y_magnitude[train_idx], y_magnitude[val_idx]

        # Train models
        self.beat_model.fit(
            X_train, y_beat_train,
            eval_set=[(X_val, y_beat_val)],
            verbose=False,
        )
        self.direction_model.fit(
            X_train, y_dir_train,
            eval_set=[(X_val, y_dir_val)],
            verbose=False,
        )
        self.magnitude_model.fit(
            X_train, y_mag_train,
            eval_set=[(X_val, y_mag_val)],
            verbose=False,
        )

        # Build explainer using XGBoost built-in feature importance
        self.explainer = None  # Using built-in importance instead of SHAP

        return self._evaluate(X_val, y_beat_val, y_dir_val, y_mag_val)

    def predict(self, X: pd.DataFrame) -> dict:
        """Generate predictions with explanations."""
        beat_prob = self.beat_model.predict_proba(X)[0][1]
        direction_prob = self.direction_model.predict_proba(X)[0][1]
        expected_move = float(self.magnitude_model.predict(X)[0])

        # Generate explanation using XGBoost built-in feature importance
        feature_importance = self._get_top_features(X)
        explanation = self._generate_explanation(feature_importance, beat_prob, direction_prob)

        # Determine recommendation
        recommendation = self._get_recommendation(beat_prob, direction_prob, expected_move)

        # Confidence is based on how decisive the predictions are
        confidence = self._calculate_confidence(beat_prob, direction_prob, expected_move)

        return {
            "recommendation": recommendation,
            "confidence_score": confidence,
            "beat_probability": float(beat_prob),
            "miss_probability": float(1 - beat_prob),
            "price_up_probability": float(direction_prob),
            "price_down_probability": float(1 - direction_prob),
            "expected_move_pct": expected_move,
            "expected_volatility": abs(expected_move) * 1.5,
            "predicted_direction": "up" if direction_prob > 0.5 else "down",
            "feature_importance": feature_importance,
            "explanation_text": explanation,
            "model_version": self.version,
        }

    def _get_recommendation(self, beat_prob: float, direction_prob: float,
                            expected_move: float) -> str:
        """Determine buy/sell/avoid recommendation."""
        # Strong buy: high beat probability + positive direction + meaningful move
        if beat_prob > 0.65 and direction_prob > 0.6 and expected_move > 2.0:
            return "buy"
        # Strong sell: low beat probability + negative direction
        if beat_prob < 0.35 and direction_prob < 0.4 and expected_move < -2.0:
            return "sell"
        # Avoid: uncertain or mixed signals
        return "avoid"

    def _calculate_confidence(self, beat_prob: float, direction_prob: float,
                              expected_move: float) -> float:
        """Calculate confidence score (0-1)."""
        # Higher confidence when predictions are more decisive
        beat_decisiveness = abs(beat_prob - 0.5) * 2  # 0 at 50%, 1 at 0% or 100%
        dir_decisiveness = abs(direction_prob - 0.5) * 2
        move_magnitude = min(abs(expected_move) / 10.0, 1.0)

        confidence = (beat_decisiveness * 0.4 + dir_decisiveness * 0.4 + move_magnitude * 0.2)
        return round(min(max(confidence, 0.0), 1.0), 3)

    def _get_top_features(self, X: pd.DataFrame, top_n: int = 5) -> dict:
        """Get top features using XGBoost built-in feature importance."""
        importance = self.beat_model.feature_importances_
        feature_impacts = {}
        for i, col in enumerate(X.columns):
            feature_impacts[col] = float(importance[i])

        sorted_features = sorted(
            feature_impacts.items(), key=lambda x: abs(x[1]), reverse=True
        )
        return {k: round(v, 4) for k, v in sorted_features[:top_n]}

    def _generate_explanation(self, feature_importance: dict,
                              beat_prob: float, direction_prob: float) -> str:
        """Generate human-readable explanation."""
        lines = []
        if beat_prob > 0.6:
            lines.append(f"This stock has a {beat_prob:.0%} chance of beating earnings estimates.")
        elif beat_prob < 0.4:
            lines.append(f"This stock has a {1-beat_prob:.0%} chance of missing earnings estimates.")
        else:
            lines.append("Earnings outcome is uncertain for this stock.")

        lines.append("Key factors driving this prediction:")
        for feature, impact in list(feature_importance.items())[:3]:
            direction = "positive" if impact > 0 else "negative"
            readable_name = feature.replace("_", " ").title()
            lines.append(f"  • {readable_name}: {direction} impact ({impact:+.3f})")

        return "\n".join(lines)

    def _evaluate(self, X_val, y_beat_val, y_dir_val, y_mag_val) -> dict:
        """Evaluate model performance on validation set."""
        beat_pred = self.beat_model.predict(X_val)
        beat_prob = self.beat_model.predict_proba(X_val)[:, 1]
        dir_pred = self.direction_model.predict(X_val)
        mag_pred = self.magnitude_model.predict(X_val)

        return {
            "accuracy": accuracy_score(y_beat_val, beat_pred),
            "precision_beat": precision_score(y_beat_val, beat_pred, zero_division=0),
            "recall_beat": recall_score(y_beat_val, beat_pred, zero_division=0),
            "f1_score": f1_score(y_beat_val, beat_pred, zero_division=0),
            "auc_roc": roc_auc_score(y_beat_val, beat_prob) if len(set(y_beat_val)) > 1 else 0,
            "direction_accuracy": accuracy_score(y_dir_val, dir_pred),
            "mean_absolute_error_move": float(np.mean(np.abs(mag_pred - y_mag_val))),
        }

    def save(self, path: str = None):
        """Save model to disk."""
        if path is None:
            path = settings.model_path
        model_dir = Path(path)
        model_dir.mkdir(parents=True, exist_ok=True)

        joblib.dump(self.beat_model, model_dir / "beat_model.joblib")
        joblib.dump(self.direction_model, model_dir / "direction_model.joblib")
        joblib.dump(self.magnitude_model, model_dir / "magnitude_model.joblib")
        joblib.dump(self.feature_names, model_dir / "feature_names.joblib")
        joblib.dump(self.version, model_dir / "version.joblib")

    @classmethod
    def load(cls, path: str = None) -> "EarningsPredictionModel":
        """Load model from disk."""
        if path is None:
            path = settings.model_path
        model_dir = Path(path)

        model = cls()
        model.beat_model = joblib.load(model_dir / "beat_model.joblib")
        model.direction_model = joblib.load(model_dir / "direction_model.joblib")
        model.magnitude_model = joblib.load(model_dir / "magnitude_model.joblib")
        model.feature_names = joblib.load(model_dir / "feature_names.joblib")
        model.version = joblib.load(model_dir / "version.joblib")
        model.explainer = None

        return model
