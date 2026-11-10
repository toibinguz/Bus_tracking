"""
Diagnostic EDA for Step 3.4: Check daily row counts in `split=train` and `split=test`
to verify temporal validation split coverage and route-level residual behavior.
"""

import os
import sys
import pandas as pd
import pyarrow.dataset as ds_pa

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, BASE_DIR)

train_dir = os.path.join(BASE_DIR, "data", "lakehouse", "gold", "eta_feature_store", "split=train")
test_dir = os.path.join(BASE_DIR, "data", "lakehouse", "gold", "eta_feature_store", "split=test")

ds_tr = ds_pa.dataset(train_dir, format="parquet")
df_tr_dt = ds_tr.to_table(columns=["dt", "day_type"]).to_pandas()
print("=== TRAIN SPLIT ROW COUNTS BY DATE (dt) ===")
print(df_tr_dt.groupby(["dt", "day_type"]).size().to_string())

ds_te = ds_pa.dataset(test_dir, format="parquet")
df_te_dt = ds_te.to_table(columns=["dt", "day_type"]).to_pandas()
print("\n=== TEST SPLIT ROW COUNTS BY DATE (dt) ===")
print(df_te_dt.groupby(["dt", "day_type"]).size().to_string())
