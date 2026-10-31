"""
Module 3: Bus ETA Prediction Engine
Subcomponent: step_3_1_historical_baseline_model
File: baseline_segment_average.py

Historical Segment Travel Time Matrix (Medallion Gold Serving Layer).
Implements:
1. Linear Station Crossing Interpolation (Doc 49, Section 3.2)
2. 3-Tier Fallback Imputation (Doc 49, Section 3.4)
3. Gold Schema Persistence (`agg_segment_travel_times`)
4. Closed-form Anchor Baseline ETA inference (Doc 49, Section 5)
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

# Ensure project root in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
sys.path.insert(0, os.path.abspath("."))

from config.system_config import get_database_path, DEFAULT_DB_PATH, TZ_HANOI

TIME_WINDOWS = ["MORNING_PEAK", "OFF_PEAK_DAY", "EVENING_PEAK", "NIGHT"]
DAY_TYPES = ["WEEKDAY", "WEEKEND"]


def get_time_window(hour_val: float) -> str:
    """Discretize hour into transit operational time windows."""
    if 6.5 <= hour_val < 9.0:
        return "MORNING_PEAK"
    elif 9.0 <= hour_val < 16.5:
        return "OFF_PEAK_DAY"
    elif 16.5 <= hour_val < 19.5:
        return "EVENING_PEAK"
    else:
        return "NIGHT"


def get_day_type(dt: datetime) -> str:
    """Determine weekday vs weekend."""
    return "WEEKEND" if dt.weekday() >= 5 else "WEEKDAY"


class HistoricalSegmentAverageModel:
    """
    Computes, persists, and serves historical segment travel times
    for all bus routes across Hanoi using Linear Station Crossing Interpolation.
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
        """
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()

            # 1. Fetch official station sequence
            stations = cur.execute("""
                SELECT station_order, station_name, cum_distance_m
                FROM dim_station_crosswalk
                WHERE route_code = ? AND direction = ?
                ORDER BY station_order
            """, (route_code, direction)).fetchall()

            if len(stations) < 2:
                return []

            # 2. Fetch all projected telemetry pings for this route and direction
            cur.execute("""
                SELECT vehicle_id, device_epoch, s_bus_m, device_update_time
                FROM route_projected_telemetry
                WHERE route_code = ? AND direction = ?
                ORDER BY vehicle_id, device_epoch
            """, (route_code, direction))
            rows = cur.fetchall()

        if not rows:
            return []

        # 3. Group pings by vehicle
        pings_by_veh = defaultdict(list)
        for vid, epoch, s, utime in rows:
            pings_by_veh[vid].append((epoch, s, utime))

        # 4. Split vehicle traces into trips and detect station crossings
        segment_raw_samples = defaultdict(list)
        all_day_segment_samples = defaultdict(list)
        all_speeds = []

        for vid, plist in pings_by_veh.items():
            # Segment trace into trips when s drops backwards
            trips = []
            curr_trip = []
            for p in plist:
                if curr_trip and p[1] < curr_trip[-1][1] - 500.0:
                    if len(curr_trip) >= 4:
                        trips.append(curr_trip)
                    curr_trip = [p]
                else:
                    curr_trip.append(p)
            if len(curr_trip) >= 4:
                trips.append(curr_trip)

            for trip in trips:
                # Interpolate crossing epoch for each station
                crossings = {}
                for k in range(len(stations)):
                    s_target = stations[k][2]
                    for i in range(len(trip) - 1):
                        tA, sA, uA = trip[i]
                        tB, sB, uB = trip[i + 1]
                        if sA <= s_target < sB and 0 < tB - tA <= 180.0 and sB > sA:
                            t_cross = tA + (tB - tA) * ((s_target - sA) / (sB - sA))
                            crossings[k] = (t_cross, uA)
                            break

                # Measure travel time between consecutive stations k -> k+1
                for k in range(len(stations) - 1):
                    if k in crossings and (k + 1) in crossings:
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
                all_day_median = statistics.median(all_day_samples) if all_day_samples else None

                for win in TIME_WINDOWS:
                    samples = segment_raw_samples.get((k, win, dtype), [])
                    n_samples = len(samples)

                    if n_samples >= 3:
                        # Full statistical distribution
                        med_t = statistics.median(samples)
                        mean_t = statistics.mean(samples)
                        std_t = statistics.stdev(samples) if n_samples > 1 else 0.0
                        sorted_s = sorted(samples)
                        p10_idx = int(math.floor(0.10 * (n_samples - 1)))
                        p90_idx = int(math.floor(0.90 * (n_samples - 1)))
                        p10_t = sorted_s[p10_idx]
                        p90_t = sorted_s[p90_idx]
                        comm_spd = (seg_dist / med_t) * 3.6
                        is_interpolated = 0
                    elif all_day_median is not None and len(all_day_samples) >= 3:
                        # Tier 1 Fallback: All-day segment median
                        med_t = all_day_median
                        mean_t = statistics.mean(all_day_samples)
                        std_t = statistics.stdev(all_day_samples) if len(all_day_samples) > 1 else 0.0
                        sorted_all = sorted(all_day_samples)
                        p10_t = sorted_all[int(0.10 * (len(sorted_all) - 1))]
                        p90_t = sorted_all[int(0.90 * (len(sorted_all) - 1))]
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

    def process_all_routes(self) -> Dict[str, int]:
        """Process travel time matrices for all active routes in the database."""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            routes = cur.execute("""
                SELECT DISTINCT route_code, direction
                FROM route_projected_telemetry
                ORDER BY route_code, direction
            """).fetchall()

        summary = {}
        total_records = 0
        print(f"Processing travel time matrices for {len(routes)} route directions...")

        for r_code, direction in routes:
            records = self.extract_route_direction_matrix(r_code, direction)
            if records:
                self.save_matrix_records(records)
                key = f"{r_code}_{direction}"
                summary[key] = len(records)
                total_records += len(records)
                print(f"  * Route {r_code:<6} [{direction:<6}] -> Extracted {len(records)} matrix cells")

        print(f"\n[DONE] Total matrix records persisted: {total_records:,}")
        return summary

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
                FROM dim_station_crosswalk
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
    print("HISTORICAL SEGMENT TRAVEL TIME MATRIX EXTRACTION")
    print("=" * 80)

    model = HistoricalSegmentAverageModel()

    # If --all passed or run directly, compute for all routes
    if len(sys.argv) > 1 and sys.argv[1] == "--route":
        r_code = sys.argv[2] if len(sys.argv) > 2 else "02"
        recs = model.extract_route_direction_matrix(r_code, "go")
        model.save_matrix_records(recs)
        print(f"Extracted {len(recs)} records for Route {r_code} [go].")
    else:
        summary = model.process_all_routes()

    # Test ETA query on Route 02
    eta_sec = model.predict_eta(
        route_code="02",
        direction="go",
        current_s_m=1200.0,
        target_station_order=5
    )
    print(f"\n[ETA INFERENCE TEST] Route 02 [go] at s=1200m -> Station #5: ETA = {eta_sec} seconds ({eta_sec/60:.1f} mins)")
