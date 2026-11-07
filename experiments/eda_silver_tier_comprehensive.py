"""
Comprehensive Exploratory Data Analysis (EDA) of the Pure Silver Lakehouse Tier
Analyzes:
1. Spatio-Temporal Coverage, Route Volume & Train/Test Split Balance
2. Geometric Projection Fidelity (Cross-Track d_perp & Terminal Staging s_bus_m)
3. Heartbeat Jitter (delta_t) & Derived Kinematics (derived_speed_kmh by Hour)
4. Macroscopic Trip Segmentation Statistics
5. Silver TomTom Incident Fusion Distribution (fact_route_tomtom_incidents)
"""

import os
import sys
import time
import sqlite3
import numpy as np
import pandas as pd
import pyarrow.dataset as ds

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

DB_PATH = "data/hanoi_bus_system.db"
SILVER_TEL_DIR = "data/lakehouse/silver/route_projected_telemetry"


def run_silver_eda():
    t0 = time.time()
    print("=" * 88)
    print("COMPREHENSIVE EMPIRICAL EDA OF THE SILVER LAKEHOUSE TIER (PRE-MODULE 3)")
    print("=" * 88)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # 1. OVERALL VOLUME & TRAIN/TEST SPLIT
    print("\n[1] SPATIO-TEMPORAL COVERAGE & TRAIN/TEST SPLIT")
    dataset = ds.dataset(SILVER_TEL_DIR, format="parquet", partitioning="hive")
    df = dataset.to_table(
        columns=[
            "route_code",
            "dt",
            "vehicle_id",
            "device_epoch",
            "direction",
            "s_bus_m",
            "cross_track_m",
            "derived_speed_kmh",
        ]
    ).to_pandas()

    total_rows = len(df)
    n_routes = df["route_code"].nunique()
    n_vehicles = df["vehicle_id"].nunique()
    n_dates = df["dt"].nunique()
    train_mask = df["dt"] <= "2026-11-01"
    n_train = int(train_mask.sum())
    n_test = int((~train_mask).sum())

    print(f"  * Total Clean Silver Rows      : {total_rows:,} rows across {len(dataset.files):,} Parquet partitions")
    print(f"  * Active Projected Routes      : {n_routes} routes (out of 176 canonical master routes)")
    print(f"  * Unique Active Bus Vehicles   : {n_vehicles:,} vehicles")
    print(f"  * Active Calendar Dates        : {n_dates} days ({df['dt'].min()} -> {df['dt'].max()})")
    print(f"  * Train Split (<= 2026-11-01)  : {n_train:,} rows ({n_train/total_rows*100:.2f}%) across {df.loc[train_mask, 'dt'].nunique()} days")
    print(f"  * Test Split  (>= 2026-11-02)  : {n_test:,} rows ({n_test/total_rows*100:.2f}%) across {df.loc[~train_mask, 'dt'].nunique()} days")

    # Daily volume summary
    daily_counts = df.groupby("dt").size()
    print(f"  * Daily Ping Volume            : Median={int(daily_counts.median()):,}/day | Max={int(daily_counts.max()):,} ({daily_counts.idxmax()}) | Min={int(daily_counts.min()):,} ({daily_counts.idxmin()})")

    # Route volume distribution
    route_stats = df.groupby("route_code").agg(
        pings=("device_epoch", "count"),
        vehicles=("vehicle_id", "nunique"),
        days=("dt", "nunique"),
        avg_dperp=("cross_track_m", "mean"),
    ).sort_values("pings", ascending=False)

    print("\n  --- Top 5 Highest-Volume Routes ---")
    for rcode, row in route_stats.head(5).iterrows():
        print(f"    Route {rcode:<6}: {int(row['pings']):>7,} pings | {int(row['vehicles']):>3} vehicles | {int(row['days']):>2} days | avg d_perp={row['avg_dperp']:.2f}m")

    print("  --- Bottom 5 Lowest-Volume Routes ---")
    for rcode, row in route_stats.tail(5).iterrows():
        print(f"    Route {rcode:<6}: {int(row['pings']):>7,} pings | {int(row['vehicles']):>3} vehicles | {int(row['days']):>2} days | avg d_perp={row['avg_dperp']:.2f}m")

    # 2. GEOMETRIC FIDELITY & TERMINAL STAGING
    print("\n[2] GEOMETRIC PROJECTION FIDELITY & TERMINAL STAGING ANALYSIS")
    dperp_q = np.percentile(df["cross_track_m"], [10, 25, 50, 75, 90, 95, 99])
    print(f"  * Cross-Track Error (d_perp)   : Mean={df['cross_track_m'].mean():.2f}m | Std={df['cross_track_m'].std():.2f}m")
    print(f"    Percentiles: P10={dperp_q[0]:.1f}m | P25={dperp_q[1]:.1f}m | P50={dperp_q[2]:.1f}m | P75={dperp_q[3]:.1f}m | P90={dperp_q[4]:.1f}m | P95={dperp_q[5]:.1f}m | P99={dperp_q[6]:.1f}m")

    # Route max length lookup from canonical_shape_master
    shape_max = pd.read_sql_query(
        "SELECT route_code, direction, MAX(cum_distance_m) AS route_len_m FROM canonical_shape_master GROUP BY route_code, direction",
        conn,
    )
    df = df.merge(shape_max, on=["route_code", "direction"], how="left")
    near_start = (df["s_bus_m"] <= 100.0).sum()
    near_end = (df["s_bus_m"] >= (df["route_len_m"] - 100.0)).sum()
    mid_corridor = total_rows - near_start - near_end
    print(f"  * Longitudinal Position (s_bus):")
    print(f"    - Terminal Origin (s <= 100m)       : {near_start:,} pings ({near_start/total_rows*100:.2f}%) -> Terminal staging / waiting zone")
    print(f"    - Active Mid-Corridor               : {mid_corridor:,} pings ({mid_corridor/total_rows*100:.2f}%)")
    print(f"    - Terminal Destination (s >= L-100m): {near_end:,} pings ({near_end/total_rows*100:.2f}%)")

    # 3. HEARTBEAT JITTER (DELTA_T) & DERIVED KINEMATICS
    print("\n[3] HEARTBEAT JITTER (DELTA_T) & DERIVED KINEMATICS (V_DERIVED)")
    df_sorted = df.sort_values(["route_code", "vehicle_id", "direction", "device_epoch"])
    same_veh = (
        (df_sorted["route_code"] == df_sorted["route_code"].shift(1))
        & (df_sorted["vehicle_id"] == df_sorted["vehicle_id"].shift(1))
        & (df_sorted["direction"] == df_sorted["direction"].shift(1))
    )
    dt_series = (df_sorted["device_epoch"] - df_sorted["device_epoch"].shift(1))[same_veh]
    valid_dt = dt_series[(dt_series > 0) & (dt_series <= 300)]

    dt_q = np.percentile(valid_dt, [10, 25, 50, 75, 90, 95, 99])
    print(f"  * Intra-Trip Ping Interval dt (0 < dt <= 300s, N={len(valid_dt):,}):")
    print(f"    Percentiles: P10={dt_q[0]:.1f}s | P25={dt_q[1]:.1f}s | P50={dt_q[2]:.1f}s | P75={dt_q[3]:.1f}s | P90={dt_q[4]:.1f}s | P95={dt_q[5]:.1f}s | P99={dt_q[6]:.1f}s")
    b1 = (valid_dt <= 15).mean() * 100
    b2 = ((valid_dt > 15) & (valid_dt <= 35)).mean() * 100
    b3 = ((valid_dt > 35) & (valid_dt <= 65)).mean() * 100
    b4 = ((valid_dt > 65) & (valid_dt <= 120)).mean() * 100
    b5 = (valid_dt > 120).mean() * 100
    print(f"    Buckets    : <=15s: {b1:.1f}% | 15-35s: {b2:.1f}% | 35-65s: {b3:.1f}% | 65-120s: {b4:.1f}% | 120-300s: {b5:.1f}%")

    spd = df["derived_speed_kmh"]
    n_null_spd = int(spd.isna().sum())
    spd_valid = spd.dropna()
    n_zero_spd = int((spd_valid == 0).sum())
    n_crawl = int(((spd_valid > 0) & (spd_valid <= 5)).sum())
    n_slow = int(((spd_valid > 5) & (spd_valid <= 15)).sum())
    n_norm = int(((spd_valid > 15) & (spd_valid <= 35)).sum())
    n_fast = int(((spd_valid > 35) & (spd_valid <= 60)).sum())
    n_high = int((spd_valid > 60).sum())

    moving_spd = spd_valid[spd_valid > 0]
    spd_q = np.percentile(moving_spd, [10, 25, 50, 75, 90, 95])
    print(f"\n  * Derived Speed Distribution (v = delta_s / delta_t):")
    print(f"    - Trip Start / Unchained (NULL)     : {n_null_spd:>9,} ({n_null_spd/total_rows*100:.2f}%)")
    print(f"    - Stationary (v == 0 km/h)          : {n_zero_spd:>9,} ({n_zero_spd/total_rows*100:.2f}%)")
    print(f"    - Crawling   (0 < v <= 5 km/h)      : {n_crawl:>9,} ({n_crawl/total_rows*100:.2f}%)")
    print(f"    - Slow Urban (5 < v <= 15 km/h)     : {n_slow:>9,} ({n_slow/total_rows*100:.2f}%)")
    print(f"    - Cruising   (15 < v <= 35 km/h)    : {n_norm:>9,} ({n_norm/total_rows*100:.2f}%)")
    print(f"    - Fast Art.  (35 < v <= 60 km/h)    : {n_fast:>9,} ({n_fast/total_rows*100:.2f}%)")
    print(f"    - High Speed (60 < v <= 80 km/h)    : {n_high:>9,} ({n_high/total_rows*100:.2f}%)")
    print(f"    * Moving Speed (v > 0) Percentiles  : Mean={moving_spd.mean():.2f} km/h | P10={spd_q[0]:.1f} | P25={spd_q[1]:.1f} | P50={spd_q[2]:.1f} | P75={spd_q[3]:.1f} | P90={spd_q[4]:.1f} | P95={spd_q[5]:.1f} km/h")

    # Hourly Speed Profile (Mid-corridor moving buses: 100m < s < L-100m and v > 0)
    mid_moving = df[(df["s_bus_m"] > 100.0) & (df["s_bus_m"] < df["route_len_m"] - 100.0) & (df["derived_speed_kmh"] > 0)].copy()
    mid_moving["hour_vn"] = ((mid_moving["device_epoch"].astype(np.int64) + 7 * 3600) % 86400) // 3600
    hr_profile = mid_moving.groupby("hour_vn")["derived_speed_kmh"].agg(["count", "mean", "median"])
    print("\n  * Hourly Mid-Corridor Moving Speed Profile (UTC+7):")
    for hr in [6, 7, 8, 9, 12, 15, 17, 18, 19, 21]:
        if hr in hr_profile.index:
            r = hr_profile.loc[hr]
            tag = " [MORNING PEAK]" if hr in (7, 8) else (" [EVENING PEAK]" if hr in (17, 18) else "")
            print(f"    Hour {hr:02d}:00 | Pings={int(r['count']):>7,} | Mean={r['mean']:>5.2f} km/h | Median={r['median']:>5.2f} km/h{tag}")

    # 4. TRIP SEGMENTATION REALITY CHECK
    print("\n[4] MACROSCOPIC TRIP SEGMENTATION (dt > 300s or ds < -50m or direction flip)")
    ds_series = df_sorted["s_bus_m"] - df_sorted["s_bus_m"].shift(1)
    dt_full = df_sorted["device_epoch"] - df_sorted["device_epoch"].shift(1)
    new_trip = (~same_veh) | (dt_full > 300.0) | (ds_series < -50.0)
    df_sorted["trip_id"] = new_trip.cumsum()

    trip_agg = df_sorted.groupby("trip_id").agg(
        pings=("device_epoch", "count"),
        dur_min=("device_epoch", lambda x: (x.max() - x.min()) / 60.0),
        span_km=("s_bus_m", lambda x: (x.max() - x.min()) / 1000.0),
    )
    valid_trips = trip_agg[(trip_agg["pings"] >= 5) & (trip_agg["span_km"] >= 0.5)]
    print(f"  * Total Raw Trajectory Segments : {len(trip_agg):,}")
    print(f"  * Valid Active Trips (>=5 pings & >=0.5km span): {len(valid_trips):,} trips")
    print(f"    - Pings per Valid Trip        : Median={valid_trips['pings'].median():.0f} | Mean={valid_trips['pings'].mean():.1f} | P90={np.percentile(valid_trips['pings'], 90):.0f}")
    print(f"    - Duration per Valid Trip     : Median={valid_trips['dur_min'].median():.1f} min | Mean={valid_trips['dur_min'].mean():.1f} min | P90={np.percentile(valid_trips['dur_min'], 90):.1f} min")
    print(f"    - Distance Covered per Trip   : Median={valid_trips['span_km'].median():.2f} km | Mean={valid_trips['span_km'].mean():.2f} km | P90={np.percentile(valid_trips['span_km'], 90):.2f} km")

    # 5. SILVER TOMTOM INCIDENTS EDA
    print("\n[5] SILVER TOMTOM INCIDENTS FUSION (fact_route_tomtom_incidents)")
    inc_df = pd.read_sql_query(
        "SELECT route_code, direction, magnitude_of_delay, delay_seconds, overlap_length_m, d_perp_m, substr(t_start_utc, 1, 10) AS dt FROM fact_route_tomtom_incidents",
        conn,
    )
    print(f"  * Total Route-Matched Incident Episodes : {len(inc_df):,} rows across {inc_df['route_code'].nunique()}/{n_routes} routes")
    print(f"  * Date Span                             : {inc_df['dt'].min()} -> {inc_df['dt'].max()} ({inc_df['dt'].nunique()} days)")
    mag_counts = inc_df["magnitude_of_delay"].value_counts().sort_index()
    print(f"  * Severity Distribution (magnitude)     : {dict( {int(k): int(v) for k, v in mag_counts.items()} )}")
    print(f"  * Segment Overlap Length                : Mean={inc_df['overlap_length_m'].mean():.1f}m | Median={inc_df['overlap_length_m'].median():.1f}m")
    print(f"  * Proportional Delay Seconds (>0)       : Mean={inc_df.loc[inc_df['delay_seconds']>0, 'delay_seconds'].mean():.1f}s | P90={np.percentile(inc_df.loc[inc_df['delay_seconds']>0, 'delay_seconds'], 90):.1f}s")

    conn.close()
    print("\n" + "=" * 88)
    print(f"SILVER EDA COMPLETED IN {time.time() - t0:.2f}s")
    print("=" * 88)


if __name__ == "__main__":
    run_silver_eda()
