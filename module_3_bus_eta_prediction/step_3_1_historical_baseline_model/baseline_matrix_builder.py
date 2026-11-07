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

import json
import math
import os
import sqlite3
import sys
import time
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import pyarrow.dataset as ds_pa

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, BASE_DIR)

from config.system_config import (
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
    DEFAULT_LAKEHOUSE_ROOT,
    DEFAULT_URBAN_BUS_SPEED_KMPH,
    EXCLUDE_TERMINAL_BOUNDARY_STATIONS,
    SEGMENT_MAX_SPEED_KMPH,
    SEGMENT_MIN_SPEED_KMPH,
    TEST_SPLIT_START_DATE,
    TRAIN_SPLIT_END_DATE,
    TZ_HANOI,
)
from module_1_data_ingestion_and_preprocessing.step_1_3_telemetry_kinematic_sanitizer.trip_segmenter import (
    segment_trajectory_into_trips,
)

DB_PATH = os.path.join(BASE_DIR, DEFAULT_DB_PATH)
SILVER_TEL_DIR = os.path.join(BASE_DIR, DEFAULT_LAKEHOUSE_ROOT, "silver", "route_projected_telemetry")
GOLD_BASELINE_DIR = os.path.join(BASE_DIR, DEFAULT_LAKEHOUSE_ROOT, "gold", "agg_segment_travel_times")


def get_active_corridor_stations(
    st_list: List[Tuple[int, int, str, float]]
) -> List[Tuple[int, int, str, float]]:
    """
    TD-19: Excludes the 2 terminal boundary stations (Origin Terminal station_order == 0
    and Destination Terminal depot station_order == N) when EXCLUDE_TERMINAL_BOUNDARY_STATIONS
    is enabled, returning the active in-transit corridor stations [1 .. N-1].
    """
    if EXCLUDE_TERMINAL_BOUNDARY_STATIONS and len(st_list) >= 4:
        return st_list[1:-1]
    return st_list


def get_bus_terminal_or_corridor_status(
    s_bus_m: float, st_list: List[Tuple[int, int, str, float]]
) -> str:
    """
    TD-19: Classifies a same-direction bus into:
      - 'AT_ORIGIN_TERMINAL'      : s_bus_m < s_station[1] (waiting for dispatch or exiting gate)
      - 'AT_DESTINATION_TERMINAL' : s_bus_m >= s_station[N-1] (entering destination depot gate)
      - 'ACTIVE_IN_TRANSIT'       : s_station[1] <= s_bus_m < s_station[N-1] (eligible for kinematic ETA)
    """
    if len(st_list) >= 4:
        if s_bus_m < st_list[1][3]:
            return "AT_ORIGIN_TERMINAL"
        if s_bus_m >= st_list[-2][3]:
            return "AT_DESTINATION_TERMINAL"
    return "ACTIVE_IN_TRANSIT"


def extract_bracketed_station_arrivals(
    trip: List[Tuple[Any, ...]],
    stations: List[Tuple[int, int, str, float]],
    epoch_idx: int = 1,
    s_idx: int = 2,
) -> Dict[int, float]:
    """
    Given a valid forward trip (list of tuples with device_epoch and s_bus_m)
    and ordered route stations [(station_order, station_id, station_name, s_station_m)],
    returns a dict `{station_order: interpolated_arrival_epoch}` for all stations
    that are tightly bracketed by a consecutive pair of pings in the trip:
      - s_prev <= s_station <= s_curr
      - 0 < dt <= BRACKET_MAX_DT_SEC (150s)
      - 0 <= ds <= BRACKET_MAX_DS_M (1000m)
    Strictly respects Checklist 3 (no backward extrapolation before trip start s_first)
    and Checklist 4 (Bracketing Guard against detour gaps).
    """
    if len(trip) < 2 or not stations:
        return {}

    epochs = np.array([float(p[epoch_idx]) for p in trip], dtype=np.float64)
    s_vals = np.array([float(p[s_idx]) for p in trip], dtype=np.float64)

    # Enforce cumulative monotonic envelope for station crossing interpolation
    s_mono = np.maximum.accumulate(s_vals)
    s_start = s_mono[0]
    s_end = s_mono[-1]

    arrivals: Dict[int, float] = {}
    n_pings = len(trip)
    n_st = len(stations)
    p_idx = 0

    for k_st, (st_order, _, _, s_st) in enumerate(stations):
        if s_st < s_start or s_st > s_end:
            continue

        # Advance p_idx until s_mono[p_idx + 1] >= s_st
        while p_idx + 1 < n_pings and s_mono[p_idx + 1] < s_st:
            p_idx += 1

        if p_idx + 1 >= n_pings:
            break

        s0 = s_mono[p_idx]
        s1 = s_mono[p_idx + 1]
        t0 = epochs[p_idx]
        t1 = epochs[p_idx + 1]
        dt = t1 - t0
        ds = s1 - s0

        # TD-B02: Adaptive bracketing guard for long highway/bridge segments > 1000m
        prev_st_s = stations[k_st - 1][3] if k_st > 0 else s_st
        next_st_s = stations[k_st + 1][3] if k_st + 1 < n_st else s_st
        local_seg_len = max(s_st - prev_st_s, next_st_s - s_st)
        max_allowed_ds = max(BRACKET_MAX_DS_M, BRACKET_SEG_LEN_FACTOR * local_seg_len)

        if 0.0 < dt <= BRACKET_MAX_DT_SEC and 0.0 <= ds <= max_allowed_ds:
            if ds > 1e-3:
                ratio = (s_st - s0) / ds
                t_arr = t0 + ratio * dt
            else:
                t_arr = t0
            arrivals[st_order] = float(t_arr)

    return arrivals


def build_and_evaluate_baseline_matrix() -> Dict[str, Any]:
    t0 = time.time()
    print("=" * 88, flush=True)
    print("STEP 3.1 & 3.2: TEMPORAL SPLIT, TRIP SEGMENTATION & LEAK-FREE BASELINE MATRIX", flush=True)
    print(f"Train Window: [{CANONICAL_START_DATE} .. {TRAIN_SPLIT_END_DATE}] | Test Window: [{TEST_SPLIT_START_DATE} .. 2026-11-07]", flush=True)
    print("=" * 88, flush=True)

    conn = sqlite3.connect(DB_PATH)
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

    # 2. Scan Silver Parquet dataset grouped by route_code
    dataset = ds_pa.dataset(SILVER_TEL_DIR, format="parquet", partitioning="hive")
    tbl = dataset.to_table(
        columns=["route_code", "vehicle_id", "device_update_time", "device_epoch", "direction", "s_bus_m", "derived_speed_kmh"]
    )
    df_all = tbl.to_pandas()
    df_all["dt"] = df_all["device_update_time"].str.slice(0, 10)
    df_all = df_all.sort_values(["route_code", "vehicle_id", "direction", "device_epoch"]).reset_index(drop=True)

    train_pings = int((df_all["dt"] <= TRAIN_SPLIT_END_DATE).sum())
    test_pings = int((df_all["dt"] >= TEST_SPLIT_START_DATE).sum())
    print(f"[1/4] Loaded Silver Lakehouse: {len(df_all):,} pings | Train: {train_pings:,} ({train_pings/len(df_all)*100:.2f}%) | Test: {test_pings:,} ({test_pings/len(df_all)*100:.2f}%)", flush=True)

    # 3. Segment trajectories into clean trips & extract bracketed station arrivals
    train_trip_count = 0
    test_trip_count = 0

    # Key for segment samples: (route_code, direction, from_order, to_order, is_weekend, hour_slot) -> list of travel_time_sec
    slot_samples: Dict[Tuple[str, str, int, int, int, int], List[float]] = defaultdict(list)
    # Key for segment across all hours of same day type: (route_code, direction, from_order, to_order, is_weekend)
    daytype_samples: Dict[Tuple[str, str, int, int, int], List[float]] = defaultdict(list)
    # Key for segment across all days/hours: (route_code, direction, from_order, to_order)
    seg_all_samples: Dict[Tuple[str, str, int, int], List[float]] = defaultdict(list)
    # Route-direction average speed fallback: (route_code, direction) -> [sum_dist, sum_time]
    route_speed_accum: Dict[Tuple[str, str], List[float]] = defaultdict(lambda: [0.0, 0.0])

    # Store test trips with their station arrival dictionaries for evaluation
    test_trips_eval: List[Tuple[str, str, List[Tuple[str, float, float, float]], Dict[int, float]]] = []
    # Also store per-route trip and sample stats for EDA
    route_eda_stats: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"train_pings": 0, "test_pings": 0, "train_trips": 0, "test_trips": 0, "train_seg_samples": 0, "test_seg_samples": 0}
    )

    rejected_slow_Or_fast = 0
    unbracketed_pairs = 0

    for (r_code, vid, d_str), grp in df_all.groupby(["route_code", "vehicle_id", "direction"], sort=False):
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

        trips = segment_trajectory_into_trips(
            pings_tuples, epoch_idx=1, s_idx=2, shape_len_m=r_len, trim_terminals=True
        )

        for tr in trips:
            tr_dt = tr[0][0]
            is_train = tr_dt <= TRAIN_SPLIT_END_DATE
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

                    if is_train:
                        dt_obj = datetime.fromtimestamp(arrivals[ord_a], tz=TZ_HANOI)
                        wd = dt_obj.weekday()
                        day_type = (
                            DAY_TYPE_WEEKDAY
                            if wd < 5
                            else (DAY_TYPE_SATURDAY if wd == 5 else DAY_TYPE_SUNDAY)
                        )
                        hr_slot = min(BASELINE_MAX_HOUR_SLOT, max(BASELINE_MIN_HOUR_SLOT, dt_obj.hour))
                        slot_samples[(r_code, d_str, ord_a, ord_b, day_type, hr_slot)].append(tt)
                        daytype_samples[(r_code, d_str, ord_a, ord_b, day_type)].append(tt)
                        seg_all_samples[(r_code, d_str, ord_a, ord_b)].append(tt)
                        route_speed_accum[(r_code, d_str)][0] += seg_dist
                        route_speed_accum[(r_code, d_str)][1] += tt
                        route_eda_stats[r_code]["train_seg_samples"] += 1
                    else:
                        route_eda_stats[r_code]["test_seg_samples"] += 1
                else:
                    unbracketed_pairs += 1

    print(
        f"[2/4] Segmented {train_trip_count + test_trip_count:,} clean trips "
        f"(Train: {train_trip_count:,} | Test: {test_trip_count:,}). "
        f"Extracted {sum(len(v) for v in slot_samples.values()):,} valid Train segment traversals.",
        flush=True,
    )

    # 4. Build Complete Leak-Free Baseline Matrix across all active routes, segments, 3 day types (0/1/2), and 17 operating hours (5..21)
    active_routes = sorted(df_all["route_code"].unique())
    matrix_rows = []
    tier_counts = {0: 0, 1: 0, 2: 0, 3: 0}

    # Lookup map for fast evaluation: (route_code, direction, from_order, to_order, day_type, hour_slot) -> (p50, p10, p90, mean, std, n, tier, seg_dist)
    baseline_lookup: Dict[Tuple[str, str, int, int, int, int], Tuple[float, float, float, float, float, int, int, float]] = {}

    for r_code in active_routes:
        for d_str in ("go", "re"):
            st_list = get_active_corridor_stations(stations_map.get((r_code, d_str), []))
            if len(st_list) < 2:
                continue

            tot_d, tot_t = route_speed_accum.get((r_code, d_str), [0.0, 0.0])
            route_avg_mps = (tot_d / tot_t) if tot_t > 0 else (DEFAULT_URBAN_BUS_SPEED_KMPH / 3.6)

            for k in range(len(st_list) - 1):
                ord_a, id_a, name_a, s_a = st_list[k]
                ord_b, id_b, name_b, s_b = st_list[k + 1]
                seg_dist = round(max(15.0, s_b - s_a), 1)

                for day_type in (DAY_TYPE_WEEKDAY, DAY_TYPE_SATURDAY, DAY_TYPE_SUNDAY):
                    tier0_thresh = (
                        BASELINE_TIER0_MIN_SAMPLES
                        if day_type == DAY_TYPE_WEEKDAY
                        else BASELINE_TIER0_MIN_SAMPLES_WEEKEND
                    )
                    for hr_slot in range(BASELINE_MIN_HOUR_SLOT, BASELINE_MAX_HOUR_SLOT + 1):
                        direct_vals = slot_samples.get((r_code, d_str, ord_a, ord_b, day_type, hr_slot), [])
                        n_direct = len(direct_vals)

                        # TD-18: For Saturday (4 days) and Sunday (3 days), apply 3-hour sliding kernel
                        # [hr-1, hr, hr+1] strictly on the SAME day_type when direct count < 8
                        if day_type in (DAY_TYPE_SATURDAY, DAY_TYPE_SUNDAY) and n_direct < BASELINE_SAT_SUN_KERNEL_MIN_DIRECT:
                            eff_vals = []
                            for h_adj in (hr_slot - 1, hr_slot, hr_slot + 1):
                                eff_vals.extend(slot_samples.get((r_code, d_str, ord_a, ord_b, day_type, h_adj), []))
                        else:
                            eff_vals = direct_vals

                        n_eff = len(eff_vals)

                        if n_eff >= tier0_thresh:
                            q_tier = 0
                            used_vals = eff_vals
                        elif n_eff >= BASELINE_TIER1_MIN_SAMPLES:
                            q_tier = 1
                            used_vals = eff_vals
                        else:
                            # Tier 2: Pool adjacent hours (hr-1, hr, hr+1) on same day type, or full day_type / segment samples
                            neighbor_vals = []
                            for h_adj in (hr_slot - 1, hr_slot, hr_slot + 1):
                                neighbor_vals.extend(slot_samples.get((r_code, d_str, ord_a, ord_b, day_type, h_adj), []))
                            if len(neighbor_vals) >= BASELINE_TIER1_MIN_SAMPLES:
                                q_tier = 2
                                used_vals = neighbor_vals
                            elif len(daytype_samples.get((r_code, d_str, ord_a, ord_b, day_type), [])) >= BASELINE_TIER1_MIN_SAMPLES:
                                q_tier = 2
                                used_vals = daytype_samples[(r_code, d_str, ord_a, ord_b, day_type)]
                            elif len(seg_all_samples.get((r_code, d_str, ord_a, ord_b), [])) >= 1:
                                q_tier = 2
                                used_vals = seg_all_samples[(r_code, d_str, ord_a, ord_b)]
                            else:
                                q_tier = 3
                                used_vals = []

                        tier_counts[q_tier] += 1

                        if used_vals:
                            arr = np.array(used_vals, dtype=np.float64)
                            p10 = float(np.percentile(arr, 10))
                            p50 = float(np.percentile(arr, 50))
                            p90 = float(np.percentile(arr, 90))
                            mean_v = float(np.mean(arr))
                            std_v = float(np.std(arr)) if len(arr) > 1 else round(0.15 * mean_v, 2)
                        else:
                            # Tier 3 physical kinematics fallback
                            p50 = seg_dist / max(1.0, route_avg_mps)
                            p10 = p50 * 0.75
                            p90 = p50 * 1.35
                            mean_v = p50
                            std_v = p50 * 0.20

                        row_tuple = (
                            r_code,
                            d_str,
                            ord_a,
                            ord_b,
                            id_a,
                            id_b,
                            name_a,
                            name_b,
                            seg_dist,
                            day_type,
                            hr_slot,
                            n_eff,
                            q_tier,
                            round(p10, 2),
                            round(p50, 2),
                            round(p90, 2),
                            round(mean_v, 2),
                            round(std_v, 2),
                        )
                        matrix_rows.append(row_tuple)
                        baseline_lookup[(r_code, d_str, ord_a, ord_b, day_type, hr_slot)] = (
                            round(p50, 2),
                            round(p10, 2),
                            round(p90, 2),
                            round(mean_v, 2),
                            round(std_v, 2),
                            n_eff,
                            q_tier,
                            seg_dist,
                        )

    # Save Baseline Matrix to SQLite and Gold Parquet
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
    cur.commit() if hasattr(cur, "commit") else conn.commit()
    conn.close()

    os.makedirs(GOLD_BASELINE_DIR, exist_ok=True)
    df_matrix = pd.DataFrame(
        matrix_rows,
        columns=[
            "route_code", "direction", "from_station_order", "to_station_order",
            "from_station_id", "to_station_id", "from_station_name", "to_station_name",
            "segment_length_m", "day_type", "hour_slot", "sample_count", "quality_tier",
            "tt_p10_sec", "tt_p50_sec", "tt_p90_sec", "tt_mean_sec", "tt_std_sec",
        ],
    )
    df_matrix.to_parquet(
        os.path.join(GOLD_BASELINE_DIR, "part-00000.snappy.parquet"),
        engine="pyarrow",
        compression="snappy",
        index=False,
    )

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
        "test_trips": test_trip_count,
        "rejected_slow_or_fast": rejected_slow_Or_fast,
        "unbracketed_pairs": unbracketed_pairs,
        "route_eda_stats": dict(route_eda_stats),
        "elapsed_sec": round(time.time() - t0, 2),
    }


if __name__ == "__main__":
    build_and_evaluate_baseline_matrix()
