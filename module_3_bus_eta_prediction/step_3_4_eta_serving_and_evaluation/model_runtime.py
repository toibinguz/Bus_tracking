"""
Step 3.4 — Runtime mô hình XGBoost (residual -> absolute) + calibrator Empirical-Bayes.
Module: module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/model_runtime.py

Canonical artifact (SPEC-16 §1.3.1):
  - Model : data/models/eta_xgb_global_full_54feat_r3_big.json (54 feature, 708 cây)
  - Meta  : data/models/eta_xgb_metadata_and_calibrator_r3_big.json (khóa "calibrator", 384 ô)
XGBoost dự báo RESIDUAL; serving dựng ETA = max(5.0, baseline_eta_p50_sec + delta) rồi áp calibrator.
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from config.system_config import DEFAULT_DB_PATH  # noqa: F401  (giữ import config để đồng bộ SSOT)

logger = logging.getLogger(__name__)

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
MODEL_PATH = os.path.join(BASE_DIR, "data", "models", "eta_xgb_global_full_54feat_r3_big.json")
METADATA_PATH = os.path.join(BASE_DIR, "data", "models", "eta_xgb_metadata_and_calibrator_r3_big.json")

CATEGORICAL_FEATURES = ["route_id_idx", "direction_id", "day_type", "hour_slot"]


def assign_horizon_bucket(n_stations_ahead: int) -> int:
    """Ánh xạ n_stations_ahead -> bucket 0:==1, 1:2..5, 2:6..15, 3:>15 (khớp eta_model_trainer)."""
    if n_stations_ahead <= 1:
        return 0
    if n_stations_ahead <= 5:
        return 1
    if n_stations_ahead <= 15:
        return 2
    return 3


class ModelRuntime:
    """Bọc XGBRegressor + calibrator; an toàn khi artifact thiếu/hỏng (available == False)."""

    def __init__(
        self,
        model: Any = None,
        calibrator: Optional[Dict[str, Tuple[float, float]]] = None,
        booster_feature_names: Optional[List[str]] = None,
    ):
        self._model = model
        self._calibrator: Dict[str, Tuple[float, float]] = calibrator or {}
        self._booster_feature_names = booster_feature_names

    @classmethod
    def load(cls, model_path: str = MODEL_PATH, metadata_path: str = METADATA_PATH) -> "ModelRuntime":
        """Nạp model + các ô calibrator; trả instance unavailable nếu lỗi (không ném ra ngoài)."""
        try:
            import xgboost as xgb

            model = xgb.XGBRegressor()
            model.load_model(model_path)
            booster_feature_names = list(model.get_booster().feature_names or [])

            calibrator: Dict[str, Tuple[float, float]] = {}
            if os.path.exists(metadata_path):
                with open(metadata_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                for k, v in meta.get("calibrator", {}).items():
                    if v is not None and len(v) == 2:
                        calibrator[str(k)] = (float(v[0]), float(v[1]))

            logger.info("Đã nạp model (%d feature) và %d ô calibrator", len(booster_feature_names), len(calibrator))
            return cls(model=model, calibrator=calibrator, booster_feature_names=booster_feature_names)
        except Exception as e:
            logger.error("Không nạp được model runtime (%s): %s", model_path, e)
            return cls(model=None, calibrator={}, booster_feature_names=None)

    @property
    def available(self) -> bool:
        """True khi model + danh sách feature_names sẵn sàng."""
        return self._model is not None and bool(self._booster_feature_names)

    def predict_p50(self, feature_row: Dict[str, float]) -> Optional[float]:
        """
        Dự báo ETA P50 tuyệt đối (đã calibrate). None nếu model unavailable/exception.
        = max(5.0, baseline_eta_p50_sec + delta), rồi áp calibrator theo (route_id_idx, direction_id, horizon).
        """
        if not self.available:
            return None
        try:
            X = pd.DataFrame([feature_row]).reindex(columns=self._booster_feature_names)
            for c in CATEGORICAL_FEATURES:
                if c in X.columns:
                    # int32 trước khi category để khớp index type của tập train (feature store cast int32).
                    X[c] = X[c].astype("int32").astype("category")
            delta = float(self._model.predict(X)[0])

            base = float(feature_row["baseline_eta_p50_sec"])
            eta = max(5.0, base + delta)

            r_idx = int(feature_row["route_id_idx"])
            d_idx = int(feature_row["direction_id"])
            h_bkt = assign_horizon_bucket(int(feature_row["n_stations_ahead"]))
            cal = self._calibrator.get(f"{r_idx}_{d_idx}_{h_bkt}")
            if cal is not None:
                scale_factor, bias_shift = cal
                eta = 0.5 * (eta * scale_factor) + 0.5 * (eta + bias_shift)
                eta = max(5.0, eta)
            return eta
        except Exception as e:
            logger.warning("Lỗi predict_p50, fallback baseline: %s", e)
            return None
