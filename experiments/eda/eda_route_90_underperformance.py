"""
EDA Step 3.4 (TD-25): Why is Route 90 worse than Baseline? Breaks down Baseline-vs-XGB error on Route 90
by direction, day_type, horizon, and compares train-vs-test feature drift against a reference of all routes.
"""
import os
import sys

import numpy as np
import pandas as pd
import xgboost as xgb

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, BASE_DIR)
from module_3_bus_eta_prediction.step_3_3_machine_learning_models.eta_model_trainer import (
    ALL_54_FEATURES, GOLD_FEATURE_DIR, assign_horizon_bucket, predict_eta_with_residual_model,
)

model = xgb.XGBRegressor()
model.load_model(os.path.join(BASE_DIR, "data", "models", "eta_xgb_global_full_54feat.json"))

R = "90"
te = pd.read_parquet(os.path.join(GOLD_FEATURE_DIR, "split=test", f"route_code={R}", "part-00000.snappy.parquet"))
tr = pd.read_parquet(os.path.join(GOLD_FEATURE_DIR, "split=train", f"route_code={R}", "part-00000.snappy.parquet"))
te["pred"] = predict_eta_with_residual_model(model, te, ALL_54_FEATURES)
te["base"] = te["baseline_eta_p50_sec"].clip(lower=5)
te["ae_b"] = (te.actual_eta_sec - te.base).abs()
te["ae_x"] = (te.actual_eta_sec - te.pred).abs()
te["bias_b"] = te.actual_eta_sec - te.base
te["bias_x"] = te.actual_eta_sec - te.pred
te["h"] = assign_horizon_bucket(te.n_stations_ahead.to_numpy())

print(f"Route {R}: train rows={len(tr):,} test rows={len(te):,}; train days={tr.dt.nunique()} test days={te.dt.nunique()}")
for key in ["direction", "day_type", "h", "dt"]:
    g = te.groupby(key).agg(n=("ae_b", "size"), mae_base=("ae_b", "mean"), mae_xgb=("ae_x", "mean"),
                            bias_base=("bias_b", "mean"), bias_xgb=("bias_x", "mean")).round(2)
    print(f"\n--- by {key} ---\n{g.to_string()}")

feats = ["baseline_eta_p50_sec", "baseline_tier0_frac", "recent_corridor_congestion_ratio", "inc_ahead_total_delay_sec",
         "ego_speed_roll5_kmh", "ego_cum_delay_vs_baseline_sec", "route_base_speed_kmh"]
print("\n--- feature drift train vs test (route 90) ---")
print(pd.DataFrame({"train_mean": tr[feats].mean(), "test_mean": te[feats].mean()}).round(3).to_string())
print("\ntarget/baseline ratio train:", round((tr.actual_eta_sec / tr.baseline_eta_p50_sec.clip(lower=5)).median(), 3),
      "test:", round((te.actual_eta_sec / te.base).median(), 3))
