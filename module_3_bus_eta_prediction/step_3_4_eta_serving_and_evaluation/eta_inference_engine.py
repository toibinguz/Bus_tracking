"""
Module 3 - Step 3.5: ETA Inference Engine (Serving Vertical Slice).
Loads the trained XGBoost residual model + Empirical-Bayes calibrator and converts a 54-feature table into ETA seconds.
Spec: docs/06_ETA_INFERENCE_ENGINE_SPEC.md
"""

import json
import os
import sys
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import xgboost as xgb

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, BASE_DIR)

from module_3_bus_eta_prediction.step_3_3_machine_learning_models.eta_model_trainer import (
    apply_per_route_calibrator,
    predict_eta_with_residual_model,
)

MODEL_DIR = os.path.join(BASE_DIR, "data", "models")
DEFAULT_TAG = "_r3_big"
MIN_ETA_SEC = 5.0


class EtaInferenceEngine:
    """Batch/single-row ETA predictor (global XGBoost residual + per-route calibration)."""

    def __init__(self, tag: str = DEFAULT_TAG, model_dir: str = MODEL_DIR) -> None:
        model_path = os.path.join(model_dir, f"eta_xgb_global_full_54feat{tag}.json")
        meta_path = os.path.join(model_dir, f"eta_xgb_metadata_and_calibrator{tag}.json")
        self.model = xgb.XGBRegressor()
        self.model.load_model(model_path)
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        self.features: List[str] = list(meta["all_features"])
        self.calibrator: Dict[Tuple[int, int, int], Tuple[float, float]] = {}
        for k, v in meta["calibrator"].items():
            r, d, h = (int(x) for x in k.split("_"))
            self.calibrator[(r, d, h)] = (float(v[0]), float(v[1]))

    def validate(self, df: pd.DataFrame) -> None:
        """Raises ValueError on missing columns, NaN/inf values or n_stations_ahead < 1."""
        missing = [c for c in self.features if c not in df.columns]
        if missing:
            raise ValueError(f"Thiếu {len(missing)} cột đặc trưng: {missing[:5]}...")
        vals = df[self.features].to_numpy(dtype=np.float64)
        if not np.isfinite(vals).all():
            raise ValueError("Đặc trưng chứa NaN/inf")
        if (df["n_stations_ahead"].to_numpy() < 1).any():
            raise ValueError("n_stations_ahead phải >= 1")

    def predict(self, df: pd.DataFrame, calibrate: bool = True) -> np.ndarray:
        """Returns ETA seconds (float64) for each row."""
        self.validate(df)
        raw = predict_eta_with_residual_model(self.model, df, self.features)
        if not calibrate:
            return raw
        return np.maximum(MIN_ETA_SEC, apply_per_route_calibrator(df, raw, self.calibrator))
