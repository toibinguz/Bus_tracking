"""
Step-by-Step Zero-Regression Verification Harness for Frenet Projection & Module 2 Schema
Evaluates worker_project_route on 3 benchmark routes (01, 02, 05) and reports:
- Total projected rows & direction balance ('go' vs 're')
- Defect 1: Off-corridor rows (cross_track_m > 35.0m)
- Defect 2: Backward jitter ds < 0 given positive speed (derived_speed_kmh > 0)
- Defect 3: Valid consecutive Silver chain (0 < dt <= 300s, -20m <= ds, speed <= 80 km/h) with NULL speed
- Defect 4: Mid-route backward jumps (ds < -20m within dt <= 300s, excluding terminal turnaround L->0)
"""

import sqlite3
import sys
import time
import numpy as np
import pandas as pd
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from module_1_data_ingestion_and_preprocessing.step_1_4_frenet_spatial_projection.multi_route_projector import (
    worker_project_route,
)

DB_PATH = "data/hanoi_bus_system.db"
TEST_ROUTES = ["01", "02", "05"]


def run_step_verification(step_label: str = "BASELINE"):
    t0 = time.time()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute(
        """
        SELECT route_id, station_id, MIN(direction)
        FROM canonical_station_master
        GROUP BY route_id, station_id
        HAVING COUNT(DISTINCT direction) = 1
        """
    )
    st_dir = {(r_id, st_id): d for r_id, st_id, d in cur.fetchall()}

    placeholders = ",".join(f"'{r}'" for r in TEST_ROUTES)
    routes = cur.execute(
        f"SELECT route_id, route_code FROM canonical_route_master WHERE route_code IN ({placeholders}) ORDER BY route_code"
    ).fetchall()

    shapes_by_route = {}
    shape_len_map = {}
    for r_id, r_code in routes:
        shapes_by_route[r_id] = {"go": [], "re": []}
        rows = cur.execute(
            "SELECT direction, point_order, lat, lon, cum_distance_m FROM canonical_shape_master WHERE route_id = ? ORDER BY direction, point_order",
            (r_id,),
        ).fetchall()
        for d, pt_ord, lat, lon, s_m in rows:
            shapes_by_route[r_id][d].append((pt_ord, lat, lon, s_m))
            shape_len_map[(r_code, d)] = max(shape_len_map.get((r_code, d), 0.0), float(s_m))
    conn.close()

    all_records = []
    for r_id, r_code in routes:
        _, _, _, recs, _ = worker_project_route((DB_PATH, r_id, r_code, shapes_by_route[r_id], st_dir))
        all_records.extend(recs)

    cols = [
        "ping_id", "route_code", "route_id", "vehicle_id", "plate",
        "device_update_time", "device_epoch", "direction",
        "lat", "lon", "s_bus_m", "cross_track_m", "derived_speed_kmh",
    ]
    if all_records and len(all_records[0]) == 14:
        cols.append("is_dwell")

    df = pd.DataFrame(all_records, columns=cols)
    df = df.sort_values(["route_code", "vehicle_id", "device_epoch"]).reset_index(drop=True)
    df["route_len"] = [shape_len_map.get((r, d), 0.0) for r, d in zip(df["route_code"], df["direction"])]

    same_dir = (
        (df["route_code"] == df["route_code"].shift(1))
        & (df["vehicle_id"] == df["vehicle_id"].shift(1))
        & (df["direction"] == df["direction"].shift(1))
    )
    dt = np.where(same_dir, df["device_epoch"] - df["device_epoch"].shift(1), np.nan)
    ds = np.where(same_dir, np.round(df["s_bus_m"] - df["s_bus_m"].shift(1), 1), np.nan)
    prev_s = np.where(same_dir, df["s_bus_m"].shift(1), np.nan)

    off_corridor = int((df["cross_track_m"] > 35.0).sum())
    bug_abs_ds = int(((ds < 0) & (df["derived_speed_kmh"] > 0)).sum())

    valid_chain = (
        same_dir
        & (dt > 0)
        & (dt <= 300.0)
        & (ds >= -20.0)
        & ((np.maximum(0.0, ds) / np.where(dt > 0, dt, 1.0) * 3.6) <= 80.0)
    )
    bug_false_null_spd = int((valid_chain & df["derived_speed_kmh"].isna()).sum())

    is_turnaround_reset = (prev_s >= (df["route_len"] - 800.0)) & (df["s_bus_m"] <= 800.0)
    mid_backjump = int((same_dir & (dt > 0) & (dt <= 300.0) & (ds < -20.0) & (~is_turnaround_reset)).sum())

    go_pct = (df["direction"] == "go").mean() * 100
    print("=" * 84)
    print(f"VERIFICATION HARNESS [{step_label}] (Routes 01, 02, 05 | Elapsed: {time.time()-t0:.2f}s)")
    print("=" * 84)
    print(f"  * Total Projected Pings        : {len(df):,} (go: {go_pct:.2f}% | re: {100-go_pct:.2f}%)")
    print(f"  * Schema Columns Count         : {len(cols)} ({'has is_dwell' if 'is_dwell' in cols else 'CLEAN - no is_dwell'})")
    print(f"  * [Defect 1] Off-corridor >35m : {off_corridor:,}")
    print(f"  * [Defect 2] ds<0 with speed>0 : {bug_abs_ds:,}")
    print(f"  * [Defect 3] False NULL speed  : {bug_false_null_spd:,}")
    print(f"  * [Defect 4] Mid-route backjump: {mid_backjump:,}")
    print("=" * 84)


def run_full_db_verification():
    t0 = time.time()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cols_info = cur.execute("PRAGMA table_info(route_projected_telemetry)").fetchall()
    col_names = [c[1] for c in cols_info]

    shape_rows = cur.execute(
        "SELECT route_code, direction, MAX(cum_distance_m) FROM canonical_shape_master GROUP BY route_code, direction"
    ).fetchall()
    shape_len_map = {(r, d): float(l) for r, d, l in shape_rows}

    df = pd.read_sql_query(
        "SELECT route_code, vehicle_id, device_epoch, direction, s_bus_m, cross_track_m, derived_speed_kmh FROM route_projected_telemetry ORDER BY route_code, vehicle_id, device_epoch",
        conn,
    )
    conn.close()

    df["route_len"] = [shape_len_map.get((r, d), 0.0) for r, d in zip(df["route_code"], df["direction"])]
    same_dir = (
        (df["route_code"] == df["route_code"].shift(1))
        & (df["vehicle_id"] == df["vehicle_id"].shift(1))
        & (df["direction"] == df["direction"].shift(1))
    )
    dt = np.where(same_dir, df["device_epoch"] - df["device_epoch"].shift(1), np.nan)
    ds = np.where(same_dir, np.round(df["s_bus_m"] - df["s_bus_m"].shift(1), 1), np.nan)
    prev_s = np.where(same_dir, df["s_bus_m"].shift(1), np.nan)

    off_corridor = int((df["cross_track_m"] > 35.0).sum())
    bug_abs_ds = int(((ds < 0) & (df["derived_speed_kmh"] > 0)).sum())
    valid_chain = (
        same_dir
        & (dt > 0)
        & (dt <= 300.0)
        & (ds >= -20.0)
        & ((np.maximum(0.0, ds) / np.where(dt > 0, dt, 1.0) * 3.6) <= 80.0)
    )
    bug_false_null_spd = int((valid_chain & df["derived_speed_kmh"].isna()).sum())
    is_turnaround_reset = (prev_s >= (df["route_len"] - 800.0)) & (df["s_bus_m"] <= 800.0)
    mid_backjump = int((same_dir & (dt > 0) & (dt <= 300.0) & (ds < -20.0) & (~is_turnaround_reset)).sum())

    go_pct = (df["direction"] == "go").mean() * 100
    print("=" * 84)
    print(f"FULL 48-ROUTE SQLITE ACCEPTANCE AUDIT [STEP_6_FULL_48_ROUTES] (Elapsed: {time.time()-t0:.2f}s)")
    print("=" * 84)
    print(f"  * Total Active Routes          : {df['route_code'].nunique()}")
    print(f"  * Total Projected Pings        : {len(df):,} (go: {go_pct:.2f}% | re: {100-go_pct:.2f}%)")
    print(f"  * Schema Columns Count         : {len(col_names)} ({'has is_dwell' if 'is_dwell' in col_names else 'CLEAN - no is_dwell'})")
    print(f"  * [Defect 1] Off-corridor >35m : {off_corridor:,}")
    print(f"  * [Defect 2] ds<0 with speed>0 : {bug_abs_ds:,}")
    print(f"  * [Defect 3] False NULL speed  : {bug_false_null_spd:,}")
    print(f"  * [Defect 4] Mid-route backjump: {mid_backjump:,}")
    print("=" * 84)


if __name__ == "__main__":
    label = sys.argv[1] if len(sys.argv) > 1 else "BASELINE"
    if label == "FULL_DB":
        run_full_db_verification()
    else:
        run_step_verification(label)
