"""
Module 3: Bus ETA Prediction Engine
Subcomponent: step_3_1_historical_baseline_model
File: baseline_segment_average.py

Historical Segment Travel Time Matrix (Medallion Gold Serving Layer).
Implements:
1. Linear Station Crossing Interpolation (Doc 49, Section 3.2)
2. Deadheading & Detour Corridor Filtering (Doc 54: d_perp <= 35m)
3. 3 Day Types: WEEKDAY (Mon-Fri), SATURDAY, SUNDAY
4. 9 Adaptive Kinematic Regimes (Inflection-point grounded temporal discretization)
5. 3-Tier Fallback Imputation (Doc 49, Section 3.4)
6. Gold Schema Persistence (`agg_segment_travel_times`)
7. Closed-form Anchor Baseline ETA inference (Doc 49, Section 5)
Pure Python Standard Library implementation for maximum portability and zero-drift execution.
"""

import os
import sys
import sqlite3
import math
import statistics
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from typing import Dict, List, Tuple, Optional, Any
from concurrent.futures import ProcessPoolExecutor, as_completed

# Ensure project root in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
sys.path.insert(0, os.path.abspath("."))

from config.system_config import (
    get_database_path,
    DEFAULT_DB_PATH,
    TZ_HANOI,
    MAX_CORRIDOR_CROSS_TRACK_M
)

# 9 Adaptive Kinematic Regimes based on empirical inflection points
TIME_WINDOWS = [
    "EARLY_MORNING",       # 05:00 - 06:30 (Free-flow morning)
    "MORNING_SURGE",       # 06:30 - 07:00 (Inbound commute transition)
    "MORNING_PEAK",        # 07:00 - 09:00 (Morning congestion core)
    "MID_MORNING",         # 09:00 - 11:30 (Late morning steady state)
    "MIDDAY_LULL",         # 11:30 - 13:45 (Noon low-flow steady state)
    "EARLY_AFTERNOON",     # 13:45 - 16:30 (Afternoon build-up)
    "PRE_EVENING_PEAK",    # 16:30 - 17:30 (Early evening transition)
    "EVENING_PEAK_CORE",   # 17:30 - 19:00 (Critical shockwave core)
    "LATE_EVENING_NIGHT"   # 19:00 - 22:30 (Evening dissipation & night)
]

# Adjacent time windows with similar traffic kinematics for Tier-1 fallback
ADJACENT_WINDOWS = {
    "EARLY_MORNING": ["MORNING_SURGE"],
    "MORNING_SURGE": ["MID_MORNING", "EARLY_MORNING"],
    "MORNING_PEAK": ["PRE_EVENING_PEAK", "EVENING_PEAK_CORE"],
    "MID_MORNING": ["EARLY_AFTERNOON", "MIDDAY_LULL"],
    "MIDDAY_LULL": ["MID_MORNING", "EARLY_AFTERNOON"],
    "EARLY_AFTERNOON": ["MID_MORNING", "PRE_EVENING_PEAK"],
    "PRE_EVENING_PEAK": ["EARLY_AFTERNOON", "MORNING_PEAK"],
    "EVENING_PEAK_CORE": ["MORNING_PEAK", "PRE_EVENING_PEAK"],
    "LATE_EVENING_NIGHT": ["MIDDAY_LULL", "EARLY_MORNING"]
}

# 3 Granular Day Types
DAY_TYPES = ["WEEKDAY", "SATURDAY", "SUNDAY"]


def get_time_window(hour_val: float) -> str:
    """Discretize hour into 9 adaptive transit kinematic regimes."""
    if 5.0 <= hour_val < 6.5:
        return "EARLY_MORNING"
    elif 6.5 <= hour_val < 7.0:
        return "MORNING_SURGE"
    elif 7.0 <= hour_val < 9.0:
        return "MORNING_PEAK"
    elif 9.0 <= hour_val < 11.5:
        return "MID_MORNING"
    elif 11.5 <= hour_val < 13.75:
        return "MIDDAY_LULL"
    elif 13.75 <= hour_val < 16.5:
        return "EARLY_AFTERNOON"
    elif 16.5 <= hour_val < 17.5:
        return "PRE_EVENING_PEAK"
    elif 17.5 <= hour_val < 19.0:
        return "EVENING_PEAK_CORE"
    else:
        return "LATE_EVENING_NIGHT"


def get_day_type(dt: datetime) -> str:
    """Determine weekday vs saturday vs sunday."""
    wd = dt.weekday()
    if wd < 5:
        return "WEEKDAY"
    elif wd == 5:
        return "SATURDAY"
    else:
        return "SUNDAY"


def continuous_percentile(sorted_list: List[float], p: float) -> float:
    """Compute continuous percentile using linear interpolation (like numpy percentile)."""
    n = len(sorted_list)
    if n == 0:
        return 0.0
    if n == 1:
        return sorted_list[0]
    idx = p * (n - 1)
    i = int(math.floor(idx))
    f = idx - i
    if i >= n - 1:
        return sorted_list[-1]
    return sorted_list[i] + f * (sorted_list[i + 1] - sorted_list[i])


def _is_valid_segment_traversal(
    trip: List[Tuple[float, float, str]],
    i1: int,
    i2: int,
    max_gap_s: float = 300.0,
    max_stall_s: float = 300.0,
    stall_dist_m: float = 40.0
) -> bool:
    """
    Validate that the traversal between station k (crossed at ping pair i1..i1+1)
    and station k+1 (crossed at ping pair i2..i2+1) is a continuous transit movement
    without telemetry blackouts (> 300s) or mid-segment layovers/staging (>= 300s within 40m).
    """
    if i2 < i1:
        return False
    for j in range(i1, i2 + 1):
        if trip[j + 1][0] - trip[j][0] > max_gap_s:
            return False
        if trip[j + 1][1] < trip[j][1] - 50.0:
            return False

    sub = trip[i1 : i2 + 2]
    n = len(sub)
    for a in range(n):
        for b in range(a + 1, n):
            dt = sub[b][0] - sub[a][0]
            ds = abs(sub[b][1] - sub[a][1])
            if dt >= max_stall_s and ds < stall_dist_m:
                return False
    return True


def _compute_clean_distribution(samples: List[float]) -> Tuple[float, float, float, float, float]:
    """
    Compute outlier-robust (med_t, mean_t, std_t, p10_t, p90_t) consistently on the
    MAD-filtered clean sample set with Empirical Bayes variance shrinkage for small samples.
    """
    raw_med = statistics.median(samples)
    deviations = [abs(x - raw_med) for x in samples]
    mad = statistics.median(deviations)
    threshold = max(3.0 * mad, 45.0)
    upper_cap = max(2.2 * raw_med, raw_med + 300.0)

    clean = [x for x in samples if abs(x - raw_med) <= threshold and x <= upper_cap]
    if len(clean) < 2:
        clean = sorted(samples)[: max(2, len(samples))]
    else:
        clean = sorted(clean)

    med_t = statistics.median(clean)
    mean_t = statistics.mean(clean)
    p10_t = continuous_percentile(clean, 0.10)
    p90_t = continuous_percentile(clean, 0.90)
    raw_std = statistics.stdev(clean) if len(clean) >= 2 else 0.0

    n_c = len(clean)
    if n_c < 15:
        prior_std = 0.20 * med_t
        std_t = (n_c / (n_c + 10.0)) * raw_std + (10.0 / (n_c + 10.0)) * prior_std
    else:
        std_t = raw_std

    return med_t, mean_t, std_t, p10_t, p90_t


def _worker_extract_matrix(args: Tuple[str, str, str]) -> Tuple[str, str, List[Dict[str, Any]], float]:
    """Top-level worker function executing matrix extraction for a single route direction."""
    import time
    db_path, r_code, direction = args
    t0 = time.time()
    model = HistoricalSegmentAverageModel(db_path)
    records = model.extract_route_direction_matrix(r_code, direction)
    return (r_code, direction, records, time.time() - t0)


class HistoricalSegmentAverageModel:
    """
    Computes, persists, and serves historical segment travel times
    for all bus routes across Hanoi using Linear Station Crossing Interpolation
    with 9 Adaptive Kinematic Regimes and 3 Granular Day Types.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or get_database_path()
        self._ensure_table_exists()

    def _ensure_table_exists(self):
        """Ensure agg_segment_travel_times table and indices exist."""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("""
            CREATE TABLE IF NOT EXISTS agg_segment_travel_times (
                route_code              TEXT NOT NULL,
                direction               TEXT NOT NULL,
                from_station_order      INTEGER NOT NULL,
                to_station_order        INTEGER NOT NULL,
                from_station_name       TEXT,
                to_station_name         TEXT,
                segment_distance_m      REAL NOT NULL,
                time_window             TEXT NOT NULL,
                day_type                TEXT NOT NULL,
                sample_count            INTEGER NOT NULL,
                median_transit_sec      REAL NOT NULL,
                mean_transit_sec        REAL NOT NULL,
                std_transit_sec         REAL,
                p10_transit_sec         REAL,
                p90_transit_sec         REAL,
                commercial_speed_kmh    REAL NOT NULL,
                is_interpolated         INTEGER DEFAULT 0,
                updated_at              TEXT NOT NULL,
                PRIMARY KEY (route_code, direction, from_station_order, to_station_order, time_window, day_type)
            );
            """)
            cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_segment_matrix_lookup 
            ON agg_segment_travel_times (route_code, direction, time_window, day_type);
            """)
            conn.commit()

    def extract_route_direction_matrix(self, route_code: str, direction: str = "go") -> List[Dict[str, Any]]:
        """
        Extract travel time matrix for a specific route and direction
        using Linear Station Crossing Interpolation on vehicle trajectories.
        Strictly filters out deadheading/detour pings with cross_track_m > MAX_CORRIDOR_CROSS_TRACK_M (35m).
        """
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()

            # 1. Fetch official station sequence
            stations = cur.execute("""
                SELECT station_order, station_name, cum_distance_m
                FROM canonical_station_master
                WHERE route_code = ? AND direction = ?
                ORDER BY station_order
            """, (route_code, direction)).fetchall()

            if len(stations) < 2:
                return []

            # 2. Fetch all projected telemetry pings within valid corridor (Doc 54: d_perp <= 35m)
            cur.execute("""
                SELECT vehicle_id, device_epoch, s_bus_m, device_update_time
                FROM route_projected_telemetry
                WHERE route_code = ? AND direction = ? AND cross_track_m <= ?
                ORDER BY vehicle_id, device_epoch
            """, (route_code, direction, MAX_CORRIDOR_CROSS_TRACK_M))
            rows = cur.fetchall()

        # 3. Group pings by vehicle (if any valid pings exist)
        pings_by_veh = defaultdict(list)
        if rows:
            for vid, epoch, s, utime in rows:
                pings_by_veh[vid].append((epoch, s, utime))

        # 4. Split vehicle traces into trips and detect station crossings
        segment_raw_samples = defaultdict(list)
        all_day_segment_samples = defaultdict(list)
        all_speeds = []

        for vid, plist in pings_by_veh.items():
            # Segment trace into trips when s drops backwards (> 300m from step or trip peak) or time gap > 600s
            trips = []
            curr_trip = []
            max_s = -1.0
            for p in plist:
                if curr_trip and (
                    p[1] < curr_trip[-1][1] - 300.0
                    or p[1] < max_s - 300.0
                    or p[0] - curr_trip[-1][0] > 600.0
                ):
                    if len(curr_trip) >= 4:
                        trips.append(curr_trip)
                    curr_trip = [p]
                    max_s = p[1]
                else:
                    curr_trip.append(p)
                    if p[1] > max_s:
                        max_s = p[1]
            if len(curr_trip) >= 4:
                trips.append(curr_trip)

            for trip in trips:
                # Interpolate crossing epoch for each station monotonically along trip
                crossings = {}
                cross_idx = {}
                search_start = 0
                for k in range(len(stations)):
                    s_target = stations[k][2]
                    for i in range(search_start, len(trip) - 1):
                        tA, sA, uA = trip[i]
                        tB, sB, uB = trip[i + 1]
                        if sA <= s_target < sB and 0 < tB - tA <= 180.0 and sB > sA:
                            # Rolling departure validation for Station 0 (terminal)
                            # Ensure vehicle actively leaves depot by checking progress in forward pings
                            if k == 0:
                                has_departed = False
                                for j in range(i + 1, min(i + 6, len(trip))):
                                    if trip[j][1] > s_target + 50.0:
                                        has_departed = True
                                        break
                                if not has_departed:
                                    continue
                            t_cross = tA + (tB - tA) * ((s_target - sA) / (sB - sA))
                            crossings[k] = (t_cross, uA)
                            cross_idx[k] = i
                            search_start = i
                            break

                # Measure travel time between consecutive stations k -> k+1
                for k in range(len(stations) - 1):
                    if k in crossings and (k + 1) in crossings:
                        i1 = cross_idx[k]
                        i2 = cross_idx[k + 1]
                        if not _is_valid_segment_traversal(trip, i1, i2):
                            continue
                        t1, u1 = crossings[k]
                        t2, u2 = crossings[k + 1]
                        delta_t = t2 - t1
                        delta_s = stations[k + 1][2] - stations[k][2]
                        if delta_t > 0 and delta_s > 0:
                            v_kmh = (delta_s / delta_t) * 3.6
                            # Sanity Filter: 3 km/h <= speed <= 75 km/h, 10s <= delta_t <= 1800s
                            if 3.0 <= v_kmh <= 75.0 and 10.0 <= delta_t <= 1800.0:
                                try:
                                    dt = datetime.fromisoformat(u1.replace("Z", "+00:00"))
                                    hour_val = dt.hour + dt.minute / 60.0
                                    dtype = get_day_type(dt)
                                except Exception:
                                    hour_val = 12.0
                                    dtype = "WEEKDAY"

                                win = get_time_window(hour_val)
                                segment_raw_samples[(k, win, dtype)].append(delta_t)
                                all_day_segment_samples[(k, dtype)].append(delta_t)
                                all_speeds.append(v_kmh)

        # 5. Route-level fallback speed
        fallback_speed_kmh = statistics.median(all_speeds) if all_speeds else 18.0

        # 6. Build matrix records with 3-tier Fallback Imputation
        records = []
        now_iso = datetime.now(timezone.utc).isoformat()

        for k in range(len(stations) - 1):
            s_from_order, s_from_name, s_from_dist = stations[k]
            s_to_order, s_to_name, s_to_dist = stations[k + 1]
            seg_dist = max(10.0, s_to_dist - s_from_dist)

            for dtype in DAY_TYPES:
                all_day_samples = all_day_segment_samples.get((k, dtype), [])

                for win in TIME_WINDOWS:
                    samples = segment_raw_samples.get((k, win, dtype), [])
                    n_samples = len(samples)

                    if n_samples >= 3:
                        # Tier 0: Full statistical distribution on MAD-cleaned observed samples
                        med_t, mean_t, std_t, p10_t, p90_t = _compute_clean_distribution(samples)
                        comm_spd = (seg_dist / med_t) * 3.6
                        is_interpolated = 0
                    else:
                        # Tier 1 Fallback: Regime-matched pooling (same window across day types first, then adjacent windows)
                        # Avoids mixing 5 AM free-flow with 6 PM rush hour or industrial shift-change
                        tier1_pool = list(samples)
                        other_dtypes = (
                            ["SATURDAY", "WEEKDAY"] if dtype == "SUNDAY"
                            else ["SUNDAY", "WEEKDAY"] if dtype == "SATURDAY"
                            else ["SATURDAY", "SUNDAY"]
                        )
                        for other_dt in other_dtypes:
                            tier1_pool.extend(segment_raw_samples.get((k, win, other_dt), []))
                            if len(tier1_pool) >= 3:
                                break
                        if len(tier1_pool) < 3:
                            for adj_win in ADJACENT_WINDOWS.get(win, []):
                                tier1_pool.extend(segment_raw_samples.get((k, adj_win, dtype), []))
                                if len(tier1_pool) >= 3:
                                    break
                        if len(tier1_pool) < 3 and len(all_day_samples) >= 3:
                            tier1_pool = list(all_day_samples)

                        if len(tier1_pool) >= 3:
                            med_t, mean_t, std_t, p10_t, p90_t = _compute_clean_distribution(tier1_pool)
                            comm_spd = (seg_dist / med_t) * 3.6
                            is_interpolated = 1
                        else:
                            # Tier 2 Fallback: Route-level average commercial speed
                            med_t = (seg_dist / (fallback_speed_kmh / 3.6))
                            mean_t = med_t
                            std_t = 0.0
                            p10_t = med_t * 0.85
                            p90_t = med_t * 1.30
                            comm_spd = fallback_speed_kmh
                            is_interpolated = 2

                    records.append({
                        "route_code": route_code,
                        "direction": direction,
                        "from_station_order": s_from_order,
                        "to_station_order": s_to_order,
                        "from_station_name": s_from_name,
                        "to_station_name": s_to_name,
                        "segment_distance_m": round(seg_dist, 2),
                        "time_window": win,
                        "day_type": dtype,
                        "sample_count": n_samples,
                        "median_transit_sec": round(med_t, 2),
                        "mean_transit_sec": round(mean_t, 2),
                        "std_transit_sec": round(std_t, 2) if std_t is not None else 0.0,
                        "p10_transit_sec": round(p10_t, 2),
                        "p90_transit_sec": round(p90_t, 2),
                        "commercial_speed_kmh": round(comm_spd, 2),
                        "is_interpolated": is_interpolated,
                        "updated_at": now_iso
                    })

        return records

    def save_matrix_records(self, records: List[Dict[str, Any]]):
        """Persist matrix records to SQLite."""
        if not records:
            return
        query = """
        INSERT OR REPLACE INTO agg_segment_travel_times (
            route_code, direction, from_station_order, to_station_order,
            from_station_name, to_station_name, segment_distance_m,
            time_window, day_type, sample_count,
            median_transit_sec, mean_transit_sec, std_transit_sec,
            p10_transit_sec, p90_transit_sec, commercial_speed_kmh,
            is_interpolated, updated_at
        ) VALUES (
            :route_code, :direction, :from_station_order, :to_station_order,
            :from_station_name, :to_station_name, :segment_distance_m,
            :time_window, :day_type, :sample_count,
            :median_transit_sec, :mean_transit_sec, :std_transit_sec,
            :p10_transit_sec, :p90_transit_sec, :commercial_speed_kmh,
            :is_interpolated, :updated_at
        );
        """
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.executemany(query, records)
            conn.commit()

    def process_all_routes(self, clear_existing: bool = True, max_workers: int = 6) -> Dict[str, int]:
        """
        Process travel time matrices for all active routes in the database using multi-core parallel workers.
        Optionally clears stale table contents before re-populating.
        Strictly capped at max 6 workers.
        """
        max_workers = min(max_workers, 6)
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            if clear_existing:
                print("Clearing stale records from agg_segment_travel_times...")
                cur.execute("DELETE FROM agg_segment_travel_times;")
                conn.commit()

            routes = cur.execute("""
                SELECT DISTINCT route_code, direction
                FROM route_projected_telemetry
                ORDER BY route_code, direction
            """).fetchall()

        summary = {}
        total_records = 0
        print(f"Processing travel time matrices for {len(routes)} route directions using {max_workers} parallel workers...")
        print(f"Applying Deadheading & Detour Corridor Filter: d_perp <= {MAX_CORRIDOR_CROSS_TRACK_M}m")
        print(f"Grid Configuration: 3 Day Types x 9 Adaptive Kinematic Regimes = 27 cells/segment\n")

        tasks = [(self.db_path, r_code, direction) for r_code, direction in routes]
        completed_cnt = 0

        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_worker_extract_matrix, task): task for task in tasks}
            for future in as_completed(futures):
                r_code, direction, records, comp_time = future.result()
                completed_cnt += 1
                if records:
                    self.save_matrix_records(records)
                    key = f"{r_code}_{direction}"
                    summary[key] = len(records)
                    total_records += len(records)
                    print(f"  [{completed_cnt:02d}/{len(routes)}] Route {r_code:<6} [{direction:<6}] -> {len(records):<5} cells in {comp_time:.2f}s | Total: {total_records:,}")

        print(f"\n[DONE] Total matrix records persisted: {total_records:,}")
        return summary

    def generate_audit_report(self, route_codes: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Generate statistical percentile audit report (P10, P50, P90, Speed, Samples)
        on specified routes across the 9 adaptive regimes and 3 day types.
        """
        if route_codes is None:
            route_codes = ["19", "22A", "02"]

        report_data = {}
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            for r in route_codes:
                report_data[r] = {}
                for d in ["go", "re"]:
                    rows = cur.execute("""
                        SELECT 
                            time_window, day_type,
                            count(*) as n_segments,
                            sum(sample_count) as total_samples,
                            avg(median_transit_sec) as avg_p50_sec,
                            avg(p10_transit_sec) as avg_p10_sec,
                            avg(p90_transit_sec) as avg_p90_sec,
                            avg(commercial_speed_kmh) as avg_speed_kmh,
                            sum(CASE WHEN is_interpolated = 0 THEN 1 ELSE 0 END) as n_direct,
                            sum(CASE WHEN is_interpolated = 1 THEN 1 ELSE 0 END) as n_tier1,
                            sum(CASE WHEN is_interpolated = 2 THEN 1 ELSE 0 END) as n_tier2
                        FROM agg_segment_travel_times
                        WHERE route_code = ? AND direction = ?
                        GROUP BY time_window, day_type
                        ORDER BY day_type, time_window
                    """, (r, d)).fetchall()

                    # Overall route-direction summary
                    total_pings = cur.execute("""
                        SELECT count(*) FROM route_projected_telemetry WHERE route_code = ? AND direction = ?
                    """, (r, d)).fetchone()[0]
                    valid_pings = cur.execute("""
                        SELECT count(*) FROM route_projected_telemetry 
                        WHERE route_code = ? AND direction = ? AND cross_track_m <= ?
                    """, (r, d, MAX_CORRIDOR_CROSS_TRACK_M)).fetchone()[0]

                    report_data[r][d] = {
                        "total_pings": total_pings,
                        "valid_pings": valid_pings,
                        "valid_pct": round(valid_pings / max(1, total_pings) * 100, 2),
                        "windows": rows
                    }

        return report_data

    def predict_eta(
        self,
        route_code: str,
        direction: str,
        current_s_m: float,
        target_station_order: int,
        query_time: Optional[datetime] = None
    ) -> Optional[float]:
        """
        Compute instant Anchor Baseline ETA from current position s_bus to target station S_target.
        Formula: ETA = T_partial(s -> S_{i+1}) + sum_{j=i+1}^{target-1} T(j -> j+1)
        Closed-form execution in < 0.1 ms.
        """
        dt = query_time or datetime.now(TZ_HANOI)
        win = get_time_window(dt.hour + dt.minute / 60.0)
        dtype = get_day_type(dt)

        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            # Fetch all segment travel times up to target
            rows = cur.execute("""
                SELECT from_station_order, to_station_order, segment_distance_m, median_transit_sec
                FROM agg_segment_travel_times
                WHERE route_code = ? AND direction = ? AND time_window = ? AND day_type = ?
                  AND to_station_order <= ?
                ORDER BY from_station_order
            """, (route_code, direction, win, dtype, target_station_order)).fetchall()

            if not rows:
                return None

            # Fetch station positions
            stations = cur.execute("""
                SELECT station_order, cum_distance_m
                FROM canonical_station_master
                WHERE route_code = ? AND direction = ?
                ORDER BY station_order
            """, (route_code, direction)).fetchall()

        # Find which segment the bus is currently on
        s_map = {order: dist for order, dist in stations}
        cur_segment = None
        for r in rows:
            s_from = s_map.get(r[0], 0.0)
            s_to = s_map.get(r[1], 0.0)
            if s_from <= current_s_m < s_to:
                cur_segment = r
                break

        if not cur_segment:
            # Bus might be before first station or past target
            if current_s_m < s_map.get(rows[0][0], 0.0):
                cur_segment = rows[0]
            else:
                return 0.0

        cur_from_order, cur_to_order, cur_dist, cur_med_t = cur_segment
        s_next = s_map.get(cur_to_order, current_s_m)
        remaining_in_seg = max(0.0, s_next - current_s_m)
        ratio = remaining_in_seg / max(1.0, cur_dist)
        t_partial = cur_med_t * min(1.0, ratio)

        # Sum full segments between cur_to_order and target_station_order
        t_downstream = sum(r[3] for r in rows if r[0] >= cur_to_order)

        return round(t_partial + t_downstream, 1)


if __name__ == "__main__":
    if sys.stdout.encoding != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    print("=" * 80)
    print("HISTORICAL SEGMENT TRAVEL TIME MATRIX EXTRACTION (MODULE 3)")
    print(f"Corridor Constraint: d_perp <= {MAX_CORRIDOR_CROSS_TRACK_M}m (Doc 54)")
    print(f"Adaptive Architecture: 3 Day Types x 9 Kinematic Regimes = 27 cells/segment")
    print("=" * 80)

    model = HistoricalSegmentAverageModel()

    # Process all routes with new adaptive architecture
    summary = model.process_all_routes(clear_existing=True)

    # Test ETA query on Route 02
    eta_sec = model.predict_eta(
        route_code="02",
        direction="go",
        current_s_m=1200.0,
        target_station_order=5
    )
    if eta_sec is not None:
        print(f"\n[ETA INFERENCE TEST] Route 02 [go] at s=1200m -> Station #5: ETA = {eta_sec}s ({eta_sec/60:.1f} mins)")

    # Run audit report on routes: 19, 22A, 02
    print("\n" + "=" * 80)
    print("AUDIT REPORT: 9-REGIME PERCENTILE DISTRIBUTION ON ROUTES 19, 22A, 02")
    print("=" * 80)
    audit = model.generate_audit_report(["19", "22A", "02"])
    for r in ["19", "22A", "02"]:
        for d in ["go", "re"]:
            data = audit[r][d]
            print(f"\n>>> Route {r} [{d}] | Telemetry: {data['valid_pings']:,}/{data['total_pings']:,} pings valid ({data['valid_pct']}%)")
            print(f"{'Time Regime':<20} {'Day':<9} {'Segs':<5} {'Samples':<8} {'P10 (s)':<9} {'P50 (s)':<9} {'P90 (s)':<9} {'Speed (km/h)':<13} {'Direct/T1/T2'}")
            print("-" * 98)
            for w in data["windows"]:
                win, day, n_seg, smp, p50, p10, p90, spd, d_cnt, t1_cnt, t2_cnt = w
                print(f"{win:<20} {day:<9} {n_seg:<5} {smp:<8} {p10:<9.1f} {p50:<9.1f} {p90:<9.1f} {spd:<13.1f} {d_cnt}/{t1_cnt}/{t2_cnt}")
