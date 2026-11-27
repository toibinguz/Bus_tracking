"""
Module 3 - Step 3.1: Historical Baseline Travel Time Matrix & Temporal Split Engine
Strictly complies with docs/03_SILVER_TRAJECTORY_CONTINUITY_AND_ETA_CHECKLIST.md
and docs/04_TECHNICAL_DEBT_AND_OPEN_ISSUES_LEDGER.md:
- Enforces strict temporal split:
    * Train Set : dt <= TRAIN_SPLIT_END_DATE ('2026-10-31')
    * Test Set  : dt >= TEST_SPLIT_START_DATE ('2026-11-01')
- Uses continuity-aware trip segmentation (`segment_trajectory_into_trips` with `trim_terminals=True`).
- Extracts station arrival timestamps via linear trajectory interpolation ONLY when bracketed
  by consecutive pings satisfying `0 < dt <= BRACKET_MAX_DT_SEC` (150s) and `0 < ds <= BRACKET_MAX_DS_M` (1000m).
- Computes leak-free statistical baseline matrix (`agg_segment_travel_times`) strictly on Train trips
  with explicit `sample_count` and `quality_tier` (0, 1, 2, 3).
- Evaluates Baseline MAE / MedAE / RMSE / P90 on the held-out Test Set across both:
    * Adjacent station segments (k -> k+1)
    * Multi-station ETA horizons (1..5 stations, 6..15 stations, >15 stations)
"""

import gc
import json
import math
import os
import sqlite3
import sys
import time
from uuid import uuid4
from collections import defaultdict
from datetime import datetime
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds_pa
import pyarrow.parquet as pq

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
sys.path.insert(0, BASE_DIR)

from config.hardware_guard import check_memory_pressure, set_process_below_normal_priority
from config.system_config import (
    BASELINE_FIT_END_DATE,
    BASELINE_MAX_HOUR_SLOT,
    BASELINE_MIN_HOUR_SLOT,
    BASELINE_SAT_SUN_KERNEL_MIN_DIRECT,
    BASELINE_TIER0_MIN_SAMPLES,
    BASELINE_TIER0_MIN_SAMPLES_WEEKEND,
    BASELINE_TIER1_MIN_SAMPLES,
    BRACKET_MAX_DS_M,
    BRACKET_MAX_DT_SEC,
    BRACKET_SEG_LEN_FACTOR,
    CANONICAL_START_DATE,
    DAY_TYPE_SATURDAY,
    DAY_TYPE_SUNDAY,
    DAY_TYPE_WEEKDAY,
    DEFAULT_DB_PATH,
    DEFAULT_URBAN_BUS_SPEED_KMPH,
    EXCLUDE_TERMINAL_BOUNDARY_STATIONS,
    SEGMENT_MAX_SPEED_KMPH,
    SEGMENT_MIN_SPEED_KMPH,
    TEST_SPLIT_START_DATE,
    TRAIN_SPLIT_END_DATE,
    TZ_HANOI,
)
from modules.ingestion.sanitizer.trip_segmenter import (
    segment_trajectory_into_trips,
)
from modules.eta.baseline.baseline_core import (
    GOLD_BASELINE_COLUMNS,
    build_route_baseline_rows,
    extract_bracketed_station_arrivals,
    get_active_corridor_stations,
    get_bus_terminal_or_corridor_status,
)

DB_PATH = os.path.join(BASE_DIR, DEFAULT_DB_PATH)
SILVER_TEL_DIR: Optional[str] = None
GOLD_BASELINE_DIR: Optional[str] = None
from modules.eta.temporal_contract import split_at_dates


def _vehicle_frames(dataset):
    # Keep all days of each vehicle together, including trips crossing midnight.
    ids = set()
    for batch in dataset.to_batches(columns=["vehicle_id"]):
        ids.update(batch.column(0).unique().to_pylist())
    has_null = None in ids
    ids.discard(None)
    ordered = sorted(ids)
    field = ds_pa.field("vehicle_id")
    filters = [field.isin(ordered[i:i + 8]) for i in range(0, len(ordered), 8)]
    if has_null:
        filters.append(field.is_null())
    for predicate in filters:
        yield dataset.to_table(
            columns=["vehicle_id", "device_epoch", "direction", "s_bus_m", "derived_speed_kmh"],
            filter=predicate,
        ).to_pandas()


def build_and_evaluate_baseline_matrix(
    fit_end_date: Optional[str] = None,
    db_path: Optional[str] = None,
    silver_tel_dir: Optional[str] = None,
    gold_baseline_dir: Optional[str] = None,
) -> Dict[str, Any]:
    set_process_below_normal_priority()
    resolved_db = str(db_path) if db_path is not None else DB_PATH
    resolved_silver = str(silver_tel_dir) if silver_tel_dir is not None else SILVER_TEL_DIR
    resolved_gold = str(gold_baseline_dir) if gold_baseline_dir is not None else GOLD_BASELINE_DIR
    if not resolved_silver or not resolved_gold:
        raise ValueError("silver_tel_dir and gold_baseline_dir must be provided")

    t0 = time.time()
    fit_end_date = fit_end_date or BASELINE_FIT_END_DATE
    date.fromisoformat(fit_end_date)
    if fit_end_date > TRAIN_SPLIT_END_DATE:
        raise ValueError('baseline fit cutoff must not extend into test')
    print("=" * 88, flush=True)
    print("STEP 3.1 & 3.2: TEMPORAL SPLIT, TRIP SEGMENTATION & LEAK-FREE BASELINE MATRIX", flush=True)
    print(
        f"Baseline Fit: [{CANONICAL_START_DATE} .. {fit_end_date}] | "
        f"Train <= {TRAIN_SPLIT_END_DATE} | Test >= {TEST_SPLIT_START_DATE}",
        flush=True,
    )
    print("=" * 88, flush=True)

    conn = sqlite3.connect(resolved_db)
    cur = conn.cursor()

    # 1. Load canonical stations and shape lengths
    shape_rows = cur.execute(
        "SELECT route_code, direction, MAX(cum_distance_m) FROM canonical_shape_master GROUP BY route_code, direction"
    ).fetchall()
    shape_len_map = {(r, d): float(l) for r, d, l in shape_rows}

    st_rows = cur.execute(
        """
        SELECT route_code, direction, station_order, station_id, station_name, cum_distance_m
        FROM canonical_station_master
        ORDER BY route_code, direction, station_order
        """
    ).fetchall()
    stations_map: Dict[Tuple[str, str], List[Tuple[int, int, str, float]]] = defaultdict(list)
    for r_code, d_str, st_ord, st_id, st_name, s_m in st_rows:
        stations_map[(r_code, d_str)].append((int(st_ord), int(st_id), str(st_name), float(s_m)))

    # Read each route in groups of vehicles so cross-day trips remain intact.
    route_dirs = sorted(
        d
        for d in os.listdir(resolved_silver)
        if d.startswith("route_code=") and os.path.isdir(os.path.join(resolved_silver, d))
    )
    dt_partitioning = ds_pa.partitioning(pa.schema([("dt", pa.string())]), flavor="hive")

    train_trip_count = 0
    fit_trip_count = 0
    test_trip_count = 0
    total_pings = 0
    train_pings = 0
    test_pings = 0
    active_routes: List[str] = []

    # Extracted fit segment samples per route and direction:
    # (route_code, direction) -> list of (ord_a, ord_b, day_type, hr_slot, tt, seg_dist)
    fit_samples_by_route: Dict[str, Dict[str, List[Tuple[int, int, int, int, float, float]]]] = defaultdict(
        lambda: defaultdict(list)
    )

    # Store test trips with their station arrival dictionaries for evaluation
    test_trips_eval: List[Tuple[str, str, List[Tuple[str, float, float, float]], Dict[int, float]]] = []
    # Also store per-route trip and sample stats for EDA
    route_eda_stats: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"train_pings": 0, "test_pings": 0, "train_trips": 0, "test_trips": 0, "train_seg_samples": 0, "test_seg_samples": 0}
    )

    rejected_slow_Or_fast = 0
    unbracketed_pairs = 0

    def route_frames():
        for name in route_dirs:
            route = name.split("=", 1)[1]
            dataset = ds_pa.dataset(os.path.join(resolved_silver, name), format="parquet", partitioning=dt_partitioning)
            for frame in _vehicle_frames(dataset):
                yield route, frame

    for r_code, df_route in route_frames():
        if not active_routes or active_routes[-1] != r_code:
            active_routes.append(r_code)
        df_route["dt"] = (
            pd.to_datetime(df_route["device_epoch"], unit="s", utc=True)
            .dt.tz_convert("Asia/Ho_Chi_Minh")
            .dt.strftime("%Y-%m-%d")
        )
        df_route = df_route.sort_values(["vehicle_id", "direction", "device_epoch"]).reset_index(drop=True)

        n_route = len(df_route)
        n_route_train = int((df_route["dt"] <= TRAIN_SPLIT_END_DATE).sum())
        n_route_test = int((df_route["dt"] >= TEST_SPLIT_START_DATE).sum())
        total_pings += n_route
        train_pings += n_route_train
        test_pings += n_route_test

        for (vid, d_str), grp in df_route.groupby(["vehicle_id", "direction"], sort=False):
            r_len = shape_len_map.get((r_code, d_str), 0.0)
            full_st_list = stations_map.get((r_code, d_str), [])
            st_list = get_active_corridor_stations(full_st_list)
            if len(st_list) < 2:
                continue

            # Build lightweight tuples: (dt_str, epoch, s_bus_m, spd_kmh)
            pings_tuples = list(
                zip(
                    grp["dt"].tolist(),
                    grp["device_epoch"].tolist(),
                    grp["s_bus_m"].tolist(),
                    grp["derived_speed_kmh"].tolist(),
                )
            )
            for dt_s in grp["dt"].tolist():
                if dt_s <= TRAIN_SPLIT_END_DATE:
                    route_eda_stats[r_code]["train_pings"] += 1
                else:
                    route_eda_stats[r_code]["test_pings"] += 1

            trips = []
            for window in split_at_dates(pings_tuples, [fit_end_date, TRAIN_SPLIT_END_DATE]):
                trips.extend(
                    segment_trajectory_into_trips(
                        window, epoch_idx=1, s_idx=2, shape_len_m=r_len, trim_terminals=True
                    )
                )

            for tr in trips:
                tr_dt = tr[0][0]
                is_train = tr_dt <= TRAIN_SPLIT_END_DATE
                is_fit = tr[-1][0] <= fit_end_date
                if is_fit:
                    fit_trip_count += 1
                if is_train:
                    train_trip_count += 1
                    route_eda_stats[r_code]["train_trips"] += 1
                else:
                    test_trip_count += 1
                    route_eda_stats[r_code]["test_trips"] += 1

                arrivals = extract_bracketed_station_arrivals(tr, st_list, epoch_idx=1, s_idx=2)
                if len(arrivals) < 2:
                    continue

                if not is_train:
                    test_trips_eval.append((r_code, d_str, tr, arrivals))

                # Extract adjacent station segment travel times (k -> k+1)
                for k in range(len(st_list) - 1):
                    ord_a, _, _, s_a = st_list[k]
                    ord_b, _, _, s_b = st_list[k + 1]
                    seg_dist = s_b - s_a
                    if seg_dist <= 1.0:
                        continue

                    if ord_a in arrivals and ord_b in arrivals:
                        tt = arrivals[ord_b] - arrivals[ord_a]
                        if tt <= 0:
                            continue
                        spd_kmh = (seg_dist / tt) * 3.6
                        if not (SEGMENT_MIN_SPEED_KMPH <= spd_kmh <= SEGMENT_MAX_SPEED_KMPH):
                            rejected_slow_Or_fast += 1
                            continue

                        if is_fit:
                            dt_obj = datetime.fromtimestamp(arrivals[ord_a], tz=TZ_HANOI)
                            wd = dt_obj.weekday()
                            day_type = (
                                DAY_TYPE_WEEKDAY
                                if wd < 5
                                else (DAY_TYPE_SATURDAY if wd == 5 else DAY_TYPE_SUNDAY)
                            )
                            hr_slot = min(BASELINE_MAX_HOUR_SLOT, max(BASELINE_MIN_HOUR_SLOT, dt_obj.hour))
                            fit_samples_by_route[r_code][d_str].append(
                                (ord_a, ord_b, day_type, hr_slot, float(tt), float(seg_dist))
                            )
                            route_eda_stats[r_code]["train_seg_samples"] += 1
                        else:
                            route_eda_stats[r_code]["test_seg_samples"] += 1
                    else:
                        unbracketed_pairs += 1

        gc.collect()
        check_memory_pressure(label=f"baseline_route={r_code}")

    pct_train = (train_pings / total_pings * 100) if total_pings else 0.0
    pct_test = (test_pings / total_pings * 100) if total_pings else 0.0
    print(f"[1/4] Streamed Silver Lakehouse: {total_pings:,} pings | Train: {train_pings:,} ({pct_train:.2f}%) | Test: {test_pings:,} ({pct_test:.2f}%)", flush=True)
    total_fit_samples = sum(
        len(dir_list)
        for dir_map in fit_samples_by_route.values()
        for dir_list in dir_map.values()
    )
    print(
        f"[2/4] Segmented {train_trip_count + test_trip_count:,} clean trips "
        f"(Train: {train_trip_count:,} | Test: {test_trip_count:,}). "
        f"Extracted {total_fit_samples:,} valid Train segment traversals.",
        flush=True,
    )

    # 4. Build Complete Leak-Free Baseline Matrix across all active routes, segments, 3 day types (0/1/2), and 17 operating hours (5..21)
    active_routes = sorted(active_routes)
    matrix_rows = []
    tier_counts = {0: 0, 1: 0, 2: 0, 3: 0}

    # Lookup map for fast evaluation: (route_code, direction, from_order, to_order, day_type, hour_slot) -> (p50, p10, p90, mean, std, n, tier, seg_dist)
    baseline_lookup: Dict[Tuple[str, str, int, int, int, int], Tuple[float, float, float, float, float, int, int, float]] = {}

    for r_code in active_routes:
        stations_by_dir = {
            d_str: stations_map.get((r_code, d_str), [])
            for d_str in ("go", "re")
        }
        route_rows, route_tiers = build_route_baseline_rows(
            r_code, stations_by_dir, fit_samples_by_route.get(r_code, {})
        )
        for q_t, cnt in route_tiers.items():
            tier_counts[q_t] += cnt
        for row_tuple in route_rows:
            matrix_rows.append(row_tuple)
            baseline_lookup[(row_tuple[0], row_tuple[1], row_tuple[2], row_tuple[3], row_tuple[9], row_tuple[10])] = (
                row_tuple[14],
                row_tuple[13],
                row_tuple[15],
                row_tuple[16],
                row_tuple[17],
                row_tuple[11],
                row_tuple[12],
                row_tuple[8],
            )

    # Save Baseline Matrix to SQLite and Gold Parquet
    cur.execute("BEGIN")
    cur.execute("DROP TABLE IF EXISTS agg_segment_travel_times")
    cur.execute(
        """
        CREATE TABLE agg_segment_travel_times (
            route_code TEXT NOT NULL,
            direction TEXT NOT NULL,
            from_station_order INTEGER NOT NULL,
            to_station_order INTEGER NOT NULL,
            from_station_id INTEGER NOT NULL,
            to_station_id INTEGER NOT NULL,
            from_station_name TEXT,
            to_station_name TEXT,
            segment_length_m REAL NOT NULL,
            day_type INTEGER NOT NULL,
            hour_slot INTEGER NOT NULL,
            sample_count INTEGER NOT NULL,
            quality_tier INTEGER NOT NULL,
            tt_p10_sec REAL NOT NULL,
            tt_p50_sec REAL NOT NULL,
            tt_p90_sec REAL NOT NULL,
            tt_mean_sec REAL NOT NULL,
            tt_std_sec REAL NOT NULL,
            PRIMARY KEY (route_code, direction, from_station_order, to_station_order, day_type, hour_slot)
        )
        """
    )
    cur.executemany(
        "INSERT INTO agg_segment_travel_times VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        matrix_rows,
    )
    build_id = uuid4().hex
    cur.execute("DROP TABLE IF EXISTS eta_baseline_manifest")
    cur.execute("CREATE TABLE eta_baseline_manifest(fit_end_date TEXT, train_end_date TEXT, "
                "test_start_date TEXT, source TEXT, snapshot_id TEXT, build_id TEXT)")
    cur.execute("INSERT INTO eta_baseline_manifest VALUES (?, ?, ?, 'local', NULL, ?)",
                (fit_end_date, TRAIN_SPLIT_END_DATE, TEST_SPLIT_START_DATE, build_id))

    os.makedirs(resolved_gold, exist_ok=True)
    df_matrix = pd.DataFrame(matrix_rows, columns=list(GOLD_BASELINE_COLUMNS))
    table = pa.Table.from_pandas(df_matrix, preserve_index=False)
    table = table.replace_schema_metadata({**(table.schema.metadata or {}), b"build_id": build_id.encode()})
    part = os.path.join(resolved_gold, "part-00000.snappy.parquet")
    temporary = os.path.join(resolved_gold, f".{build_id}.tmp")
    try:
        pq.write_table(table, temporary, compression="snappy")
        os.replace(temporary, part)
        conn.commit()
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
        conn.close()

    total_cells = len(matrix_rows)
    print(
        f"[3/4] Built Leak-Free Baseline Matrix (3 Day-Types x 17 Hours): {total_cells:,} cells | "
        f"Tier 0: {tier_counts[0]:,} ({tier_counts[0]/total_cells*100:.1f}%) | "
        f"Tier 1: {tier_counts[1]:,} ({tier_counts[1]/total_cells*100:.1f}%) | "
        f"Tier 2 (Neighbor): {tier_counts[2]:,} ({tier_counts[2]/total_cells*100:.1f}%) | "
        f"Tier 3 (Fallback): {tier_counts[3]:,} ({tier_counts[3]/total_cells*100:.1f}%)",
        flush=True,
    )

    # 5. Evaluate Baseline Matrix on Held-Out Test Set (2026-11-01 .. 2026-11-07)
    seg_errors_by_tier: Dict[int, List[float]] = defaultdict(list)
    seg_errors_by_daytype: Dict[int, List[float]] = defaultdict(list)
    horizon_errors_p50: Dict[str, List[float]] = defaultdict(list)
    horizon_errors_mean: Dict[str, List[float]] = defaultdict(list)

    for r_code, d_str, tr, arrivals in test_trips_eval:
        st_list = get_active_corridor_stations(stations_map[(r_code, d_str)])
        # Map station_order -> index k in st_list
        ord_to_k = {st[0]: idx_k for idx_k, st in enumerate(st_list)}
        sorted_arr_orders = sorted(arrivals.keys())

        # 5a. Single-segment evaluation (k -> k+1)
        for k in range(len(st_list) - 1):
            ord_a, _, _, s_a = st_list[k]
            ord_b, _, _, s_b = st_list[k + 1]
            seg_dist = s_b - s_a
            if ord_a in arrivals and ord_b in arrivals and seg_dist > 1.0:
                actual_tt = arrivals[ord_b] - arrivals[ord_a]
                spd_kmh = (seg_dist / actual_tt) * 3.6 if actual_tt > 0 else 0.0
                if not (SEGMENT_MIN_SPEED_KMPH <= spd_kmh <= SEGMENT_MAX_SPEED_KMPH):
                    continue
                dt_obj = datetime.fromtimestamp(arrivals[ord_a], tz=TZ_HANOI)
                wd = dt_obj.weekday()
                day_type = (
                    DAY_TYPE_WEEKDAY
                    if wd < 5
                    else (DAY_TYPE_SATURDAY if wd == 5 else DAY_TYPE_SUNDAY)
                )
                hr_slot = min(BASELINE_MAX_HOUR_SLOT, max(BASELINE_MIN_HOUR_SLOT, dt_obj.hour))
                cell = baseline_lookup.get((r_code, d_str, ord_a, ord_b, day_type, hr_slot))
                if cell:
                    pred_p50 = cell[0]
                    q_tier = cell[6]
                    seg_errors_by_tier[q_tier].append(actual_tt - pred_p50)
                    seg_errors_by_daytype[day_type].append(actual_tt - pred_p50)

        # 5b. Multi-station ETA evaluation along the trip (TD-B04: compare Sum(P50) vs Additive Sum(Mean))
        for i_a in range(len(sorted_arr_orders)):
            ord_start = sorted_arr_orders[i_a]
            k_start = ord_to_k[ord_start]
            t_start = arrivals[ord_start]
            dt_obj = datetime.fromtimestamp(t_start, tz=TZ_HANOI)
            wd = dt_obj.weekday()
            day_type = (
                DAY_TYPE_WEEKDAY
                if wd < 5
                else (DAY_TYPE_SATURDAY if wd == 5 else DAY_TYPE_SUNDAY)
            )
            hr_slot = min(BASELINE_MAX_HOUR_SLOT, max(BASELINE_MIN_HOUR_SLOT, dt_obj.hour))

            for i_b in range(i_a + 1, len(sorted_arr_orders)):
                ord_end = sorted_arr_orders[i_b]
                k_end = ord_to_k[ord_end]
                n_hops = k_end - k_start
                if n_hops <= 0:
                    continue

                actual_eta = arrivals[ord_end] - t_start
                if actual_eta <= 0 or actual_eta > 7200:
                    continue

                # Sum baseline P50 and Mean across intermediate segments k_start .. k_end-1
                pred_eta_p50 = 0.0
                pred_eta_mean = 0.0
                valid_path = True
                for k_step in range(k_start, k_end):
                    o_u = st_list[k_step][0]
                    o_v = st_list[k_step + 1][0]
                    cell = baseline_lookup.get((r_code, d_str, o_u, o_v, day_type, hr_slot))
                    if not cell:
                        valid_path = False
                        break
                    pred_eta_p50 += cell[0]
                    pred_eta_mean += cell[3]

                if not valid_path:
                    continue

                err_p50 = actual_eta - pred_eta_p50
                err_mean = actual_eta - pred_eta_mean
                if n_hops == 1:
                    h_bucket = "1_hop_adjacent"
                elif 2 <= n_hops <= 5:
                    h_bucket = "2_to_5_stations"
                elif 6 <= n_hops <= 15:
                    h_bucket = "6_to_15_stations"
                else:
                    h_bucket = "gt_15_stations"
                horizon_errors_p50[h_bucket].append(err_p50)
                horizon_errors_mean[h_bucket].append(err_mean)

    print("\n[4/4] HELD-OUT TEST SET BENCHMARK (2026-11-01 .. 2026-11-07) — STATISTICAL BASELINE ONLY:", flush=True)
    print("-" * 100, flush=True)
    print("  [A] Estimator: Sum(tt_p50_sec) (Optimal for MedAE on short hops, underestimates long horizons):", flush=True)
    for h_key in ("1_hop_adjacent", "2_to_5_stations", "6_to_15_stations", "gt_15_stations"):
        errs = horizon_errors_p50.get(h_key, [])
        if not errs:
            continue
        arr_e = np.array(errs, dtype=np.float64)
        abs_e = np.abs(arr_e)
        print(
            f"    * Horizon {h_key:<18}: N={len(arr_e):>9,} | "
            f"MAE={np.mean(abs_e):>6.2f}s ({np.mean(abs_e)/60:.2f}m) | "
            f"MedAE={np.median(abs_e):>6.2f}s | Bias={np.mean(arr_e):>+6.2f}s | RMSE={np.sqrt(np.mean(arr_e**2)):>6.2f}s",
            flush=True,
        )
    print("  [B] Estimator: Sum(tt_mean_sec) (TD-11 Expectation-Additive for multi-station MAE & zero bias):", flush=True)
    for h_key in ("1_hop_adjacent", "2_to_5_stations", "6_to_15_stations", "gt_15_stations"):
        errs = horizon_errors_mean.get(h_key, [])
        if not errs:
            continue
        arr_e = np.array(errs, dtype=np.float64)
        abs_e = np.abs(arr_e)
        print(
            f"    * Horizon {h_key:<18}: N={len(arr_e):>9,} | "
            f"MAE={np.mean(abs_e):>6.2f}s ({np.mean(abs_e)/60:.2f}m) | "
            f"MedAE={np.median(abs_e):>6.2f}s | Bias={np.mean(arr_e):>+6.2f}s | RMSE={np.sqrt(np.mean(arr_e**2)):>6.2f}s",
            flush=True,
        )
    print("-" * 100, flush=True)
    day_labels = {0: "Weekday (Mon-Fri)", 1: "Saturday (Thứ 7) ", 2: "Sunday (Chủ Nhật)"}
    for dt_k in sorted(seg_errors_by_daytype.keys()):
        arr_e = np.array(seg_errors_by_daytype[dt_k], dtype=np.float64)
        abs_e = np.abs(arr_e)
        print(
            f"  * Day-Type {dt_k} [{day_labels[dt_k]}]: N={len(arr_e):>9,} | "
            f"MAE={np.mean(abs_e):>6.2f}s | MedAE={np.median(abs_e):>6.2f}s | Bias={np.mean(arr_e):>+6.2f}s | RMSE={np.sqrt(np.mean(arr_e**2)):>6.2f}s",
            flush=True,
        )
    print("-" * 100, flush=True)
    for qt in sorted(seg_errors_by_tier.keys()):
        arr_e = np.array(seg_errors_by_tier[qt], dtype=np.float64)
        abs_e = np.abs(arr_e)
        print(
            f"  * Quality Tier {qt} (1-Segment) : N={len(arr_e):>9,} | "
            f"MAE={np.mean(abs_e):>6.2f}s | MedAE={np.median(abs_e):>6.2f}s | Bias={np.mean(arr_e):>+6.2f}s",
            flush=True,
        )
    print("=" * 100, flush=True)

    return {
        "total_cells": total_cells,
        "tier_counts": tier_counts,
        "train_trips": train_trip_count,
        "fit_trips": fit_trip_count,
        "fit_end_date": fit_end_date,
        "test_trips": test_trip_count,
        "rejected_slow_or_fast": rejected_slow_Or_fast,
        "unbracketed_pairs": unbracketed_pairs,
        "route_eda_stats": dict(route_eda_stats),
        "elapsed_sec": round(time.time() - t0, 2),
    }


if __name__ == "__main__":
    build_and_evaluate_baseline_matrix()
