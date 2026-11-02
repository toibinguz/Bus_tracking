"""
Module 3: Bus ETA Prediction Engine
Subcomponent: step_3_2_feature_store_extractor
File: feature_extractor.py

Extracts supervised machine learning training features (X) and ground truth target (Y)
with zero trip-level data leakage, combining:
  1. Historical Statistical Priors from Module 3.1 (agg_segment_travel_times)
  2. Multi-Ping Ego-Vehicle Kinematics & Realized Trip Pace (last 1, 2, 3 pings, 3m/10m rolling speed, acceleration trend, recent segment pace ratio)
  3. Downstream Leader ("Probe Vehicle") Real-Time Segment Traversals & Live Corridor Speed
  4. Same-Route Fleet Headway & Bus Bunching Dynamics (distance to leader/follower, time headway since previous bus)
  5. Multi-Source TomTom Incident Fusion (WP 2.1 segment-by-segment accumulation)
  6. Two-Stage Decoupled Feature Architecture (WP 2.2):
     - Stage 1: Immutable Physical Kinematic Horizon Observations (partitioned by dt=YYYY-MM-DD in Parquet)
     - Stage 2: Dynamic Weekly Matrix Re-binding (bind_stage2_dynamic_matrix) in <1s/route via vectorized NumPy lookup
"""

import bisect
import glob
import math
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple

import numpy as np
import pandas as pd
import pyarrow.dataset as ds_pa

# Ensure project root in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))
sys.path.insert(0, os.path.abspath("."))

from config.system_config import DEFAULT_DB_PATH, DEFAULT_LAKEHOUSE_ROOT, get_database_path
from module_3_bus_eta_prediction.step_3_1_historical_baseline_model.baseline_segment_average import (
    DAY_TYPES,
    TIME_WINDOWS,
    get_day_type,
    get_time_window,
)

# Canonical 24 High-Signal Features optimized for Data-Rich Golden Demo Routes (>400k samples/route)
FEATURE_COLUMNS: List[str] = [
    # 1. Historical Matrix Priors from Module 3.1 (4 features)
    "baseline_median_sec",
    "baseline_p90_sec",
    "baseline_spread_sec",
    "baseline_std_sec",
    # 2. Ego-Vehicle Multi-Ping Live Kinematics & Realized Trip Pace (8 features)
    "ego_recent_pace_ratio",
    "speed_vs_baseline_ratio",
    "rolling_speed_180s_kmh",
    "rolling_speed_600s_kmh",
    "v_last_1_ping_kmh",
    "v_last_2_ping_kmh",
    "is_dwell",
    "current_dwell_sec",
    "dwell_ratio_300s",
    # 3. Same-Route Fleet Interaction: Leader Probe & Headway/Bunching (6 features)
    "leader_expected_eta_sec",
    "leader_pace_ratio",
    "leader_info_age_sec",
    "dist_to_leader_m",
    "leader_live_speed_kmh",
    "dist_to_follower_m",
    "headway_to_leader_sec",
    # 4. Spatial Geometry & Route Topology (4 features)
    "target_station_order",
    "s_bus_m",
    "distance_remaining_m",
    "dist_to_next_stop_m",
    "stops_ahead",
    # 5. Direction & Temporal Regime (3 features)
    "direction_encoded",
    "hour",
    "is_weekend",
]

# 6. Multi-Source TomTom Incidents (v2.0 Apache & TomTom Fusion - 3 features)
TOMTOM_FEATURE_COLUMNS: List[str] = [
    "tomtom_has_incident",
    "tomtom_delay_sec",
    "tomtom_magnitude",
]

# V2.0 Full Feature Set with Multi-Source Incident Fusion (27 features)
V2_FEATURE_COLUMNS: List[str] = FEATURE_COLUMNS + TOMTOM_FEATURE_COLUMNS

TARGET_COLUMN: str = "actual_remaining_sec"

TIME_WINDOW_INDEX: Dict[str, int] = {w: i for i, w in enumerate(TIME_WINDOWS)}
DAY_TYPE_INDEX: Dict[str, int] = {d: i for i, d in enumerate(DAY_TYPES)}


def _load_route_baseline_matrix(
    conn: sqlite3.Connection, route_code: str
) -> Dict[Tuple[str, int, str, str], Tuple[float, float, float, float, float]]:
    """
    Load Module 3.1 historical baseline travel time matrix for a route.
    Returns dict mapping (direction, from_station_order, time_window, day_type)
    -> (median_sec, std_sec, p10_sec, p90_sec, commercial_speed_kmh).
    """
    cur = conn.cursor()
    cur.execute(
        """
        SELECT direction, from_station_order, time_window, day_type,
               median_transit_sec, std_transit_sec, p10_transit_sec,
               p90_transit_sec, commercial_speed_kmh
        FROM agg_segment_travel_times
        WHERE route_code = ?
        """,
        (route_code,),
    )
    matrix: Dict[Tuple[str, int, str, str], Tuple[float, float, float, float, float]] = {}
    for d, st_from, win, dtype, med, std, p10, p90, spd in cur.fetchall():
        matrix[(d, int(st_from), str(win), str(dtype))] = (
            float(med),
            float(std or 0.0),
            float(p10),
            float(p90),
            float(spd or 16.0),
        )
    return matrix


def _compute_valid_reach_indices(
    epochs: List[float],
    s_vals: List[float],
    max_gap_s: float = 300.0,
    max_stall_s: float = 300.0,
    stall_dist_m: float = 40.0,
) -> List[int]:
    """
    For each ping index i in a trip, compute the furthest downstream ping index
    reachable without encountering a telemetry blackout (> max_gap_s) or a
    mid-route layover/staging event (dt >= max_stall_s with ds < stall_dist_m).
    """
    n = len(epochs)
    bad_start = [n] * n

    for a in range(n - 1):
        if epochs[a + 1] - epochs[a] > max_gap_s:
            bad_start[a] = a
            continue
        for b in range(a + 1, n):
            dt = epochs[b] - epochs[a]
            ds = s_vals[b] - s_vals[a]
            if ds >= stall_dist_m:
                break
            if dt >= max_stall_s:
                bad_start[a] = b - 1
                break

    max_reach = [n - 1] * n
    curr_limit = n - 1
    for i in range(n - 1, -1, -1):
        if bad_start[i] < curr_limit:
            curr_limit = bad_start[i]
        max_reach[i] = curr_limit
    return max_reach


def extract_route_training_dataset(
    route_code: str,
    db_path: Optional[str] = None,
    max_stops_ahead: int = 5,
    max_horizon_m: float = 3500.0,
    include_tomtom: bool = False,
    target_dates: Optional[Set[str]] = None,
    lakehouse_root: str = DEFAULT_LAKEHOUSE_ROOT,
) -> pd.DataFrame:
    """
    Extract supervised training dataset for point and interval ETA prediction.
    Computes strictly causal (t <= t_ping) multi-ping ego kinematics, downstream
    leader segment traversal times, and spatial/temporal headway to leader & follower buses.
    Optionally joins TomTom incident signals (WP 2.1) when include_tomtom=True.
    When target_dates (set of 'YYYY-MM-DD' strings) is provided, only emits samples
    for pings occurring on those dates while preserving causal fleet lookback.
    Also records Stage 1 physical decoupling columns so Stage 2 dynamic weekly
    matrix re-binding (bind_stage2_dynamic_matrix) executes in <1s/route.
    """
    resolved_db = db_path or str(get_database_path())
    conn = sqlite3.connect(resolved_db)
    cur = conn.cursor()

    # 1. Load canonical stations per direction
    cur.execute(
        """
        SELECT direction, station_order, station_name, cum_distance_m
        FROM canonical_station_master
        WHERE route_code = ?
        ORDER BY direction, station_order ASC
        """,
        (route_code,),
    )
    stations_by_dir: Dict[str, List[Tuple[int, str, float]]] = {}
    for d, st_order, st_name, cum_d in cur.fetchall():
        stations_by_dir.setdefault(str(d), []).append(
            (int(st_order), str(st_name), float(cum_d))
        )

    if not stations_by_dir:
        conn.close()
        return pd.DataFrame()

    # 2. Load Module 3.1 Baseline Matrix priors
    baseline_matrix = _load_route_baseline_matrix(conn, route_code)

    # 2.1 Load TomTom incident episodes per station segment into 10-minute buckets (WP 2.1)
    # Prefer Silver Parquet partition if available to avoid SQLite contention across parallel workers
    tomtom_seg_buckets: Dict[str, Dict[int, Dict[int, List[Tuple[int, int, float, float, float, int]]]]] = {
        d: {} for d in stations_by_dir
    }
    if include_tomtom:
        silver_inc_file = os.path.join(
            lakehouse_root, "silver", "fact_route_tomtom_incidents",
            f"route_code={route_code}", "part-00000.snappy.parquet"
        )
        if os.path.exists(silver_inc_file):
            tbl_inc = ds_pa.dataset(silver_inc_file, format="parquet").to_table(
                columns=[
                    "direction", "from_station_order", "s_min_m", "s_max_m",
                    "t_start_epoch", "t_end_epoch", "delay_seconds", "magnitude_of_delay",
                ],
                filter=ds_pa.field("delay_seconds") > 0,
            )
            inc_rows = list(
                zip(
                    tbl_inc["direction"].to_pylist(),
                    tbl_inc["from_station_order"].to_pylist(),
                    tbl_inc["s_min_m"].to_pylist(),
                    tbl_inc["s_max_m"].to_pylist(),
                    tbl_inc["t_start_epoch"].to_pylist(),
                    tbl_inc["t_end_epoch"].to_pylist(),
                    tbl_inc["delay_seconds"].to_pylist(),
                    tbl_inc["magnitude_of_delay"].to_pylist(),
                )
            )
        else:
            cur.execute(
                """
                SELECT direction, from_station_order,
                       s_min_m, s_max_m,
                       t_start_epoch, t_end_epoch,
                       delay_seconds, magnitude_of_delay
                FROM fact_route_tomtom_incidents
                WHERE route_code = ? AND delay_seconds > 0
                """,
                (route_code,),
            )
            inc_rows = cur.fetchall()

        for d_dir, st_from_order, s_min_i, s_max_i, t_s, t_e, del_s, mag_d in inc_rows:
            d_str = str(d_dir)
            if d_str not in tomtom_seg_buckets:
                continue
            st_buckets = tomtom_seg_buckets[d_str].setdefault(int(st_from_order), {})
            b_start_i = int(t_s // 600)
            b_end_i = int(t_e // 600)
            inc_tuple = (
                int(t_s),
                int(t_e),
                float(s_min_i),
                float(s_max_i),
                float(del_s or 0.0),
                int(mag_d or 0),
            )
            for b_i in range(b_start_i, b_end_i + 1):
                st_buckets.setdefault(b_i, []).append(inc_tuple)

    # 3. Fetch on-corridor projected telemetry (d_perp <= 35.0m per Doc 54)
    # Prefer Silver Parquet partitions (9.58x faster + zero SQLite lock contention in ProcessPoolExecutor)
    silver_tel_route_dir = os.path.join(
        lakehouse_root, "silver", "route_projected_telemetry", f"route_code={route_code}"
    )
    silver_tel_files = sorted(glob.glob(os.path.join(silver_tel_route_dir, "dt=*", "*.parquet")))
    expanded_dates: Optional[Set[str]] = None
    if target_dates:
        expanded_dates = set()
        for d_s in target_dates:
            try:
                d_obj = datetime.strptime(d_s, "%Y-%m-%d")
                expanded_dates.add((d_obj - timedelta(days=1)).strftime("%Y-%m-%d"))
                expanded_dates.add(d_s)
                expanded_dates.add((d_obj + timedelta(days=1)).strftime("%Y-%m-%d"))
            except ValueError:
                expanded_dates.add(d_s)
        min_date_q = min(expanded_dates)
        max_date_q = max(expanded_dates)
    else:
        min_date_q = None
        max_date_q = None

    if silver_tel_files:
        conn.close()
        if expanded_dates is not None:
            silver_tel_files = [
                fp for fp in silver_tel_files
                if os.path.basename(os.path.dirname(fp)).replace("dt=", "") in expanded_dates
            ]
        if not silver_tel_files:
            return pd.DataFrame()
        tbl_tel = ds_pa.dataset(silver_tel_files, format="parquet").to_table(
            columns=[
                "ping_id", "vehicle_id", "direction", "device_epoch", "device_update_time",
                "s_bus_m", "cross_track_m", "derived_speed_kmh", "is_dwell",
            ],
            filter=ds_pa.field("cross_track_m") <= 35.0,
            use_threads=True,
        )
        df_tel = tbl_tel.to_pandas().sort_values(
            ["direction", "vehicle_id", "device_epoch"], kind="mergesort"
        )
        raw_rows = list(
            zip(
                df_tel["ping_id"].tolist(),
                df_tel["vehicle_id"].tolist(),
                df_tel["direction"].tolist(),
                df_tel["device_epoch"].tolist(),
                df_tel["device_update_time"].tolist(),
                df_tel["s_bus_m"].tolist(),
                df_tel["cross_track_m"].tolist(),
                df_tel["derived_speed_kmh"].tolist(),
                df_tel["is_dwell"].tolist(),
            )
        )
    else:
        if min_date_q and max_date_q:
            cur.execute(
                """
                SELECT ping_id, vehicle_id, direction, device_epoch, device_update_time,
                       s_bus_m, cross_track_m, derived_speed_kmh, is_dwell
                FROM route_projected_telemetry
                WHERE route_code = ?
                  AND cross_track_m <= 35.0
                  AND substr(device_update_time, 1, 10) >= ?
                  AND substr(device_update_time, 1, 10) <= ?
                ORDER BY direction, vehicle_id, device_epoch ASC
                """,
                (route_code, min_date_q, max_date_q),
            )
        else:
            cur.execute(
                """
                SELECT ping_id, vehicle_id, direction, device_epoch, device_update_time,
                       s_bus_m, cross_track_m, derived_speed_kmh, is_dwell
                FROM route_projected_telemetry
                WHERE route_code = ?
                  AND cross_track_m <= 35.0
                ORDER BY direction, vehicle_id, device_epoch ASC
                """,
                (route_code,),
            )
        raw_rows = cur.fetchall()
        conn.close()

    if not raw_rows:
        return pd.DataFrame()

    # Group pings by (direction, vehicle_id)
    pings_by_veh: Dict[Tuple[str, int], List[tuple]] = {}
    for row in raw_rows:
        d = str(row[2])
        vid = int(row[1])
        pings_by_veh.setdefault((d, vid), []).append(row)

    # 4. Segment into monotonic forward trips across all vehicles and directions
    raw_trips: List[Tuple[float, str, int, List[tuple]]] = []
    for (direction, vid), p_list in pings_by_veh.items():
        if direction not in stations_by_dir or len(stations_by_dir[direction]) < 2:
            continue

        curr_trip = [p_list[0]]
        max_s = float(p_list[0][5])

        for p in p_list[1:]:
            dt = float(p[3]) - float(curr_trip[-1][3])
            ds = float(p[5]) - float(curr_trip[-1][5])
            if dt > 600.0 or ds < -100.0 or float(p[5]) < max_s - 300.0:
                if len(curr_trip) >= 5:
                    raw_trips.append((float(curr_trip[0][3]), direction, vid, curr_trip))
                curr_trip = [p]
                max_s = float(p[5])
            else:
                curr_trip.append(p)
                if float(p[5]) > max_s:
                    max_s = float(p[5])

        if len(curr_trip) >= 5:
            raw_trips.append((float(curr_trip[0][3]), direction, vid, curr_trip))

    # Sort all trips chronologically by start epoch
    raw_trips.sort(key=lambda x: x[0])

    # -------------------------------------------------------------------------
    # 5. Pre-pass: Build Trip Kinematics + Fleet Index + Segment Traversal Logs
    # -------------------------------------------------------------------------
    seg_traversal_history: Dict[str, Dict[int, List[Tuple[float, float, int]]]] = {
        d: {} for d in stations_by_dir
    }
    station_pass_history: Dict[str, Dict[int, List[Tuple[float, int]]]] = {
        d: {} for d in stations_by_dir
    }
    time_buckets: Dict[str, Dict[int, List[int]]] = {d: {} for d in stations_by_dir}

    processed_trips: List[dict] = []

    for trip_idx_raw, (_, direction, vid, trip) in enumerate(raw_trips):
        stations = stations_by_dir[direction]
        st_orders = [s[0] for s in stations]
        st_dists = [s[2] for s in stations]
        n_stations = len(stations)

        n_pings = len(trip)
        epochs = [float(p[3]) for p in trip]
        s_vals = [float(p[5]) for p in trip]

        # Interpolate exact station crossing times
        crossings: Dict[int, Tuple[float, int]] = {}
        search_start = 0
        for k in range(n_stations):
            s_target = st_dists[k]
            for i in range(search_start, n_pings - 1):
                tA, sA = epochs[i], s_vals[i]
                tB, sB = epochs[i + 1], s_vals[i + 1]
                if sA <= s_target <= sB and (tB - tA) <= 180.0:
                    if sB - sA > 1.0:
                        ratio = (s_target - sA) / (sB - sA)
                        t_cross = tA + ratio * (tB - tA)
                    else:
                        t_cross = (tA + tB) / 2.0
                    crossings[k] = (t_cross, i)
                    search_start = i
                    break

        if not crossings:
            continue

        max_reach = _compute_valid_reach_indices(epochs, s_vals)

        step_speeds = [0.0] * n_pings
        for i in range(n_pings):
            if i > 0 and (epochs[i] - epochs[i - 1]) > 0.5:
                spd = ((s_vals[i] - s_vals[i - 1]) / (epochs[i] - epochs[i - 1])) * 3.6
                step_speeds[i] = max(0.0, min(65.0, spd))
            else:
                step_speeds[i] = max(0.0, min(65.0, float(trip[i][7] or 0.0)))

        rolling_180 = [0.0] * n_pings
        rolling_600 = [0.0] * n_pings
        dwell_durations = [0.0] * n_pings
        dwell_ratios_300 = [0.0] * n_pings

        for i in range(n_pings):
            t_now = epochs[i]
            s_now = s_vals[i]

            j180 = i
            while j180 > 0 and (t_now - epochs[j180 - 1]) <= 180.0:
                j180 -= 1
            dt180 = t_now - epochs[j180]
            ds180 = max(0.0, s_now - s_vals[j180])
            rolling_180[i] = (
                min(65.0, (ds180 / dt180) * 3.6) if dt180 >= 15.0 else step_speeds[i]
            )

            j600 = i
            while j600 > 0 and (t_now - epochs[j600 - 1]) <= 600.0:
                j600 -= 1
            dt600 = t_now - epochs[j600]
            ds600 = max(0.0, s_now - s_vals[j600])
            rolling_600[i] = (
                min(65.0, (ds600 / dt600) * 3.6)
                if dt600 >= 30.0
                else rolling_180[i]
            )

            d_idx = i
            while d_idx > 0 and abs(s_now - s_vals[d_idx - 1]) < 15.0:
                d_idx -= 1
            dwell_durations[i] = max(0.0, t_now - epochs[d_idx])

            j300 = i
            dwell_sec_300 = 0.0
            while j300 > 0 and (t_now - epochs[j300 - 1]) <= 300.0:
                step_dt = epochs[j300] - epochs[j300 - 1]
                step_ds = abs(s_vals[j300] - s_vals[j300 - 1])
                if step_ds < 15.0 or int(trip[j300][8] or 0) == 1:
                    dwell_sec_300 += step_dt
                j300 -= 1
            tot_dt300 = t_now - epochs[j300]
            dwell_ratios_300[i] = (
                min(1.0, dwell_sec_300 / tot_dt300) if tot_dt300 >= 15.0 else 0.0
            )

        t_idx = len(processed_trips)
        # Deterministic trip_id anchored on start epoch so incremental and full runs match
        trip_id = f"{route_code}_{direction}_{vid}_{int(epochs[0])}"

        for k, (t_c, _) in crossings.items():
            station_pass_history[direction].setdefault(k, []).append((t_c, t_idx))

        for k in range(n_stations - 1):
            if k in crossings and (k + 1) in crossings:
                t1, idx1 = crossings[k]
                t2, idx2 = crossings[k + 1]
                dt_seg = t2 - t1
                seg_dist = max(10.0, st_dists[k + 1] - st_dists[k])
                spd_seg = (seg_dist / dt_seg) * 3.6 if dt_seg > 0 else 0.0
                if (
                    5.0 <= dt_seg <= 1800.0
                    and 2.0 <= spd_seg <= 75.0
                    and idx2 >= idx1
                    and idx2 + 1 <= max_reach[idx1]
                ):
                    seg_traversal_history[direction].setdefault(k, []).append(
                        (t2, dt_seg, t_idx)
                    )

        b_start = int((epochs[0] - 180.0) // 600.0)
        b_end = int((epochs[-1] + 180.0) // 600.0)
        for b in range(b_start, b_end + 1):
            time_buckets[direction].setdefault(b, []).append(t_idx)

        processed_trips.append(
            {
                "t_idx": t_idx,
                "trip_id": trip_id,
                "direction": direction,
                "vid": vid,
                "trip": trip,
                "epochs": epochs,
                "s_vals": s_vals,
                "crossings": crossings,
                "max_reach": max_reach,
                "step_speeds": step_speeds,
                "rolling_180": rolling_180,
                "rolling_600": rolling_600,
                "dwell_durations": dwell_durations,
                "dwell_ratios_300": dwell_ratios_300,
            }
        )

    # Sort all causal history arrays by completion timestamp
    seg_finish_epochs: Dict[str, Dict[int, List[float]]] = {
        d: {} for d in stations_by_dir
    }
    for d in stations_by_dir:
        for k, h_list in seg_traversal_history[d].items():
            h_list.sort(key=lambda x: x[0])
            seg_finish_epochs[d][k] = [x[0] for x in h_list]

    station_pass_epochs: Dict[str, Dict[int, List[float]]] = {
        d: {} for d in stations_by_dir
    }
    for d in stations_by_dir:
        for k, p_list in station_pass_history[d].items():
            p_list.sort(key=lambda x: x[0])
            station_pass_epochs[d][k] = [x[0] for x in p_list]

    # -------------------------------------------------------------------------
    # 6. Second Pass: Extract Supervised Samples with Full Live Fleet Context
    # -------------------------------------------------------------------------
    records: List[dict] = []
    date_meta_cache: Dict[str, Tuple[str, int]] = {}
    hour_min_to_win: List[str] = [
        get_time_window(m_idx / 60.0) for m_idx in range(24 * 60)
    ]

    for tr in processed_trips:
        t_idx = tr["t_idx"]
        trip_id = tr["trip_id"]
        direction = tr["direction"]
        vid = tr["vid"]
        trip = tr["trip"]
        epochs = tr["epochs"]
        s_vals = tr["s_vals"]
        crossings = tr["crossings"]
        max_reach = tr["max_reach"]
        step_speeds = tr["step_speeds"]
        rolling_180 = tr["rolling_180"]
        rolling_600 = tr["rolling_600"]
        dwell_durations = tr["dwell_durations"]
        dwell_ratios_300 = tr["dwell_ratios_300"]

        stations = stations_by_dir[direction]
        st_orders = [s[0] for s in stations]
        st_dists = [s[2] for s in stations]
        n_stations = len(stations)
        seg_lengths = [
            max(10.0, st_dists[k + 1] - st_dists[k]) for k in range(n_stations - 1)
        ]
        dir_encoded = 1 if direction == "go" else 0
        n_pings = len(trip)

        ego_completed_segs: List[Tuple[float, int, float]] = []
        for k_seg in range(n_stations - 1):
            if k_seg in crossings and (k_seg + 1) in crossings:
                t1, _ = crossings[k_seg]
                t2, _ = crossings[k_seg + 1]
                if 5.0 <= (t2 - t1) <= 1800.0:
                    ego_completed_segs.append((t2, k_seg, t2 - t1))
        ego_completed_segs.sort(key=lambda x: x[0])
        ego_seg_finish_times = [x[0] for x in ego_completed_segs]

        for i, p in enumerate(trip):
            dt_str = str(p[4])
            dt_date = dt_str[:10]
            if target_dates and dt_date not in target_dates:
                continue

            ping_id = int(p[0])
            t_ping = epochs[i]
            s_bus = s_vals[i]
            cross_track = float(p[6] or 0.0)
            inst_speed = round(max(0.0, min(65.0, float(p[7] or 0.0))), 2)
            is_dwell = int(p[8] or 0)

            k = bisect.bisect_left(st_dists, s_bus)
            if k <= 0:
                k = 1
            if k >= n_stations:
                continue

            cached_date = date_meta_cache.get(dt_date)
            if cached_date is None:
                try:
                    dt_d_obj = datetime.strptime(dt_date, "%Y-%m-%d")
                except ValueError:
                    dt_d_obj = datetime.fromtimestamp(t_ping)
                dtype_val = get_day_type(dt_d_obj)
                wknd_val = 1 if dtype_val in ("SATURDAY", "SUNDAY") else 0
                cached_date = (dtype_val, wknd_val)
                date_meta_cache[dt_date] = cached_date
            dtype, is_weekend = cached_date

            if len(dt_str) >= 16 and dt_str[13] == ":":
                hr_int = int(dt_str[11:13])
                mn_int = int(dt_str[14:16])
            else:
                dt_fallback = datetime.fromtimestamp(t_ping)
                hr_int = dt_fallback.hour
                mn_int = dt_fallback.minute
            win = hour_min_to_win[hr_int * 60 + mn_int]

            # --- A. Multi-ping ego speeds & trend ---
            v_p1 = step_speeds[i]
            v_p2 = step_speeds[i - 1] if i >= 1 else v_p1
            v_p3 = step_speeds[i - 2] if i >= 2 else v_p2
            v_r180 = round(rolling_180[i], 2)
            v_r600 = round(rolling_600[i], 2)
            accel_trend = v_r180 - v_r600

            # --- B. Ego recent realized pace ratio on last 1-3 completed segments ---
            ego_pos = bisect.bisect_right(ego_seg_finish_times, t_ping)
            ego_real_sum = 0.0
            ego_k_list = [-1, -1, -1]
            if ego_pos > 0:
                recent_ego = ego_completed_segs[max(0, ego_pos - 3) : ego_pos]
                ego_base_sum = 0.0
                for idx_eg, (_, k_s, dt_e) in enumerate(recent_ego):
                    ego_k_list[idx_eg] = k_s
                    b_seg = baseline_matrix.get(
                        (direction, st_orders[k_s], win, dtype),
                        (seg_lengths[k_s] / 4.5, 15.0, 0.0, 0.0, 16.2),
                    )
                    ego_real_sum += dt_e
                    ego_base_sum += b_seg[0]
                ego_recent_pace_ratio = min(
                    2.5, max(0.3, ego_real_sum / max(ego_base_sum, 10.0))
                )
            else:
                ego_recent_pace_ratio = 1.0

            # --- C. Live Spatial Fleet State (Leader & Follower at t_ping) ---
            bucket = int(t_ping // 600.0)
            candidate_t_indices = time_buckets[direction].get(bucket, [])
            dist_to_leader = 5000.0
            leader_live_spd = v_r180
            dist_to_follower = 5000.0
            active_fleet = 1

            for other_idx in candidate_t_indices:
                if other_idx == t_idx:
                    continue
                other_tr = processed_trips[other_idx]
                if other_tr["vid"] == vid:
                    continue
                o_epochs = other_tr["epochs"]
                if t_ping < o_epochs[0] or t_ping > o_epochs[-1] + 120.0:
                    continue
                pos_o = bisect.bisect_right(o_epochs, t_ping) - 1
                if pos_o < 0:
                    continue
                dt_lag = t_ping - o_epochs[pos_o]
                if dt_lag > 180.0:
                    continue

                active_fleet += 1
                s_other = other_tr["s_vals"][pos_o]
                v_other = other_tr["rolling_180"][pos_o]
                diff_s = s_other - s_bus
                if diff_s > 5.0 and diff_s < dist_to_leader:
                    dist_to_leader = diff_s
                    leader_live_spd = v_other
                elif diff_s < -5.0 and (-diff_s) < dist_to_follower:
                    dist_to_follower = -diff_s

            # --- D. Time Headway since previous bus passed station k-1 ---
            pass_epochs_k = station_pass_epochs[direction].get(k - 1, [])
            pass_list_k = station_pass_history[direction].get(k - 1, [])
            headway_sec = 1800.0
            if pass_epochs_k:
                idx_p = bisect.bisect_right(pass_epochs_k, t_ping) - 1
                while idx_p >= 0 and pass_list_k[idx_p][1] == t_idx:
                    idx_p -= 1
                if idx_p >= 0:
                    dt_hw = t_ping - pass_epochs_k[idx_p]
                    if 5.0 <= dt_hw <= 3600.0:
                        headway_sec = dt_hw

            # --- E. Downstream Station Horizon Loop (m = k .. k + max_stops_ahead - 1) ---
            dist_to_next_stop = max(0.0, st_dists[k] - s_bus)
            alpha_first = min(1.0, max(0.0, dist_to_next_stop / seg_lengths[k - 1]))

            b0 = baseline_matrix.get(
                (direction, st_orders[k - 1], win, dtype),
                (seg_lengths[k - 1] / 4.5, 15.0, seg_lengths[k - 1] / 6.0, seg_lengths[k - 1] / 3.2, 16.2),
            )

            # Lookup leader traversal for first partial segment (k-1 -> k)
            lead_t0, age0 = b0[0], 1800.0
            has_lead0 = False
            f_epochs0 = seg_finish_epochs[direction].get(k - 1, [])
            if f_epochs0:
                p0 = bisect.bisect_right(f_epochs0, t_ping) - 1
                h_list0 = seg_traversal_history[direction][k - 1]
                while p0 >= 0 and h_list0[p0][2] == t_idx:
                    p0 -= 1
                if p0 >= 0 and (t_ping - f_epochs0[p0]) <= 2700.0:
                    lead_t0 = h_list0[p0][1]
                    age0 = t_ping - f_epochs0[p0]
                    has_lead0 = True

            cum_base_med = alpha_first * b0[0]
            cum_base_var = (alpha_first * b0[1]) ** 2
            cum_base_p10 = alpha_first * b0[2]
            cum_base_p90 = alpha_first * b0[3]
            cum_leader_eta = alpha_first * lead_t0
            cum_lead_obs_sec = (alpha_first * lead_t0) if has_lead0 else 0.0
            lead_miss_mask = 0 if has_lead0 else 1
            leader_age_sum = age0
            leader_seg_cnt = 1

            # Segment-by-segment TomTom incident lookup for first partial segment (k-1 -> k)
            b_inc = int(t_ping // 600.0)
            cum_tomtom_delay = 0.0
            max_tomtom_mag = 0
            if include_tomtom:
                best_del0 = 0.0
                best_mag0 = 0
                for t_s_i, t_e_i, s_min_i, s_max_i, del_i, mag_i in (
                    tomtom_seg_buckets.get(direction, {}).get(st_orders[k - 1], {}).get(b_inc, [])
                ):
                    if t_s_i <= t_ping <= t_e_i and s_max_i > s_bus + 5.0:
                        ov0 = min(st_dists[k], s_max_i) - max(s_bus, s_min_i)
                        if ov0 >= 5.0:
                            seg_inc_span = max(15.0, s_max_i - s_min_i)
                            eff_d0 = del_i * min(1.0, ov0 / seg_inc_span)
                            if eff_d0 > best_del0:
                                best_del0 = eff_d0
                            if mag_i > best_mag0:
                                best_mag0 = mag_i
                cum_tomtom_delay = best_del0
                max_tomtom_mag = best_mag0

            reach_limit = max_reach[i]
            max_m = min(n_stations - 1, k + max_stops_ahead - 1)
            for m in range(k, max_m + 1):
                if m > k:
                    seg_idx = m - 1
                    slot_bit = 1 << (m - k)
                    bm = baseline_matrix.get(
                        (direction, st_orders[seg_idx], win, dtype),
                        (seg_lengths[seg_idx] / 4.5, 15.0, seg_lengths[seg_idx] / 6.0, seg_lengths[seg_idx] / 3.2, 16.2),
                    )
                    cum_base_med += bm[0]
                    cum_base_var += bm[1] ** 2
                    cum_base_p10 += bm[2]
                    cum_base_p90 += bm[3]

                    lead_tm, agem = bm[0], 1800.0
                    has_leadm = False
                    f_epochsm = seg_finish_epochs[direction].get(seg_idx, [])
                    if f_epochsm:
                        pm = bisect.bisect_right(f_epochsm, t_ping) - 1
                        h_listm = seg_traversal_history[direction][seg_idx]
                        while pm >= 0 and h_listm[pm][2] == t_idx:
                            pm -= 1
                        if pm >= 0 and (t_ping - f_epochsm[pm]) <= 2700.0:
                            lead_tm = h_listm[pm][1]
                            agem = t_ping - f_epochsm[pm]
                            has_leadm = True

                    cum_leader_eta += lead_tm
                    if has_leadm:
                        cum_lead_obs_sec += lead_tm
                    else:
                        lead_miss_mask |= slot_bit
                    leader_age_sum += agem
                    leader_seg_cnt += 1

                    if include_tomtom:
                        best_delm = 0.0
                        best_magm = 0
                        for t_s_i, t_e_i, s_min_i, s_max_i, del_i, mag_i in (
                            tomtom_seg_buckets.get(direction, {}).get(st_orders[seg_idx], {}).get(b_inc, [])
                        ):
                            if t_s_i <= t_ping <= t_e_i:
                                if del_i > best_delm:
                                    best_delm = del_i
                                if mag_i > best_magm:
                                    best_magm = mag_i
                        cum_tomtom_delay += best_delm
                        if best_magm > max_tomtom_mag:
                            max_tomtom_mag = best_magm

                dist_rem = round(st_dists[m] - s_bus, 2)
                if dist_rem < 5.0 or dist_rem > max_horizon_m:
                    continue

                if m not in crossings:
                    continue

                t_arrival, cross_idx = crossings[m]
                if cross_idx < i or cross_idx + 1 > reach_limit:
                    continue

                actual_rem_sec = t_arrival - t_ping
                if actual_rem_sec < 5.0 or actual_rem_sec > 1800.0:
                    continue

                realized_spd_kmh = (dist_rem / actual_rem_sec) * 3.6
                if realized_spd_kmh < 1.8 or realized_spd_kmh > 75.0:
                    continue

                base_std = math.sqrt(cum_base_var)
                base_spread = max(5.0, cum_base_p90 - cum_base_p10)
                base_spd_kmh = max(4.0, (dist_rem / max(cum_base_med, 5.0)) * 3.6)

                eff_spd_kmh = (
                    v_r180 if v_r180 >= 3.0 else max(inst_speed, base_spd_kmh * 0.75)
                )
                speed_ratio = min(2.5, max(0.2, eff_spd_kmh / base_spd_kmh))
                kinematic_eta = dist_rem / max(eff_spd_kmh / 3.6, 1.5)

                leader_pace_ratio = min(
                    2.5, max(0.3, cum_leader_eta / max(cum_base_med, 5.0))
                )
                mean_leader_age = leader_age_sum / leader_seg_cnt

                tomtom_has_inc = 1 if cum_tomtom_delay >= 1.0 else 0
                tomtom_cum_delay = round(min(1200.0, cum_tomtom_delay), 1)
                tomtom_max_mag = max_tomtom_mag

                rec_dict = {
                    "ping_id": ping_id,
                    "trip_id": trip_id,
                    "vehicle_id": vid,
                    "route_code": route_code,
                    "direction": direction,
                    "direction_encoded": dir_encoded,
                    "dt": dt_date,
                    "k_idx": k,
                    "alpha_first": alpha_first,
                    "ego_real_sum": ego_real_sum,
                    "ego_k0": ego_k_list[0],
                    "ego_k1": ego_k_list[1],
                    "ego_k2": ego_k_list[2],
                    "lead_obs_sec": cum_lead_obs_sec,
                    "lead_miss_mask": lead_miss_mask,
                    "target_station_order": st_orders[m],
                    "stops_ahead": (m - k + 1),
                    "s_bus_m": round(s_bus, 2),
                    "distance_remaining_m": dist_rem,
                    "dist_to_next_stop_m": round(dist_to_next_stop, 2),
                    "cross_track_m": round(cross_track, 2),
                    "derived_speed_kmh": inst_speed,
                    "v_last_1_ping_kmh": round(v_p1, 2),
                    "v_last_2_ping_kmh": round(v_p2, 2),
                    "v_last_3_ping_kmh": round(v_p3, 2),
                    "rolling_speed_180s_kmh": v_r180,
                    "rolling_speed_600s_kmh": v_r600,
                    "accel_trend_kmh": round(accel_trend, 2),
                    "speed_vs_baseline_ratio": round(speed_ratio, 3),
                    "ego_recent_pace_ratio": round(ego_recent_pace_ratio, 3),
                    "is_dwell": is_dwell,
                    "current_dwell_sec": round(dwell_durations[i], 1),
                    "dwell_ratio_300s": round(dwell_ratios_300[i], 3),
                    "kinematic_eta_sec": round(kinematic_eta, 2),
                    "leader_expected_eta_sec": round(cum_leader_eta, 2),
                    "leader_pace_ratio": round(leader_pace_ratio, 3),
                    "leader_info_age_sec": round(mean_leader_age, 1),
                    "dist_to_leader_m": round(dist_to_leader, 1),
                    "leader_live_speed_kmh": round(leader_live_spd, 2),
                    "dist_to_follower_m": round(dist_to_follower, 1),
                    "headway_to_leader_sec": round(headway_sec, 1),
                    "active_fleet_count": active_fleet,
                    "hour": hr_int,
                    "minute": mn_int,
                    "is_weekend": is_weekend,
                    "time_window": win,
                    "day_type": dtype,
                    "baseline_median_sec": round(cum_base_med, 2),
                    "baseline_p10_sec": round(cum_base_p10, 2),
                    "baseline_p90_sec": round(cum_base_p90, 2),
                    "baseline_std_sec": round(base_std, 2),
                    "baseline_spread_sec": round(base_spread, 2),
                    "actual_remaining_sec": round(actual_rem_sec, 2),
                }

                if include_tomtom:
                    rec_dict["tomtom_has_incident"] = tomtom_has_inc
                    rec_dict["tomtom_delay_sec"] = tomtom_cum_delay
                    rec_dict["tomtom_magnitude"] = tomtom_max_mag

                records.append(rec_dict)

    df_out = pd.DataFrame(records)
    if not df_out.empty:
        df_out = bind_stage2_dynamic_matrix(df_out, route_code, db_path=resolved_db, inplace=True)
    return df_out


def bind_stage2_dynamic_matrix(
    df: pd.DataFrame,
    route_code: str,
    db_path: Optional[str] = None,
    inplace: bool = True,
) -> pd.DataFrame:
    """
    Stage 2 of the Two-Stage Decoupled Feature Architecture (WP 2.2):
    Given a DataFrame of Stage 1 immutable physical kinematic samples loaded from
    Apache Parquet (across all historical weeks), dynamically re-binds the latest
    Weekly `agg_segment_travel_times` matrix in <0.12s/route using vectorized
    NumPy array indexing.
    Updates:
      - baseline_median_sec, baseline_p10_sec, baseline_p90_sec, baseline_std_sec, baseline_spread_sec
      - ego_recent_pace_ratio
      - speed_vs_baseline_ratio, kinematic_eta_sec
      - leader_expected_eta_sec, leader_pace_ratio
    Guarantees 0% Stale Matrix Drift across weeks as the travel time matrix matures.
    """
    if df.empty or "k_idx" not in df.columns:
        return df

    resolved_db = db_path or str(get_database_path())
    conn = sqlite3.connect(resolved_db)
    cur = conn.cursor()

    cur.execute(
        """
        SELECT direction, station_order, cum_distance_m
        FROM canonical_station_master
        WHERE route_code = ?
        ORDER BY direction, station_order ASC
        """,
        (route_code,),
    )
    stations_by_dir: Dict[str, List[Tuple[int, float]]] = {}
    for d, st_order, cum_d in cur.fetchall():
        stations_by_dir.setdefault(str(d), []).append((int(st_order), float(cum_d)))

    baseline_matrix = _load_route_baseline_matrix(conn, route_code)
    conn.close()

    max_segs = max((len(v) for v in stations_by_dir.values()), default=2)
    n_win = len(TIME_WINDOWS)
    n_dt = len(DAY_TYPES)

    # Build 4D lookup arrays: [dir_enc (2), win_idx (9), dtype_idx (3), seg_idx (max_segs)]
    med_lut = np.zeros((2, n_win, n_dt, max_segs), dtype=np.float64)
    std_lut = np.zeros((2, n_win, n_dt, max_segs), dtype=np.float64)
    p10_lut = np.zeros((2, n_win, n_dt, max_segs), dtype=np.float64)
    p90_lut = np.zeros((2, n_win, n_dt, max_segs), dtype=np.float64)

    for d_str, d_enc in (("re", 0), ("go", 1)):
        st_list = stations_by_dir.get(d_str, [])
        n_st = len(st_list)
        if n_st < 2:
            continue
        for seg_idx in range(n_st - 1):
            st_ord = st_list[seg_idx][0]
            seg_len = max(10.0, st_list[seg_idx + 1][1] - st_list[seg_idx][1])
            def_tuple = (seg_len / 4.5, 15.0, seg_len / 6.0, seg_len / 3.2, 16.2)
            for w_str, w_idx in TIME_WINDOW_INDEX.items():
                for dt_str, dt_idx in DAY_TYPE_INDEX.items():
                    b_val = baseline_matrix.get((d_str, st_ord, w_str, dt_str), def_tuple)
                    med_lut[d_enc, w_idx, dt_idx, seg_idx] = b_val[0]
                    std_lut[d_enc, w_idx, dt_idx, seg_idx] = b_val[1]
                    p10_lut[d_enc, w_idx, dt_idx, seg_idx] = b_val[2]
                    p90_lut[d_enc, w_idx, dt_idx, seg_idx] = b_val[3]

    # Map hour + minute directly to window index in O(1) without hashing 800k strings
    hour_min_win_lut = np.array(
        [TIME_WINDOW_INDEX[get_time_window(m_idx / 60.0)] for m_idx in range(24 * 60)],
        dtype=np.int32,
    )
    dir_arr = df["direction_encoded"].to_numpy(dtype=np.int32)
    hr_arr = df["hour"].to_numpy(dtype=np.int32)
    mn_arr = df["minute"].to_numpy(dtype=np.int32)
    win_arr = hour_min_win_lut[np.clip(hr_arr * 60 + mn_arr, 0, 1439)]

    # Fast categorical lookup for day_type (only 3 categories)
    dt_cat = pd.Categorical(df["day_type"], categories=DAY_TYPES)
    dt_arr = np.clip(dt_cat.codes.astype(np.int32), 0, n_dt - 1)

    k_arr = df["k_idx"].to_numpy(dtype=np.int32)
    stops_arr = df["stops_ahead"].to_numpy(dtype=np.int32)
    alpha_arr = df["alpha_first"].to_numpy(dtype=np.float64)
    lead_obs_arr = df["lead_obs_sec"].to_numpy(dtype=np.float64)
    miss_mask_arr = df["lead_miss_mask"].to_numpy(dtype=np.int32)

    # Slot 0: partial segment k - 1
    seg0 = np.clip(k_arr - 1, 0, max_segs - 1)
    b0_med = med_lut[dir_arr, win_arr, dt_arr, seg0]
    b0_std = std_lut[dir_arr, win_arr, dt_arr, seg0]
    b0_p10 = p10_lut[dir_arr, win_arr, dt_arr, seg0]
    b0_p90 = p90_lut[dir_arr, win_arr, dt_arr, seg0]

    cum_base_med = alpha_arr * b0_med
    cum_base_var = (alpha_arr * b0_std) ** 2
    cum_base_p10 = alpha_arr * b0_p10
    cum_base_p90 = alpha_arr * b0_p90
    cum_leader_eta = lead_obs_arr + np.where((miss_mask_arr & 1) != 0, alpha_arr * b0_med, 0.0)

    # Slots 1..4: subsequent full segments k, k+1, k+2, k+3
    max_s = int(stops_arr.max()) if len(stops_arr) > 0 else 1
    for s_slot in range(1, max_s):
        active = stops_arr > s_slot
        segs = np.clip(k_arr - 1 + s_slot, 0, max_segs - 1)
        bm_med = np.where(active, med_lut[dir_arr, win_arr, dt_arr, segs], 0.0)
        bm_std = np.where(active, std_lut[dir_arr, win_arr, dt_arr, segs], 0.0)
        bm_p10 = np.where(active, p10_lut[dir_arr, win_arr, dt_arr, segs], 0.0)
        bm_p90 = np.where(active, p90_lut[dir_arr, win_arr, dt_arr, segs], 0.0)

        cum_base_med += bm_med
        cum_base_var += bm_std ** 2
        cum_base_p10 += bm_p10
        cum_base_p90 += bm_p90
        miss_slot = active & ((miss_mask_arr & (1 << s_slot)) != 0)
        cum_leader_eta += np.where(miss_slot, bm_med, 0.0)

    # Recompute ego_recent_pace_ratio
    ego_real = df["ego_real_sum"].to_numpy(dtype=np.float64)
    ego_base = np.zeros_like(ego_real)
    for col_k in ("ego_k0", "ego_k1", "ego_k2"):
        ek = df[col_k].to_numpy(dtype=np.int32)
        valid_ek = ek >= 0
        ek_clamped = np.clip(ek, 0, max_segs - 1)
        ego_base += np.where(valid_ek, med_lut[dir_arr, win_arr, dt_arr, ek_clamped], 0.0)

    has_ego = df["ego_k0"].to_numpy(dtype=np.int32) >= 0
    ego_pace_ratio = np.where(
        has_ego,
        np.clip(ego_real / np.maximum(ego_base, 10.0), 0.3, 2.5),
        1.0,
    )

    # Recompute speed_vs_baseline_ratio & leader_pace_ratio
    dist_rem = df["distance_remaining_m"].to_numpy(dtype=np.float64)
    v_r180 = df["rolling_speed_180s_kmh"].to_numpy(dtype=np.float64)
    inst_spd = df["derived_speed_kmh"].to_numpy(dtype=np.float64)

    base_std = np.sqrt(cum_base_var)
    base_spread = np.maximum(5.0, cum_base_p90 - cum_base_p10)
    base_spd_kmh = np.maximum(4.0, (dist_rem / np.maximum(cum_base_med, 5.0)) * 3.6)
    eff_spd_kmh = np.where(v_r180 >= 3.0, v_r180, np.maximum(inst_spd, base_spd_kmh * 0.75))
    speed_ratio = np.clip(eff_spd_kmh / base_spd_kmh, 0.2, 2.5)
    kinematic_eta = dist_rem / np.maximum(eff_spd_kmh / 3.6, 1.5)
    leader_pace_ratio = np.clip(cum_leader_eta / np.maximum(cum_base_med, 5.0), 0.3, 2.5)

    out = df if inplace else df.copy()
    out["baseline_median_sec"] = np.round(cum_base_med, 2)
    out["baseline_p10_sec"] = np.round(cum_base_p10, 2)
    out["baseline_p90_sec"] = np.round(cum_base_p90, 2)
    out["baseline_std_sec"] = np.round(base_std, 2)
    out["baseline_spread_sec"] = np.round(base_spread, 2)
    out["ego_recent_pace_ratio"] = np.round(ego_pace_ratio, 3)
    out["speed_vs_baseline_ratio"] = np.round(speed_ratio, 3)
    out["kinematic_eta_sec"] = np.round(kinematic_eta, 2)
    out["leader_expected_eta_sec"] = np.round(cum_leader_eta, 2)
    out["leader_pace_ratio"] = np.round(leader_pace_ratio, 3)
    return out


if __name__ == "__main__":
    rc = sys.argv[1] if len(sys.argv) > 1 else "02"
    ds = extract_route_training_dataset(rc)
    print(
        f"Extracted {len(ds):,} supervised training samples across {ds['trip_id'].nunique() if not ds.empty else 0:,} trips for Route {rc}."
    )
    if not ds.empty:
        print(
            ds[
                [
                    "trip_id",
                    "stops_ahead",
                    "v_last_1_ping_kmh",
                    "ego_recent_pace_ratio",
                    "leader_expected_eta_sec",
                    "dist_to_leader_m",
                    "baseline_median_sec",
                    "actual_remaining_sec",
                ]
            ].head(10)
        )
