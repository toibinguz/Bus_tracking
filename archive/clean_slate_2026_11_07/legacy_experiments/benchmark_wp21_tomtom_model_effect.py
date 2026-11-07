"""
Experiment: benchmark_wp21_tomtom_model_effect.py
Purpose: WP 2.1.4 - Evaluate the empirical effect of fusing 3 TomTom incident features
         into the XGB-CQR Point and Interval ETA Model on Golden Demo Route 02.
Compares:
  - Model A: 24 Canonical Features (Without TomTom)
  - Model B: 27 Features (With 3 TomTom Incident Features: has_inc, delay_sec, magnitude)
Evaluates:
  - Point Accuracy: MAE, MdAE, RMSE, Hit@60s, Hit@90s
  - Interval Quality: PICP [80% Nominal], MPIW (Width), Winkler Score, Pinball Loss
  - Incident-Specific Slice: Performance specifically during active congestion episodes
"""
import sys
import os

# Add workspace root to sys.path
sys.path.insert(0, os.path.abspath("."))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.stdout.reconfigure(encoding='utf-8')

import sqlite3
import bisect
import time
import math
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import mean_pinball_loss
DB_PATH = "data/hanoi_bus_system.db"

# Import feature extractor baseline
from module_3_bus_eta_prediction.step_3_2_feature_store_extractor.feature_extractor import (
    extract_route_training_dataset,
    FEATURE_COLUMNS,
    TARGET_COLUMN
)
from module_3_bus_eta_prediction.step_3_3_machine_learning_models.train_eta_model import (
    compute_interval_metrics
)

TOMTOM_FEATURES = ["tomtom_has_incident", "tomtom_delay_sec", "tomtom_magnitude"]
EXTENDED_FEATURES = FEATURE_COLUMNS + TOMTOM_FEATURES

def augment_dataset_with_tomtom(df: pd.DataFrame, route_code: str, conn: sqlite3.Connection) -> pd.DataFrame:
    """
    Augments dataframe with 3 TomTom incident features causally evaluated at t_ping.
    """
    t0 = time.time()
    cur = conn.cursor()
    cur.execute("""
        SELECT direction, from_station_order, to_station_order, t_start_epoch, t_end_epoch, delay_seconds, magnitude_of_delay
        FROM fact_route_tomtom_incidents
        WHERE route_code = ?
    """, (route_code,))
    rows = cur.fetchall()
    
    # Map (direction, station_order) -> sorted list of (t_start, t_end, delay, mag)
    inc_index = {}
    for r in rows:
        direction, from_stn, to_stn, t_start, t_end, delay, mag = r
        key = (direction, from_stn)
        if key not in inc_index:
            inc_index[key] = []
        inc_index[key].append((t_start, t_end, delay or 0, mag or 0))
        
    for k in inc_index:
        inc_index[k].sort(key=lambda x: x[0])
        
    print(f"Loaded and indexed {len(rows):,} TomTom incident segments for Route {route_code} in {time.time()-t0:.2f}s.")
    
    # We need t_ping for each sample. 
    # Notice: df has ping_id, direction, target_station_order, stops_ahead.
    # Let's get device_epoch for ping_ids from route_projected_telemetry
    cur.execute("""
        SELECT ping_id, device_epoch
        FROM route_projected_telemetry
        WHERE route_code = ?
    """, (route_code,))
    epoch_map = dict(cur.fetchall())
    
    has_inc_list = []
    delay_sec_list = []
    mag_list = []
    
    # Iterate through dataframe rows
    for idx, row in df.iterrows():
        p_id = row["ping_id"]
        t_ping = epoch_map.get(p_id)
        if t_ping is None:
            has_inc_list.append(0)
            delay_sec_list.append(0.0)
            mag_list.append(0)
            continue
            
        direction = row["direction"]
        target_stn = int(row["target_station_order"])
        stops_ahead = int(row["stops_ahead"])
        # The segments ahead: from current stop (target_stn - stops_ahead) to target_stn
        start_stn = max(0, target_stn - stops_ahead)
        
        has_inc = 0
        max_delay = 0.0
        max_mag = 0
        
        for stn_order in range(start_stn, target_stn):
            key = (direction, stn_order)
            windows = inc_index.get(key)
            if not windows:
                continue
            # Binary search
            idx_w = bisect.bisect_left(windows, (t_ping, -1, 0, 0))
            for check_i in [idx_w - 1, idx_w]:
                if 0 <= check_i < len(windows):
                    w_start, w_end, w_delay, w_mag = windows[check_i]
                    if w_start <= t_ping <= w_end:
                        has_inc = 1
                        if w_delay > max_delay:
                            max_delay = float(w_delay)
                        if w_mag > max_mag:
                            max_mag = int(w_mag)
                            
        has_inc_list.append(has_inc)
        delay_sec_list.append(max_delay)
        mag_list.append(max_mag)
        
    df_out = df.copy()
    df_out["tomtom_has_incident"] = has_inc_list
    df_out["tomtom_delay_sec"] = delay_sec_list
    df_out["tomtom_magnitude"] = mag_list
    
    inc_pct = sum(has_inc_list) / len(has_inc_list) * 100.0
    print(f"Augmentation complete: {len(df_out):,} samples ({inc_pct:.2f}% with active incident).")
    return df_out

def run_benchmark():
    route_code = "02"
    conn = sqlite3.connect(DB_PATH)
    
    print("=" * 80)
    print(f"WP 2.1.4: TOMTOM FUSION MODEL BENCHMARK ON ROUTE {route_code}")
    print("=" * 80)
    
    # 1. Extract base dataset
    t0 = time.time()
    df_base = extract_route_training_dataset(route_code, db_path=DB_PATH)
    print(f"Extracted base dataset for Route {route_code}: {len(df_base):,} samples in {time.time()-t0:.2f}s.")
    
    # 2. Augment with TomTom features
    df = augment_dataset_with_tomtom(df_base, route_code, conn)
    conn.close()
    
    # 3. Trip-based temporal holdout split (80% train / 20% test)
    trips = df["trip_id"].drop_duplicates().tolist()
    n_trips = len(trips)
    split_idx = int(n_trips * 0.80)
    train_trips = set(trips[:split_idx])
    test_trips = set(trips[split_idx:])
    
    train_mask = df["trip_id"].isin(train_trips)
    test_mask = df["trip_id"].isin(test_trips)
    
    train_df = df[train_mask]
    test_df = df[test_mask]
    
    y_train = train_df[TARGET_COLUMN].values
    y_test = test_df[TARGET_COLUMN].values
    
    print(f"Train set: {len(train_df):,} samples ({len(train_trips):,} trips)")
    print(f"Test set:  {len(test_df):,} samples ({len(test_trips):,} trips)")
    
    # =========================================================================
    # MODEL A: 24 Features (Without TomTom)
    # =========================================================================
    print("\n--- Training Model A: 24 Canonical Features (WITHOUT TomTom) ---")
    X_train_A = train_df[FEATURE_COLUMNS]
    X_test_A = test_df[FEATURE_COLUMNS]
    
    # Train P50, P10, P90
    reg_med_A = xgb.XGBRegressor(
        n_estimators=100, max_depth=6, learning_rate=0.08, subsample=0.8, colsample_bytree=0.8,
        tree_method="hist", n_jobs=-1, random_state=42, objective="reg:absoluteerror"
    )
    reg_med_A.fit(X_train_A, y_train)
    y_pred_med_A = reg_med_A.predict(X_test_A)
    
    reg_low_A = xgb.XGBRegressor(
        n_estimators=80, max_depth=6, learning_rate=0.08, subsample=0.8, colsample_bytree=0.8,
        tree_method="hist", n_jobs=-1, random_state=42, objective="reg:quantileerror", quantile_alpha=0.10
    )
    reg_low_A.fit(X_train_A, y_train)
    y_pred_low_A = reg_low_A.predict(X_test_A)
    
    reg_high_A = xgb.XGBRegressor(
        n_estimators=80, max_depth=6, learning_rate=0.08, subsample=0.8, colsample_bytree=0.8,
        tree_method="hist", n_jobs=-1, random_state=42, objective="reg:quantileerror", quantile_alpha=0.90
    )
    reg_high_A.fit(X_train_A, y_train)
    y_pred_high_A = reg_high_A.predict(X_test_A)
    
    metrics_A = compute_interval_metrics(y_test, y_pred_low_A, y_pred_med_A, y_pred_high_A, alpha=0.20)
    
    # =========================================================================
    # MODEL B: 27 Features (WITH 3 TomTom Features)
    # =========================================================================
    print("\n--- Training Model B: 27 Features (WITH 3 TomTom Features) ---")
    X_train_B = train_df[EXTENDED_FEATURES]
    X_test_B = test_df[EXTENDED_FEATURES]
    
    reg_med_B = xgb.XGBRegressor(
        n_estimators=100, max_depth=6, learning_rate=0.08, subsample=0.8, colsample_bytree=0.8,
        tree_method="hist", n_jobs=-1, random_state=42, objective="reg:absoluteerror"
    )
    reg_med_B.fit(X_train_B, y_train)
    y_pred_med_B = reg_med_B.predict(X_test_B)
    
    reg_low_B = xgb.XGBRegressor(
        n_estimators=80, max_depth=6, learning_rate=0.08, subsample=0.8, colsample_bytree=0.8,
        tree_method="hist", n_jobs=-1, random_state=42, objective="reg:quantileerror", quantile_alpha=0.10
    )
    reg_low_B.fit(X_train_B, y_train)
    y_pred_low_B = reg_low_B.predict(X_test_B)
    
    reg_high_B = xgb.XGBRegressor(
        n_estimators=80, max_depth=6, learning_rate=0.08, subsample=0.8, colsample_bytree=0.8,
        tree_method="hist", n_jobs=-1, random_state=42, objective="reg:quantileerror", quantile_alpha=0.90
    )
    reg_high_B.fit(X_train_B, y_train)
    y_pred_high_B = reg_high_B.predict(X_test_B)
    
    metrics_B = compute_interval_metrics(y_test, y_pred_low_B, y_pred_med_B, y_pred_high_B, alpha=0.20)
    
    # Feature importances for Model B
    importances = reg_high_B.feature_importances_
    feat_imp = sorted(zip(EXTENDED_FEATURES, importances), key=lambda x: x[1], reverse=True)
    
    # =========================================================================
    # SLICE EVALUATION: Sub-population during Active TomTom Incident
    # =========================================================================
    inc_mask_test = test_df["tomtom_has_incident"].values == 1
    n_inc_test = np.sum(inc_mask_test)
    
    metrics_A_inc = compute_interval_metrics(
        y_test[inc_mask_test], y_pred_low_A[inc_mask_test], y_pred_med_A[inc_mask_test], y_pred_high_A[inc_mask_test], alpha=0.20
    )
    metrics_B_inc = compute_interval_metrics(
        y_test[inc_mask_test], y_pred_low_B[inc_mask_test], y_pred_med_B[inc_mask_test], y_pred_high_B[inc_mask_test], alpha=0.20
    )
    
    # Print Comparative Report
    print("\n" + "=" * 90)
    print("EMPIRICAL COMPARISON: MODEL A (WITHOUT TOMTOM) VS MODEL B (WITH TOMTOM)")
    print("=" * 90)
    print(f"{'Metric':<30} | {'Model A (Base 24)':<18} | {'Model B (TomTom 27)':<18} | {'Delta / Improvement'}")
    print("-" * 90)
    print(f"{'Overall Test MAE (Point P50)':<30} | {metrics_A['mae_sec']:>14.2f}s | {metrics_B['mae_sec']:>14.2f}s | {metrics_B['mae_sec'] - metrics_A['mae_sec']:>+14.2f}s")
    print(f"{'Overall Test MdAE':<30} | {metrics_A['mdae_sec']:>14.2f}s | {metrics_B['mdae_sec']:>14.2f}s | {metrics_B['mdae_sec'] - metrics_A['mdae_sec']:>+14.2f}s")
    print(f"{'Overall Test RMSE':<30} | {metrics_A['rmse_sec']:>14.2f}s | {metrics_B['rmse_sec']:>14.2f}s | {metrics_B['rmse_sec'] - metrics_A['rmse_sec']:>+14.2f}s")
    print(f"{'Overall Hit Rate @ 60s':<30} | {metrics_A['hit_60s_pct']:>13.1f}% | {metrics_B['hit_60s_pct']:>13.1f}% | {metrics_B['hit_60s_pct'] - metrics_A['hit_60s_pct']:>+13.1f}%")
    print(f"{'Interval Coverage (PICP 80%)':<30} | {metrics_A['picp_coverage_pct']:>13.1f}% | {metrics_B['picp_coverage_pct']:>13.1f}% | {metrics_B['picp_coverage_pct'] - metrics_A['picp_coverage_pct']:>+13.1f}%")
    print(f"{'Mean Interval Width (MPIW)':<30} | {metrics_A['mpiw_width_sec']:>14.2f}s | {metrics_B['mpiw_width_sec']:>14.2f}s | {metrics_B['mpiw_width_sec'] - metrics_A['mpiw_width_sec']:>+14.2f}s")
    print(f"{'Winkler Interval Score':<30} | {metrics_A['winkler_score_sec']:>14.2f}s | {metrics_B['winkler_score_sec']:>14.2f}s | {metrics_B['winkler_score_sec'] - metrics_A['winkler_score_sec']:>+14.2f}s")
    print("-" * 90)
    print("CONGESTION SLICE EVALUATION (During Active TomTom Incident - {} samples):".format(n_inc_test))
    print(f"{'  Incident Slice MAE':<30} | {metrics_A_inc['mae_sec']:>14.2f}s | {metrics_B_inc['mae_sec']:>14.2f}s | {metrics_B_inc['mae_sec'] - metrics_A_inc['mae_sec']:>+14.2f}s")
    print(f"{'  Incident Slice PICP (80%)':<30} | {metrics_A_inc['picp_coverage_pct']:>13.1f}% | {metrics_B_inc['picp_coverage_pct']:>13.1f}% | {metrics_B_inc['picp_coverage_pct'] - metrics_A_inc['picp_coverage_pct']:>+13.1f}%")
    print(f"{'  Incident Slice MPIW (Width)':<30} | {metrics_A_inc['mpiw_width_sec']:>14.2f}s | {metrics_B_inc['mpiw_width_sec']:>14.2f}s | {metrics_B_inc['mpiw_width_sec'] - metrics_A_inc['mpiw_width_sec']:>+14.2f}s")
    print(f"{'  Incident Slice Winkler':<30} | {metrics_A_inc['winkler_score_sec']:>14.2f}s | {metrics_B_inc['winkler_score_sec']:>14.2f}s | {metrics_B_inc['winkler_score_sec'] - metrics_A_inc['winkler_score_sec']:>+14.2f}s")
    print("=" * 90)
    
    print("\nTop 10 Feature Importances in Model B (P90 Upper Quantile):")
    for feat, imp in feat_imp[:10]:
        print(f"  {feat:<30}: {imp*100:>5.2f}%")
    print("\nTomTom Feature Ranks:")
    for feat, imp in feat_imp:
        if feat in TOMTOM_FEATURES:
            print(f"  {feat:<30}: {imp*100:>5.2f}%")

if __name__ == "__main__":
    run_benchmark()
