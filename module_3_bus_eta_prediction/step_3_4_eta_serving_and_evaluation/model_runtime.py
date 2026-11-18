"""
Step 3.4 — Runtime mô hình XGBoost causal-eta.v1 (36 feature, residual -> absolute).
Module: module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/model_runtime.py

Canonical artifact:
  - Bundle: data/models/causal_eta_v1/ (model.json + manifest.json, max_depth=6, 592/600 cây)
XGBoost dự báo RESIDUAL; serving dựng ETA = max(5.0, baseline_eta_p50_sec + delta).
"""

import hashlib
import logging
import os
from typing import Any, Dict, Optional

from config.system_config import DEFAULT_DB_PATH  # noqa: F401  (giữ import config để đồng bộ SSOT)
from module_3_bus_eta_prediction.step_3_2_feature_store_extractor.causal_eta import FEATURES
from module_3_bus_eta_prediction.step_3_3_machine_learning_models.causal_eta_training import ResidualETA

logger = logging.getLogger(__name__)

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CAUSAL_MODEL_DIR = os.path.join(BASE_DIR, "data", "models", "causal_eta_v1")


def assign_horizon_bucket(n_stations_ahead: int) -> int:
    """Ánh xạ n_stations_ahead -> bucket 0:==1, 1:2..5, 2:6..15, 3:>15."""
    if n_stations_ahead <= 1:
        return 0
    if n_stations_ahead <= 5:
        return 1
    if n_stations_ahead <= 15:
        return 2
    return 3


class ModelRuntime:
    """Bọc ResidualETA (causal-eta.v1); an toàn khi artifact thiếu/hỏng (available == False)."""

    def __init__(self, residual_eta: Optional[ResidualETA] = None):
        self._residual_eta = residual_eta
        self._known_routes = (
            set(residual_eta.domains.get("route_id_idx", [])) if residual_eta is not None else set()
        )
        self.identity: Dict[str, Any] = {}

    @classmethod
    def load(cls, model_dir: str = CAUSAL_MODEL_DIR) -> "ModelRuntime":
        """Nạp bundle causal-eta.v1; trả instance unavailable nếu lỗi (không ném ra ngoài)."""
        try:
            residual = ResidualETA.load(model_dir)
            model_path = os.path.join(model_dir, "model.json")
            manifest_path = os.path.join(model_dir, "manifest.json")

            def _sha256(path: str) -> str:
                with open(path, "rb") as stream:
                    return hashlib.file_digest(stream, "sha256").hexdigest()

            runtime = cls(residual_eta=residual)
            runtime.identity = {
                "schema": "causal-eta.v1",
                "model_sha256": _sha256(model_path),
                "metadata_sha256": _sha256(manifest_path) if os.path.exists(manifest_path) else None,
                "best_iteration": residual.best_iteration,
                "features": list(FEATURES),
            }
            logger.info(
                "Đã nạp causal-eta.v1 (%d feature, best_iteration=%s, %d tuyến)",
                len(FEATURES),
                residual.best_iteration,
                len(runtime._known_routes),
            )
            return runtime
        except Exception as e:
            logger.error("Không nạp được causal-eta runtime (%s): %s", model_dir, e)
            return cls(residual_eta=None)

    @property
    def available(self) -> bool:
        """True khi bundle causal-eta.v1 sẵn sàng."""
        return self._residual_eta is not None

    def predict_p50(self, feature_row: Optional[Dict[str, Any]]) -> Optional[float]:
        """Dự báo ETA P50 tuyệt đối; trả None để fallback baseline nếu thiếu feature hoặc tuyến ngoài tập train."""
        if not self.available or not feature_row:
            return None
        r_idx = feature_row.get("route_id_idx")
        if r_idx is None or int(r_idx) not in self._known_routes:
            return None
        try:
            eta = float(self._residual_eta.predict([feature_row], allow_unknown_routes=False)[0])
            base = float(feature_row["baseline_eta_p50_sec"])
            from .request_trace import record

            record(
                "model_prediction",
                features=feature_row,
                delta=eta - base,
                calibrator=None,
                prediction_seconds=eta,
                model=self.identity,
            )
            return eta
        except Exception as e:
            logger.warning("Lỗi predict_p50, fallback baseline: %s", e)
            return None
