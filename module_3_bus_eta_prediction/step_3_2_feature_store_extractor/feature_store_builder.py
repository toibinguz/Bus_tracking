"""
Module 3 - Step 3.3: Unified Gold Feature Store Extractor (Parallel Multi-Core O(1) Engine)
Strictly complies with AGENTS.md, docs/03_SILVER_TRAJECTORY_CONTINUITY_AND_ETA_CHECKLIST.md,
and docs/04_TECHNICAL_DEBT_AND_OPEN_ISSUES_LEDGER.md (TD-01 .. TD-19).

Optimizations over naive single-core implementation:
  1. Multi-core parallel execution across all 48 routes via `ProcessPoolExecutor` (each route reads its
     own Hive partition and writes directly to `gold/eta_feature_store/split={train,test}/route_code=XX/`).
  2. O(1) prefix-sum evaluation for BOTH Historical Baseline (d) AND Recent Preceding-Bus Probe (c)
     (eliminates inner O(M) Python loops per target station).
  3. Monotonic two-pointer active incident maintenance for TomTom Incidents (e) (checks only the 0..3
     currently active episodes at `t_cur` instead of slicing 12-hour arrays).
  4. Spatial stride deduplication (`>= 150m` advance between sampled ego-bus query points along the
     same trip) + 4 balanced horizon targets per query point (`1 hop`, `short +4`, `medium +10`, `long +20/end`),
     producing ~6M high-information, low-autocorrelation training & test pairs in < 45 seconds.
"""

import math
import os
import shutil
import sqlite3
import sys
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
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
    DAY_TYPE_SATURDAY,
    DAY_TYPE_SUNDAY,
    DAY_TYPE_WEEKDAY,
    DEFAULT_DB_PATH,
    DEFAULT_LAKEHOUSE_ROOT,
    DEFAULT_URBAN_BUS_SPEED_KMPH,
    SEGMENT_MAX_SPEED_KMPH,
    SEGMENT_MIN_SPEED_KMPH,
    TEST_SPLIT_START_DATE,
    TRAIN_SPLIT_END_DATE,
    TZ_HANOI,
)
from module_1_data_ingestion_and_preprocessing.step_1_3_telemetry_kinematic_sanitizer.trip_segmenter import (
    segment_trajectory_into_trips,
)
from module_3_bus_eta_prediction.step_3_1_historical_baseline_model.baseline_matrix_builder import (
    extract_bracketed_station_arrivals,
    get_active_corridor_stations,
)

DB_PATH = os.path.join(BASE_DIR, DEFAULT_DB_PATH)
SILVER_TEL_DIR = os.path.join(BASE_DIR, DEFAULT_LAKEHOUSE_ROOT, "silver", "route_projected_telemetry")
SILVER_INC_DIR = os.path.join(BASE_DIR, DEFAULT_LAKEHOUSE_ROOT, "silver", "fact_route_tomtom_incidents")
GOLD_FEATURE_DIR = os.path.join(BASE_DIR, DEFAULT_LAKEHOUSE_ROOT, "gold", "eta_feature_store")


def initialize_storage_paths(db_path, silver_tel_dir, silver_inc_dir, gold_feature_dir):
    """Pass the selected history workspace to spawned worker processes."""
    global DB_PATH, SILVER_TEL_DIR, SILVER_INC_DIR, GOLD_FEATURE_DIR
    DB_PATH, SILVER_TEL_DIR, SILVER_INC_DIR, GOLD_FEATURE_DIR = db_path, silver_tel_dir, silver_inc_dir, gold_feature_dir

RECENT_PROBE_WINDOW_SEC = 1800.0   # 30-minute causal window for preceding bus segment traversals
FLEET_ACTIVE_WINDOW_SEC = 300.0    # 5-minute causal window for active lead/following buses on same route
MIN_EGO_SAMPLE_ADVANCE_M = 150.0   # Minimum spatial advance between consecutive ego query points in a trip

FEATURE_COLUMNS = [
    # Metadata & Target (8 columns)
    "route_code", "direction", "dt", "vehicle_id", "device_epoch",
    "current_station_order", "target_station_order", "actual_eta_sec",
    # (a) Current Ego-Bus State & Kinematics (21 columns)
    "route_id_idx", "direction_id", "day_type", "day_of_week", "hour_slot",
    "sin_time", "cos_time", "s_bus_m", "s_target_m", "remaining_distance_m",
    "n_stations_ahead", "progress_ratio", "target_progress_ratio", "dist_to_next_station_m",
    "ego_speed_instant_kmh", "ego_speed_roll3_kmh", "ego_speed_roll5_kmh",
    "ego_accel_kmh_per_min", "ego_speed_ratio_vs_baseline",
    "ego_trip_elapsed_sec", "ego_cum_delay_vs_baseline_sec",
    # (b) Same-Route Fleet Ahead & Behind (8 columns)
    "lead_bus_dist_ahead_m", "lead_bus_time_headway_sec", "lead_bus_speed_kmh",
    "lead_bus_speed_ratio", "follow_bus_dist_behind_m", "follow_bus_speed_kmh",
    "n_active_buses_on_route", "n_buses_in_corridor_ahead",
    # (c) Recent Traversals by Preceding Buses (4 columns)
    "recent_corridor_tt_sum_sec", "recent_corridor_congestion_ratio",
    "recent_seg_coverage_ratio", "recent_next_seg_congestion_ratio",
    # (d) Historical Baseline Travel Time Matrix (9 columns)
    "baseline_eta_p50_sec", "baseline_eta_mean_sec", "baseline_eta_p10_sec",
    "baseline_eta_p90_sec", "baseline_eta_iqr_sec", "baseline_eta_rss_std_sec",
    "baseline_skew_sec", "baseline_max_seg_p90_sec", "baseline_tier0_frac",
    # (e) TomTom Traffic Incidents Ahead (6 columns)
    "inc_ahead_count", "inc_ahead_total_delay_sec", "inc_ahead_max_delay_sec",
    "inc_ahead_max_magnitude", "inc_ahead_jam_length_m", "inc_dist_to_nearest_m",
    # (f) Route Latent Profile & Physics Interactions (4 columns)
    "route_base_speed_kmh", "route_station_spacing_m",
    "physics_kinematic_eta_sec", "physics_probe_corrected_eta_sec",
]

INT32_COLS = [
    "current_station_order", "target_station_order", "route_id_idx", "direction_id",
    "day_type", "day_of_week", "hour_slot", "n_stations_ahead",
    "n_active_buses_on_route", "n_buses_in_corridor_ahead", "inc_ahead_count",
]


def select_representative_target_indices(k_curr: int, valid_arr_indices: List[int]) -> List[int]:
    """
    Selects up to 4 representative target station indices (> k_curr) covering:
      - Immediate next station (1 hop)
      - Short horizon (~4 hops)
      - Medium horizon (~10 hops)
      - Long horizon (~20 hops / final bracketed station)
    """
    ahead = [idx for idx in valid_arr_indices if idx > k_curr]
    if not ahead:
        return []
    if len(ahead) <= 4:
        return ahead

    chosen = {ahead[0], ahead[-1]}
    for target_offset in (4, 11, 20):
        target_k = k_curr + target_offset
        best_idx = min(ahead, key=lambda x: abs(x - target_k))
        chosen.add(best_idx)
    return sorted(chosen)


def _process_single_route(args: Tuple[Any, ...]) -> Tuple[str, int, int, float]:
    (
        r_code,
        r_id_idx,
        route_stations_by_dir,
        route_shape_len_by_dir,
        route_bm_cells_by_dir,
    ) = args
    t_start = time.time()

    r_tel_dir = os.path.join(SILVER_TEL_DIR, f"route_code={r_code}")
    if not os.path.exists(r_tel_dir):
        return (r_code, 0, 0, 0.0)

    tel_ds = ds_pa.dataset(r_tel_dir, format="parquet", partitioning="hive")
    tel_df = tel_ds.to_table(
        columns=["vehicle_id", "device_update_time", "device_epoch", "direction", "s_bus_m", "derived_speed_kmh"]
    ).to_pandas()
    if tel_df.empty:
        return (r_code, 0, 0, 0.0)

    tel_df["dt"] = tel_df["device_update_time"].str.slice(0, 10)
    tel_df = tel_df.sort_values(["direction", "vehicle_id", "device_epoch"]).reset_index(drop=True)

    # Load route TomTom incidents if partition exists
    inc_by_dir: Dict[str, List[Tuple[float, float, float, float, float, float, float]]] = {}
    r_inc_dir = os.path.join(SILVER_INC_DIR, f"route_code={r_code}")
    if os.path.exists(r_inc_dir):
        inc_ds = ds_pa.dataset(r_inc_dir, format="parquet")
        inc_df = inc_ds.to_table(
            columns=["direction", "t_start_epoch", "t_end_epoch", "s_min_m", "s_max_m", "delay_seconds", "magnitude_of_delay", "overlap_length_m"]
        ).to_pandas()
        if not inc_df.empty:
            inc_df = inc_df.sort_values(["direction", "t_start_epoch"]).reset_index(drop=True)
            for d_s, igrp in inc_df.groupby("direction", sort=False):
                inc_by_dir[str(d_s)] = list(
                    zip(
                        igrp["t_start_epoch"].astype(float).tolist(),
                        igrp["t_end_epoch"].astype(float).tolist(),
                        igrp["s_min_m"].astype(float).tolist(),
                        igrp["s_max_m"].astype(float).tolist(),
                        igrp["delay_seconds"].fillna(0.0).astype(float).tolist(),
                        igrp["magnitude_of_delay"].fillna(0.0).astype(float).tolist(),
                        igrp["overlap_length_m"].fillna(0.0).astype(float).tolist(),
                    )
                )

    route_rows: List[Tuple[Any, ...]] = []

    for d_str in ("go", "re"):
        st_list = route_stations_by_dir.get(d_str, [])
        m_st = len(st_list)
        if m_st < 3:
            continue

        rd_grp = tel_df[tel_df["direction"] == d_str]
        if rd_grp.empty:
            continue

        r_len = route_shape_len_by_dir.get(d_str, st_list[-1][3])
        dir_id = 0 if d_str == "go" else 1
        bm_cells = route_bm_cells_by_dir.get(d_str, {})

        # Compute route profile
        corridor_len = max(100.0, st_list[-1][3] - st_list[0][3])
        r_spacing_m = round(corridor_len / max(1, m_st - 1), 1)
        tot_d = sum(v[6] for v in bm_cells.values())
        tot_t = sum(v[0] for v in bm_cells.values())
        r_base_spd_kmh = round((tot_d / tot_t) * 3.6, 2) if tot_t > 0 else DEFAULT_URBAN_BUS_SPEED_KMPH
        base_spd_mps = r_base_spd_kmh / 3.6

        # Precompute O(1) prefix arrays per (day_type, hr_slot)
        n_seg = m_st - 1
        bm_arrays: Dict[Tuple[int, int], Dict[str, np.ndarray]] = {}
        for dt_v in (DAY_TYPE_WEEKDAY, DAY_TYPE_SATURDAY, DAY_TYPE_SUNDAY):
            for hr_v in range(BASELINE_MIN_HOUR_SLOT, BASELINE_MAX_HOUR_SLOT + 1):
                a_p50 = np.zeros(n_seg, dtype=np.float64)
                a_mean = np.zeros(n_seg, dtype=np.float64)
                a_p10 = np.zeros(n_seg, dtype=np.float64)
                a_p90 = np.zeros(n_seg, dtype=np.float64)
                a_var = np.zeros(n_seg, dtype=np.float64)
                a_t0 = np.zeros(n_seg, dtype=np.float64)
                a_len = np.zeros(n_seg, dtype=np.float64)

                for k in range(n_seg):
                    o_a = st_list[k][0]
                    o_b = st_list[k + 1][0]
                    s_len = max(15.0, st_list[k + 1][3] - st_list[k][3])
                    cell = bm_cells.get((o_a, o_b, dt_v, hr_v))
                    if cell:
                        p50, mean_v, p10, p90, std_v, q_t, _ = cell
                    else:
                        p50 = s_len / max(1.0, base_spd_mps)
                        mean_v, p10, p90, std_v, q_t = p50, p50 * 0.75, p50 * 1.35, p50 * 0.2, 3
                    a_p50[k] = p50
                    a_mean[k] = mean_v
                    a_p10[k] = p10
                    a_p90[k] = p90
                    a_var[k] = std_v * std_v
                    a_t0[k] = 1.0 if q_t == 0 else 0.0
                    a_len[k] = s_len

                bm_arrays[(dt_v, hr_v)] = {
                    "p50": a_p50,
                    "mean": a_mean,
                    "p10": a_p10,
                    "p90": a_p90,
                    "var": a_var,
                    "len": a_len,
                    "pref_p50": np.concatenate(([0.0], np.cumsum(a_p50))),
                    "pref_mean": np.concatenate(([0.0], np.cumsum(a_mean))),
                    "pref_p10": np.concatenate(([0.0], np.cumsum(a_p10))),
                    "pref_p90": np.concatenate(([0.0], np.cumsum(a_p90))),
                    "pref_var": np.concatenate(([0.0], np.cumsum(a_var))),
                    "pref_t0": np.concatenate(([0.0], np.cumsum(a_t0))),
                }

        st_orders = np.array([st[0] for st in st_list], dtype=np.int32)
        st_s_vals = np.array([st[3] for st in st_list], dtype=np.float64)
        ord_to_k = {int(st[0]): k for k, st in enumerate(st_list)}

        seg_completion_events: List[Tuple[float, int, float]] = []
        trip_ping_records: List[Tuple[Any, ...]] = []

        for vid, v_grp in rd_grp.groupby("vehicle_id", sort=False):
            pings_tuples = list(
                zip(
                    v_grp["dt"].tolist(),
                    v_grp["device_epoch"].tolist(),
                    v_grp["s_bus_m"].tolist(),
                    v_grp["derived_speed_kmh"].tolist(),
                )
            )
            trips = segment_trajectory_into_trips(
                pings_tuples, epoch_idx=1, s_idx=2, shape_len_m=r_len, trim_terminals=True
            )

            for tr in trips:
                arrivals = extract_bracketed_station_arrivals(tr, st_list, epoch_idx=1, s_idx=2)
                if len(arrivals) < 2:
                    continue

                for k in range(n_seg):
                    o_a = int(st_orders[k])
                    o_b = int(st_orders[k + 1])
                    if o_a in arrivals and o_b in arrivals:
                        tt_seg = arrivals[o_b] - arrivals[o_a]
                        seg_d = st_s_vals[k + 1] - st_s_vals[k]
                        if tt_seg > 0 and seg_d > 1.0:
                            spd_seg = (seg_d / tt_seg) * 3.6
                            if SEGMENT_MIN_SPEED_KMPH <= spd_seg <= SEGMENT_MAX_SPEED_KMPH:
                                seg_completion_events.append((float(arrivals[o_b]), k, float(tt_seg)))

                n_p = len(tr)
                tr_epochs = [float(p[1]) for p in tr]
                tr_s = np.maximum.accumulate([float(p[2]) for p in tr])
                tr_spd = [float(p[3]) if p[3] is not None and not pd.isna(p[3]) else r_base_spd_kmh for p in tr]

                valid_arr_k = sorted([ord_to_k[o] for o in arrivals.keys() if o in ord_to_k])
                if len(valid_arr_k) < 2:
                    continue

                first_arr_k = valid_arr_k[0]
                first_arr_t = arrivals[int(st_orders[first_arr_k])]
                last_sampled_s = -1e9

                for i_p in range(n_p):
                    s_cur = float(tr_s[i_p])
                    if s_cur < st_s_vals[0] or s_cur >= st_s_vals[-1] - 5.0:
                        continue
                    # Spatial stride deduplication: require >= 150m progress since last query point in same trip
                    if s_cur - last_sampled_s < MIN_EGO_SAMPLE_ADVANCE_M:
                        continue

                    t_cur = tr_epochs[i_p]
                    dt_str = tr[i_p][0]

                    k_curr = int(np.searchsorted(st_s_vals, s_cur, side="right")) - 1
                    k_curr = min(n_seg - 1, max(0, k_curr))

                    target_k_list = select_representative_target_indices(k_curr, valid_arr_k)
                    if not target_k_list:
                        continue

                    valid_targets: List[Tuple[int, float]] = []
                    for tk in target_k_list:
                        act_eta = arrivals[int(st_orders[tk])] - t_cur
                        if 5.0 <= act_eta <= 7200.0 and (st_s_vals[tk] - s_cur) >= 30.0:
                            valid_targets.append((tk, float(act_eta)))

                    if not valid_targets:
                        continue

                    last_sampled_s = s_cur

                    v_inst = max(0.0, tr_spd[i_p])
                    i_3 = max(0, i_p - 3)
                    dt_3 = t_cur - tr_epochs[i_3]
                    v_roll3 = min(80.0, max(0.0, ((s_cur - tr_s[i_3]) / dt_3) * 3.6 if dt_3 >= 10.0 else v_inst))

                    i_5 = max(0, i_p - 5)
                    dt_5 = t_cur - tr_epochs[i_5]
                    v_roll5 = min(80.0, max(0.0, ((s_cur - tr_s[i_5]) / dt_5) * 3.6 if dt_5 >= 15.0 else v_roll3))

                    dt_accel_min = max(0.5, dt_5 / 60.0) if dt_5 >= 15.0 else 1.0
                    ego_accel = (v_roll3 - v_roll5) / dt_accel_min
                    trip_elapsed = max(0.0, t_cur - tr_epochs[0])

                    trip_ping_records.append(
                        (
                            t_cur,
                            dt_str,
                            str(vid),
                            s_cur,
                            k_curr,
                            v_inst,
                            v_roll3,
                            v_roll5,
                            ego_accel,
                            trip_elapsed,
                            first_arr_k,
                            first_arr_t,
                            valid_targets,
                        )
                    )

        if not trip_ping_records:
            continue

        seg_completion_events.sort(key=lambda x: x[0])
        trip_ping_records.sort(key=lambda x: x[0])

        n_events = len(seg_completion_events)
        ev_idx = 0
        latest_seg_tt = np.full(n_seg, np.nan, dtype=np.float64)
        latest_seg_epoch = np.full(n_seg, -1e12, dtype=np.float64)

        active_fleet: Dict[str, Tuple[float, float, float, float]] = {}

        # Monotonic two-pointer state for TomTom incidents on (r_code, d_str)
        inc_list = inc_by_dir.get(d_str, [])
        n_inc = len(inc_list)
        inc_ptr = 0
        active_incidents: List[Tuple[float, float, float, float, float, float, float]] = []

        for (
            t_cur,
            dt_str,
            vid,
            s_cur,
            k_curr,
            v_inst,
            v_roll3,
            v_roll5,
            ego_accel,
            trip_elapsed,
            first_arr_k,
            first_arr_t,
            valid_targets,
        ) in trip_ping_records:
            # 1. Advance segment completion events up to t_cur
            while ev_idx < n_events and seg_completion_events[ev_idx][0] <= t_cur:
                ev_t, ev_k, ev_tt = seg_completion_events[ev_idx]
                latest_seg_tt[ev_k] = ev_tt
                latest_seg_epoch[ev_k] = ev_t
                ev_idx += 1

            # 2. Advance two-pointer TomTom incident window up to t_cur
            while inc_ptr < n_inc and inc_list[inc_ptr][0] <= t_cur:
                if inc_list[inc_ptr][1] >= t_cur:
                    active_incidents.append(inc_list[inc_ptr])
                inc_ptr += 1
            if active_incidents:
                active_incidents = [ep for ep in active_incidents if ep[1] >= t_cur]

            # 3. Calendar & Baseline arrays
            dt_obj = datetime.fromtimestamp(t_cur, tz=TZ_HANOI)
            wd = dt_obj.weekday()
            day_type = DAY_TYPE_WEEKDAY if wd < 5 else (DAY_TYPE_SATURDAY if wd == 5 else DAY_TYPE_SUNDAY)
            hr_slot = min(BASELINE_MAX_HOUR_SLOT, max(BASELINE_MIN_HOUR_SLOT, dt_obj.hour))
            hour_float = dt_obj.hour + dt_obj.minute / 60.0
            sin_t = math.sin(2.0 * math.pi * hour_float / 24.0)
            cos_t = math.cos(2.0 * math.pi * hour_float / 24.0)

            bm_slice = bm_arrays[(day_type, hr_slot)]
            a_p50 = bm_slice["p50"]
            a_p90 = bm_slice["p90"]
            a_len = bm_slice["len"]
            pref_p50 = bm_slice["pref_p50"]
            pref_mean = bm_slice["pref_mean"]
            pref_p10 = bm_slice["pref_p10"]
            pref_p90 = bm_slice["pref_p90"]
            pref_var = bm_slice["pref_var"]
            pref_t0 = bm_slice["pref_t0"]

            cur_seg_base_spd_kmh = (a_len[k_curr] / max(1.0, a_p50[k_curr])) * 3.6
            ego_spd_ratio = min(3.0, max(0.1, v_roll3 / max(3.0, cur_seg_base_spd_kmh)))

            if k_curr > first_arr_k and t_cur > first_arr_t:
                ego_cum_delay = max(-600.0, min(1800.0, (t_cur - first_arr_t) - float(pref_p50[k_curr] - pref_p50[first_arr_k])))
            else:
                ego_cum_delay = 0.0

            # 4. Same-route Fleet Ahead & Behind (b)
            stale_vids = [v_k for v_k, v_val in active_fleet.items() if t_cur - v_val[0] > FLEET_ACTIVE_WINDOW_SEC]
            for sv in stale_vids:
                del active_fleet[sv]

            lead_dist = 25000.0
            lead_spd = r_base_spd_kmh
            lead_ratio = 1.0
            follow_dist = 25000.0
            follow_spd = r_base_spd_kmh
            other_ahead_s: List[float] = []

            for other_vid, (o_t, o_s, o_spd, o_rat) in active_fleet.items():
                if other_vid == vid:
                    continue
                ds_fleet = o_s - s_cur
                if ds_fleet > 20.0:
                    other_ahead_s.append(o_s)
                    if ds_fleet < lead_dist:
                        lead_dist = ds_fleet
                        lead_spd = o_spd
                        lead_ratio = o_rat
                elif ds_fleet < -20.0:
                    db_fleet = -ds_fleet
                    if db_fleet < follow_dist:
                        follow_dist = db_fleet
                        follow_spd = o_spd

            active_fleet[vid] = (t_cur, s_cur, v_roll3, ego_spd_ratio)
            n_active_route = len(active_fleet)
            lead_headway_sec = min(3600.0, lead_dist / max(1.5, v_roll3 / 3.6))

            dist_to_next_st = max(0.0, float(st_s_vals[k_curr + 1] - s_cur))
            alpha_curr = min(1.0, max(0.0, dist_to_next_st / a_len[k_curr]))

            # 5. Vectorized O(1) prefix sum for Recent Preceding-Bus Probe (c) at t_cur
            fresh_mask = ((t_cur - latest_seg_epoch) <= RECENT_PROBE_WINDOW_SEC) & (~np.isnan(latest_seg_tt))
            eff_rec_seg = np.where(fresh_mask, latest_seg_tt, a_p50)
            pref_rec_tt = np.concatenate(([0.0], np.cumsum(eff_rec_seg)))
            pref_rec_cov = np.concatenate(([0], np.cumsum(fresh_mask.astype(np.int32))))

            next_seg_probe_ratio = min(3.5, max(0.3, float(eff_rec_seg[k_curr] / max(1.0, a_p50[k_curr]))))
            eff_ego_mps = max(2.0, min(18.0, (0.6 * v_roll3 + 0.4 * r_base_spd_kmh) / 3.6))

            for tk, actual_eta in valid_targets:
                s_target = float(st_s_vals[tk])
                rem_dist = s_target - s_cur
                n_hops = tk - k_curr

                # (d) O(1) Historical Baseline features
                base_p50 = float(alpha_curr * a_p50[k_curr] + (pref_p50[tk] - pref_p50[k_curr + 1]))
                base_mean = float(alpha_curr * bm_slice["mean"][k_curr] + (pref_mean[tk] - pref_mean[k_curr + 1]))
                base_p10 = float(alpha_curr * bm_slice["p10"][k_curr] + (pref_p10[tk] - pref_p10[k_curr + 1]))
                base_p90 = float(alpha_curr * a_p90[k_curr] + (pref_p90[tk] - pref_p90[k_curr + 1]))
                base_iqr = max(1.0, base_p90 - base_p10)
                base_var = float((alpha_curr ** 2) * bm_slice["var"][k_curr] + (pref_var[tk] - pref_var[k_curr + 1]))
                base_rss_std = math.sqrt(max(1.0, base_var))
                base_skew = base_mean - base_p50
                max_seg_p90 = float(np.max(a_p90[k_curr:tk]))
                t0_frac = float((pref_t0[tk] - pref_t0[k_curr]) / max(1, n_hops))

                # (c) O(1) Recent Preceding-Bus Probe features
                rec_tt_sum = float(alpha_curr * eff_rec_seg[k_curr] + (pref_rec_tt[tk] - pref_rec_tt[k_curr + 1]))
                rec_cov_cnt = int(pref_rec_cov[tk] - pref_rec_cov[k_curr])
                rec_cong_ratio = min(3.5, max(0.3, rec_tt_sum / max(1.0, base_p50)))
                rec_cov_ratio = rec_cov_cnt / max(1, n_hops)

                n_buses_corridor = sum(1 for os_v in other_ahead_s if os_v <= s_target)

                # (e) Check active TomTom incidents overlapping [s_cur, s_target]
                inc_cnt = 0
                inc_tot_delay = 0.0
                inc_max_delay = 0.0
                inc_max_mag = 0.0
                inc_jam_len = 0.0
                inc_near_dist = 25000.0
                if active_incidents:
                    for _, _, ep_s0, ep_s1, ep_del, ep_mag, _ in active_incidents:
                        ov_s0 = max(s_cur, ep_s0)
                        ov_s1 = min(s_target, ep_s1)
                        ov_l = ov_s1 - ov_s0
                        if ov_l >= 0.0:
                            inc_cnt += 1
                            span_l = max(20.0, ep_s1 - ep_s0)
                            frac = min(1.0, max(0.1, ov_l / span_l))
                            inc_tot_delay += ep_del * frac
                            if ep_del > inc_max_delay:
                                inc_max_delay = ep_del
                            if ep_mag > inc_max_mag:
                                inc_max_mag = ep_mag
                            inc_jam_len += ov_l
                            d_near = max(0.0, ep_s0 - s_cur)
                            if d_near < inc_near_dist:
                                inc_near_dist = d_near

                # (f) Physics-guided interaction features (Shrinkage Probe + Decaying Ego Speed + Incident Delay)
                phys_kin_eta = min(7200.0, rem_dist / eff_ego_mps)
                w_probe = 0.35 * rec_cov_ratio
                w_ego = 0.20 * math.exp(-rem_dist / 2500.0)
                ego_delay_factor = min(1.35, max(0.70, 1.0 / ego_spd_ratio))
                phys_probe_eta = (
                    base_p50 * ((1.0 - w_probe - w_ego) + w_probe * rec_cong_ratio + w_ego * ego_delay_factor)
                    + min(180.0, 0.25 * inc_tot_delay)
                )

                route_rows.append(
                    (
                        r_code,
                        d_str,
                        dt_str,
                        vid,
                        round(t_cur, 1),
                        int(st_orders[k_curr]),
                        int(st_orders[tk]),
                        round(actual_eta, 2),
                        # (a)
                        int(r_id_idx),
                        int(dir_id),
                        int(day_type),
                        int(wd),
                        int(hr_slot),
                        round(sin_t, 4),
                        round(cos_t, 4),
                        round(s_cur, 1),
                        round(s_target, 1),
                        round(rem_dist, 1),
                        int(n_hops),
                        round(s_cur / max(1.0, r_len), 4),
                        round(s_target / max(1.0, r_len), 4),
                        round(dist_to_next_st, 1),
                        round(v_inst, 2),
                        round(v_roll3, 2),
                        round(v_roll5, 2),
                        round(ego_accel, 2),
                        round(ego_spd_ratio, 3),
                        round(trip_elapsed, 1),
                        round(ego_cum_delay, 1),
                        # (b)
                        round(lead_dist, 1),
                        round(lead_headway_sec, 1),
                        round(lead_spd, 2),
                        round(lead_ratio, 3),
                        round(follow_dist, 1),
                        round(follow_spd, 2),
                        int(n_active_route),
                        int(n_buses_corridor),
                        # (c)
                        round(rec_tt_sum, 2),
                        round(rec_cong_ratio, 3),
                        round(rec_cov_ratio, 3),
                        round(next_seg_probe_ratio, 3),
                        # (d)
                        round(base_p50, 2),
                        round(base_mean, 2),
                        round(base_p10, 2),
                        round(base_p90, 2),
                        round(base_iqr, 2),
                        round(base_rss_std, 2),
                        round(base_skew, 2),
                        round(max_seg_p90, 2),
                        round(t0_frac, 3),
                        # (e)
                        int(inc_cnt),
                        round(inc_tot_delay, 1),
                        round(inc_max_delay, 1),
                        round(inc_max_mag, 1),
                        round(inc_jam_len, 1),
                        round(inc_near_dist, 1),
                        # (f)
                        float(r_base_spd_kmh),
                        float(r_spacing_m),
                        round(phys_kin_eta, 2),
                        round(phys_probe_eta, 2),
                    )
                )

    if not route_rows:
        return (r_code, 0, 0, round(time.time() - t_start, 2))

    df_r = pd.DataFrame(route_rows, columns=FEATURE_COLUMNS)
    for col in FEATURE_COLUMNS[5:]:
        if col in INT32_COLS:
            df_r[col] = df_r[col].astype(np.int32)
        else:
            df_r[col] = df_r[col].astype(np.float32)

    df_tr = df_r[df_r["dt"] <= TRAIN_SPLIT_END_DATE]
    df_te = df_r[df_r["dt"] >= TEST_SPLIT_START_DATE]

    tr_out_dir = os.path.join(GOLD_FEATURE_DIR, "split=train", f"route_code={r_code}")
    te_out_dir = os.path.join(GOLD_FEATURE_DIR, "split=test", f"route_code={r_code}")

    if not df_tr.empty:
        os.makedirs(tr_out_dir, exist_ok=True)
        df_tr.to_parquet(os.path.join(tr_out_dir, "part-00000.snappy.parquet"), engine="pyarrow", compression="snappy", index=False)
    if not df_te.empty:
        os.makedirs(te_out_dir, exist_ok=True)
        df_te.to_parquet(os.path.join(te_out_dir, "part-00000.snappy.parquet"), engine="pyarrow", compression="snappy", index=False)

    return (r_code, len(df_tr), len(df_te), round(time.time() - t_start, 2))


def build_gold_feature_store(max_workers: int = 8) -> Dict[str, Any]:
    t0 = time.time()
    print("=" * 96, flush=True)
    print("STEP 3.3: UNIFIED GOLD FEATURE STORE EXTRACTOR (PARALLEL MULTI-CORE O(1) ENGINE)", flush=True)
    print(f"Target Directory: {GOLD_FEATURE_DIR} | Workers: {max_workers}", flush=True)
    print("=" * 96, flush=True)

    if os.path.exists(GOLD_FEATURE_DIR):
        shutil.rmtree(GOLD_FEATURE_DIR, ignore_errors=True)
    os.makedirs(os.path.join(GOLD_FEATURE_DIR, "split=train"), exist_ok=True)
    os.makedirs(os.path.join(GOLD_FEATURE_DIR, "split=test"), exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    shape_rows = cur.execute(
        "SELECT route_code, direction, MAX(cum_distance_m) FROM canonical_shape_master GROUP BY route_code, direction"
    ).fetchall()
    shape_len_by_route: Dict[str, Dict[str, float]] = defaultdict(dict)
    for r, d, l in shape_rows:
        shape_len_by_route[str(r)][str(d)] = float(l)

    st_rows = cur.execute(
        """
        SELECT route_code, direction, station_order, station_id, station_name, cum_distance_m
        FROM canonical_station_master
        ORDER BY route_code, direction, station_order
        """
    ).fetchall()
    raw_st_map: Dict[Tuple[str, str], List[Tuple[int, int, str, float]]] = defaultdict(list)
    for r_code, d_str, st_ord, st_id, st_name, s_m in st_rows:
        raw_st_map[(str(r_code), str(d_str))].append((int(st_ord), int(st_id), str(st_name), float(s_m)))

    stations_by_route: Dict[str, Dict[str, List[Tuple[int, int, str, float]]]] = defaultdict(dict)
    for (r_c, d_s), st_list in raw_st_map.items():
        stations_by_route[r_c][d_s] = get_active_corridor_stations(st_list)

    bm_rows = cur.execute(
        """
        SELECT route_code, direction, from_station_order, to_station_order,
               day_type, hour_slot, sample_count, quality_tier,
               tt_p10_sec, tt_p50_sec, tt_p90_sec, tt_mean_sec, tt_std_sec, segment_length_m
        FROM agg_segment_travel_times
        """
    ).fetchall()
    conn.close()

    bm_by_route: Dict[str, Dict[str, Dict[Tuple[int, int, int, int], Tuple[float, float, float, float, float, int, float]]]] = defaultdict(lambda: defaultdict(dict))
    for r_c, d_s, o_a, o_b, dt_v, hr_v, n_cnt, q_t, p10, p50, p90, mean_v, std_v, seg_l in bm_rows:
        bm_by_route[str(r_c)][str(d_s)][(int(o_a), int(o_b), int(dt_v), int(hr_v))] = (
            float(p50), float(mean_v), float(p10), float(p90), float(std_v), int(q_t), float(seg_l)
        )

    active_routes = sorted(bm_by_route.keys())
    tasks = []
    for idx, r_code in enumerate(active_routes):
        tasks.append(
            (
                r_code,
                idx,
                stations_by_route[r_code],
                shape_len_by_route[r_code],
                bm_by_route[r_code],
            )
        )

    total_train = 0
    total_test = 0
    completed = 0

    with ProcessPoolExecutor(max_workers=max_workers, initializer=initialize_storage_paths,
                             initargs=(DB_PATH, SILVER_TEL_DIR, SILVER_INC_DIR, GOLD_FEATURE_DIR)) as pool:
        futures = {pool.submit(_process_single_route, t): t[0] for t in tasks}
        for fut in as_completed(futures):
            r_c, n_tr, n_te, el_s = fut.result()
            total_train += n_tr
            total_test += n_te
            completed += 1
            if completed % 8 == 0 or completed == len(tasks):
                print(
                    f"  [Parallel Feature Store {completed:>2}/{len(tasks)}] Latest Route {r_c:<5} ({el_s:>4.1f}s) | "
                    f"Accumulated Train: {total_train:>9,} | Test: {total_test:>9,} | Wall Elapsed: {time.time()-t0:>5.1f}s",
                    flush=True,
                )

    print("=" * 96, flush=True)
    print(
        f"[COMPLETE] GOLD FEATURE STORE: {total_train + total_test:,} rows x {len(FEATURE_COLUMNS)} columns "
        f"(Train: {total_train:,} | Test: {total_test:,}) across {len(tasks)} routes in {time.time()-t0:.2f}s!",
        flush=True,
    )
    print("=" * 96, flush=True)

    return {
        "train_rows": total_train,
        "test_rows": total_test,
        "n_columns": len(FEATURE_COLUMNS),
        "elapsed_sec": round(time.time() - t0, 2),
    }


if __name__ == "__main__":
    build_gold_feature_store()
