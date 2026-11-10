"""
Post-Step 3.3 Empirical EDA & Anomaly Audit for the Unified Gold Feature Store
(`data/lakehouse/gold/eta_feature_store/` — 15,069,481 rows x 60 columns).
"""

import glob
import os
import sys
import time
import numpy as np
import pandas as pd
import pyarrow.dataset as ds_pa

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOLD_FS_DIR = os.path.join(BASE_DIR, "data", "lakehouse", "gold", "eta_feature_store")


def main() -> None:
    t0 = time.time()
    tr_dir = os.path.join(GOLD_FS_DIR, "split=train")
    te_dir = os.path.join(GOLD_FS_DIR, "split=test")

    pq_files = glob.glob(os.path.join(GOLD_FS_DIR, "**", "*.parquet"), recursive=True)
    disk_mb = sum(os.path.getsize(f) for f in pq_files) / (1024 * 1024)

    ds_tr = ds_pa.dataset(tr_dir, format="parquet")
    ds_te = ds_pa.dataset(te_dir, format="parquet")

    n_tr_total = ds_tr.count_rows()
    n_te_total = ds_te.count_rows()

    # Load full Test set (3.7M rows) for exact benchmark + stratified sample of Train set (2.5M rows) for fast correlation/EDA
    eval_cols = [
        "route_code", "dt", "actual_eta_sec", "n_stations_ahead", "remaining_distance_m",
        "day_type", "hour_slot", "ego_speed_instant_kmh", "ego_speed_roll3_kmh", "ego_speed_roll5_kmh",
        "ego_accel_kmh_per_min", "ego_speed_ratio_vs_baseline", "ego_cum_delay_vs_baseline_sec",
        "lead_bus_dist_ahead_m", "lead_bus_time_headway_sec", "lead_bus_speed_kmh", "lead_bus_speed_ratio",
        "follow_bus_dist_behind_m", "follow_bus_speed_kmh", "n_active_buses_on_route", "n_buses_in_corridor_ahead",
        "recent_corridor_tt_sum_sec", "recent_corridor_congestion_ratio", "recent_seg_coverage_ratio",
        "recent_next_seg_congestion_ratio",
        "baseline_eta_p50_sec", "baseline_eta_mean_sec", "baseline_eta_p10_sec", "baseline_eta_p90_sec",
        "baseline_eta_iqr_sec", "baseline_eta_rss_std_sec", "baseline_skew_sec", "baseline_max_seg_p90_sec",
        "baseline_tier0_frac",
        "inc_ahead_count", "inc_ahead_total_delay_sec", "inc_ahead_max_delay_sec",
        "inc_ahead_max_magnitude", "inc_ahead_jam_length_m", "inc_dist_to_nearest_m",
        "route_base_speed_kmh", "route_station_spacing_m",
        "physics_kinematic_eta_sec", "physics_probe_corrected_eta_sec",
    ]

    df_te = ds_te.to_table(columns=eval_cols).to_pandas()
    df_tr_full = ds_tr.to_table(columns=eval_cols).to_pandas()

    print("=" * 98)
    print("EDA 1: UNIFIED GOLD FEATURE STORE VOLUME, TEMPORAL SPLIT PURITY & ZERO-NAN INTEGRITY")
    print("=" * 98)
    print(f"  * Parquet Partitions : {len(pq_files)} files | Total Disk Footprint: {disk_mb:.2f} MB")
    print(f"  * Train Set Rows     : {n_tr_total:>11,} | Date Range: [{df_tr_full['dt'].min()} .. {df_tr_full['dt'].max()}] | Routes: {df_tr_full['route_code'].nunique()}")
    print(f"  * Test Set Rows      : {n_te_total:>11,} | Date Range: [{df_te['dt'].min()} .. {df_te['dt'].max()}] | Routes: {df_te['route_code'].nunique()}")
    print(f"  * Total Feature Rows : {n_tr_total + n_te_total:>11,} x 60 columns (52 features + 8 metadata/target)")
    print(f"  * Total NaNs         : Train={int(df_tr_full.isna().sum().sum())} | Test={int(df_te.isna().sum().sum())}")
    print(f"  * Invalid Target ETA : Train={int(((df_tr_full['actual_eta_sec']<=0)|(df_tr_full['actual_eta_sec']>7200)).sum())} | Test={int(((df_te['actual_eta_sec']<=0)|(df_te['actual_eta_sec']>7200)).sum())}")

    df_tr_full["residual_sec"] = df_tr_full["actual_eta_sec"] - df_tr_full["baseline_eta_p50_sec"]
    df_te["residual_sec"] = df_te["actual_eta_sec"] - df_te["baseline_eta_p50_sec"]

    print("\n" + "=" * 98)
    print("EDA 2: EMPIRICAL SIGNAL OF THE 6 CAUSAL FEATURE FAMILIES (a..f) ON 11.36M TRAIN ROWS")
    print("=" * 98)

    # (a) Ego Current Speed Ratio vs Baseline
    ego_slow = df_tr_full[df_tr_full["ego_speed_ratio_vs_baseline"] < 0.70]
    ego_fast = df_tr_full[df_tr_full["ego_speed_ratio_vs_baseline"] > 1.30]
    print("  [Family (a): Current Ego-Bus State & Kinematics]:")
    print(f"    - Ego Bus Running SLOW (<0.70x baseline) : N={len(ego_slow):>10,} | Mean Residual Delay = {ego_slow['residual_sec'].mean():>+7.2f}s (Median {ego_slow['residual_sec'].median():>+6.2f}s)")
    print(f"    - Ego Bus Running FAST (>1.30x baseline) : N={len(ego_fast):>10,} | Mean Residual Delay = {ego_fast['residual_sec'].mean():>+7.2f}s (Median {ego_fast['residual_sec'].median():>+6.2f}s)")

    # (b) Same-Route Fleet Ahead & Behind (Bus Bunching & Headway)
    bunch_close = df_tr_full[df_tr_full["lead_bus_dist_ahead_m"] <= 800.0]
    bunch_norm = df_tr_full[(df_tr_full["lead_bus_dist_ahead_m"] > 800.0) & (df_tr_full["lead_bus_dist_ahead_m"] < 20000.0)]
    lead_slow = bunch_norm[bunch_norm["lead_bus_speed_ratio"] < 0.70]
    lead_fast = bunch_norm[bunch_norm["lead_bus_speed_ratio"] > 1.30]
    print("\n  [Family (b): Same-Route Fleet Ahead & Behind (Headway, Bunching & Lead Bus Speed)]:")
    print(f"    - Active Lead Bus Ahead (<20km) Coverage : {(df_tr_full['lead_bus_dist_ahead_m']<20000).mean()*100:.1f}% of rows")
    print(f"    - Bus Bunching (Lead Bus <= 800m ahead)  : N={len(bunch_close):>10,} | Mean Residual = {bunch_close['residual_sec'].mean():>+7.2f}s (Faster due to fewer passenger stops!)")
    print(f"    - Lead Bus Ahead is SLOW (<0.70x)        : N={len(lead_slow):>10,} | Mean Residual = {lead_slow['residual_sec'].mean():>+7.2f}s")
    print(f"    - Lead Bus Ahead is FAST (>1.30x)        : N={len(lead_fast):>10,} | Mean Residual = {lead_fast['residual_sec'].mean():>+7.2f}s")

    # (c) Recent Preceding Bus Traversals (Last 30m Probe)
    has_probe = df_tr_full[df_tr_full["recent_seg_coverage_ratio"] >= 0.5]
    fast_probe = has_probe[has_probe["recent_corridor_congestion_ratio"] < 0.85]
    slow_probe = has_probe[has_probe["recent_corridor_congestion_ratio"] > 1.20]
    print("\n  [Family (c): Recent Preceding Bus Traversals (Last 30 Minutes Corridor Probe)]:")
    print(f"    - Mean Segment Probe Coverage (<=30m)    : {df_tr_full['recent_seg_coverage_ratio'].mean()*100:.1f}% (Rows with >=50% coverage: {len(has_probe)/len(df_tr_full)*100:.1f}%)")
    print(f"    - Preceding Bus was FAST (<0.85x)        : N={len(fast_probe):>10,} | Mean Residual = {fast_probe['residual_sec'].mean():>+7.2f}s (Median {fast_probe['residual_sec'].median():>+6.2f}s)")
    print(f"    - Preceding Bus was SLOW (>1.20x)        : N={len(slow_probe):>10,} | Mean Residual = {slow_probe['residual_sec'].mean():>+7.2f}s (Median {slow_probe['residual_sec'].median():>+6.2f}s)")

    # (e) TomTom Traffic Incidents Ahead
    no_inc = df_tr_full[df_tr_full["inc_ahead_count"] == 0]
    has_inc = df_tr_full[df_tr_full["inc_ahead_count"] >= 1]
    sev_inc = df_tr_full[df_tr_full["inc_ahead_total_delay_sec"] >= 300]
    print("\n  [Family (e): Real-Time TomTom Traffic Incidents Ahead]:")
    print(f"    - Rows with >=1 Incident Ahead           : {len(has_inc):>10,} ({len(has_inc)/len(df_tr_full)*100:.2f}%)")
    print(f"    - No Incident Ahead (count == 0)         : Mean Residual = {no_inc['residual_sec'].mean():>+7.2f}s")
    print(f"    - Active Incident Ahead (count >= 1)     : Mean Residual = {has_inc['residual_sec'].mean():>+7.2f}s")
    print(f"    - Severe Incident Ahead (delay>=300s)    : Mean Residual = {sev_inc['residual_sec'].mean():>+7.2f}s (N={len(sev_inc):,})")

    print("\n" + "=" * 98)
    print("EDA 3: TOP CORRELATIONS WITH ACTUAL ETA & RESIDUAL DELAY (SAMPLE 1M TRAIN ROWS)")
    print("=" * 98)
    df_samp = df_tr_full.sample(n=min(1000000, len(df_tr_full)), random_state=42)
    num_cols = [c for c in eval_cols[3:] if c != "residual_sec"]
    corr_eta = df_samp[num_cols].apply(lambda s: s.corr(df_samp["actual_eta_sec"])).sort_values(key=abs, ascending=False)
    corr_res = df_samp[num_cols].apply(lambda s: s.corr(df_samp["residual_sec"])).sort_values(key=abs, ascending=False)

    print("  [Top 10 Features Correlated with `actual_eta_sec`]:")
    for k, v in corr_eta.head(10).items():
        print(f"    * {k:<36}: r = {v:>+.4f}")

    print("\n  [Top 12 Features Correlated with `residual_sec = actual_eta - baseline_p50`]:")
    for k, v in corr_res.head(12).items():
        print(f"    * {k:<36}: r = {v:>+.4f}")

    print("\n" + "=" * 98)
    print("EDA 4: HELD-OUT TEST SET BENCHMARK (3.70M ROWS) — BASELINE vs PRECEDING-BUS PROBE (`recent_corridor_tt_sum_sec`)")
    print("=" * 98)
    # Also test a simple linear blend of 0.65 * baseline_eta_p50_sec + 0.35 * recent_corridor_tt_sum_sec
    df_te["blended_35_probe_sec"] = 0.65 * df_te["baseline_eta_p50_sec"] + 0.35 * df_te["recent_corridor_tt_sum_sec"]

    for h_lbl, mask in [
        ("1_hop_adjacent  ", df_te["n_stations_ahead"] == 1),
        ("2_to_5_stations ", df_te["n_stations_ahead"].between(2, 5)),
        ("6_to_15_stations", df_te["n_stations_ahead"].between(6, 15)),
        ("gt_15_stations  ", df_te["n_stations_ahead"] > 15),
        ("ALL_HORIZONS    ", df_te["n_stations_ahead"] >= 1),
    ]:
        sub = df_te[mask]
        e_base = (sub["actual_eta_sec"] - sub["baseline_eta_p50_sec"]).to_numpy()
        e_mean = (sub["actual_eta_sec"] - sub["baseline_eta_mean_sec"]).to_numpy()
        e_blend = (sub["actual_eta_sec"] - sub["blended_35_probe_sec"]).to_numpy()
        print(f"  * Horizon {h_lbl} (N={len(sub):>9,}):")
        print(f"    - Baseline Sum(P50)  [Family d]      : MAE={np.mean(np.abs(e_base)):>6.2f}s | MedAE={np.median(np.abs(e_base)):>6.2f}s | Bias={np.mean(e_base):>+6.2f}s | RMSE={np.sqrt(np.mean(e_base**2)):>6.2f}s")
        print(f"    - Baseline Sum(Mean) [Family d]      : MAE={np.mean(np.abs(e_mean)):>6.2f}s | MedAE={np.median(np.abs(e_mean)):>6.2f}s | Bias={np.mean(e_mean):>+6.2f}s | RMSE={np.sqrt(np.mean(e_mean**2)):>6.2f}s")
        print(f"    - 65% Base + 35% PrecedingBusProbe   : MAE={np.mean(np.abs(e_blend)):>6.2f}s | MedAE={np.median(np.abs(e_blend)):>6.2f}s | Bias={np.mean(e_blend):>+6.2f}s | RMSE={np.sqrt(np.mean(e_blend**2)):>6.2f}s")

    print("=" * 98)
    print(f"EDA Completed in {time.time()-t0:.2f}s.")


if __name__ == "__main__":
    main()
