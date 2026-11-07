"""
Verify Step 3.5 ETA Inference Engine: (a) reproduce Calibrated MAE on full Test set, (b) latency, (c) validation guards.
"""
import os
import sys
import time

import numpy as np
import pandas as pd

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, BASE_DIR)

from module_3_bus_eta_prediction.step_3_3_machine_learning_models.eta_model_trainer import GOLD_FEATURE_DIR
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.eta_inference_engine import EtaInferenceEngine

eng = EtaInferenceEngine()
test_root = os.path.join(GOLD_FEATURE_DIR, "split=test")
n = 0
sum_ae = 0.0
sum_ae_raw = 0.0
sample = None
t0 = time.perf_counter()
for d in sorted(os.listdir(test_root)):
    p = os.path.join(test_root, d, "part-00000.snappy.parquet")
    if not os.path.exists(p):
        continue
    df = pd.read_parquet(p)
    act = df["actual_eta_sec"].to_numpy(dtype=np.float64)
    sum_ae += np.abs(act - eng.predict(df)).sum()
    sum_ae_raw += np.abs(act - eng.predict(df, calibrate=False)).sum()
    n += len(df)
    if sample is None and len(df) >= 10000:
        sample = df.iloc[:10000].copy()
print(f"[a] Test rows via engine: {n:,} | MAE calibrated = {sum_ae / n:.4f}s (expected 95.76) | "
      f"MAE uncalibrated = {sum_ae_raw / n:.4f}s (expected 96.56) | {time.perf_counter() - t0:.1f}s")

one = sample.iloc[[0]]
eng.predict(one)
ts = []
for i in range(200):
    r = sample.iloc[[i]]
    t = time.perf_counter(); eng.predict(r); ts.append((time.perf_counter() - t) * 1000)
print(f"[b] Latency 1 row: median={np.median(ts):.2f} ms, p95={np.percentile(ts, 95):.2f} ms")
t = time.perf_counter(); eng.predict(sample); dt = time.perf_counter() - t
print(f"[b] Latency batch 10,000 rows: {dt * 1000:.1f} ms ({10000 / dt:,.0f} rows/s)")

bad = sample.iloc[[0]].copy(); bad.loc[bad.index[0], "ego_speed_roll5_kmh"] = np.nan
try:
    eng.predict(bad); print("[c] FAIL: NaN accepted")
except ValueError as e:
    print("[c] NaN rejected OK:", e)
bad2 = sample.iloc[[0]].drop(columns=["cos_time"])
try:
    eng.predict(bad2); print("[c] FAIL: missing column accepted")
except ValueError as e:
    print("[c] Missing column rejected OK:", e)
