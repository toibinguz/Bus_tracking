"""
Module 3 - Step 3.5: Real-time Online Feature Extractor (Zero Train/Serve Skew Engine).
Directly extracts the exact 54-feature vector (x in R^54) required by the trained XGBoost model
from live incoming GPS telemetry pings or BusMap route snapshots.

Complies strictly with AGENTS.md, docs/06_ETA_INFERENCE_ENGINE_SPEC.md,
and docs/07_ONLINE_FEATURE_EXTRACTOR_AND_SERVING_SPEC.md.
Shares exact mathematical formulas and prefix-sum O(1) structures with feature_store_builder.py.
"""

import math
import os
import sqlite3
import sys
import time
from collections import defaultdict, deque
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

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
    DEFAULT_URBAN_BUS_SPEED_KMPH,
    METERS_PER_DEG_LAT,
    METERS_PER_DEG_LON_EQUATOR,
    TZ_HANOI,
)
from module_3_bus_eta_prediction.step_3_3_machine_learning_models.eta_model_trainer import (
    ALL_54_FEATURES,
)

INT32_COLS = [
    "current_station_order", "target_station_order", "route_id_idx", "direction_id",
    "day_type", "day_of_week", "hour_slot", "n_stations_ahead",
    "n_active_buses_on_route", "n_buses_in_corridor_ahead", "inc_ahead_count",
]

RECENT_PROBE_WINDOW_SEC = 1800.0   # 30-minute causal window for preceding bus segment traversals
FLEET_ACTIVE_WINDOW_SEC = 300.0    # 5-minute causal window for active lead/following buses on same route
MAX_TRACE_HISTORY = 10             # Retain up to 10 recent pings per vehicle in memory


class OnlineFeatureExtractor:
    """
    High-performance real-time feature extractor for live bus telemetry.
    Preloads static Master Ground Truth & Baseline Matrix into memory at startup.
    Maintains rolling active fleet and preceding-bus probe states.
    Produces exact 54-dimensional feature DataFrames with 0 train/serve skew.
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        if not os.path.isabs(db_path):
            db_path = os.path.join(BASE_DIR, db_path)
        self.db_path = db_path
        if not os.path.exists(self.db_path):
            raise FileNotFoundError(f"Database not found at {self.db_path}")

        # 1. Preload static tables
        self._preload_static_ground_truth()
        self._preload_baseline_matrices()

        # 2. Dynamic in-memory rolling states
        # Key: (route_code, dir_str) -> {vid: (epoch, s_bus_m, v_roll3, ego_spd_ratio)}
        self.active_fleet: Dict[Tuple[str, str], Dict[str, Tuple[float, float, float, float]]] = defaultdict(dict)

        # Key: (route_code, dir_str) -> (latest_seg_tt: np.ndarray, latest_seg_epoch: np.ndarray)
        self.latest_seg: Dict[Tuple[str, str], Tuple[np.ndarray, np.ndarray]] = {}
        for (rc, ds), st_list in self.stations_by_dir.items():
            n_seg = max(1, len(st_list) - 1)
            tt_arr = np.full(n_seg, np.nan, dtype=np.float64)
            ep_arr = np.full(n_seg, -1e12, dtype=np.float64)
            self.latest_seg[(rc, ds)] = (tt_arr, ep_arr)

        # Key: (route_code, dir_str) -> List[Tuple[t_start, t_end, s_min, s_max, delay_sec, magnitude, overlap_len]]
        self.active_incidents: Dict[Tuple[str, str], List[Tuple[float, float, float, float, float, float, float]]] = defaultdict(list)

        # Vehicle traces: vid -> deque of (epoch, s_bus_m, speed_kmh)
        self.vehicle_traces: Dict[str, deque] = defaultdict(lambda: deque(maxlen=MAX_TRACE_HISTORY))

    def _preload_static_ground_truth(self) -> None:
        """Preloads canonical routes, shapes, and stations into fast memory structures."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        # 1. Routes
        self.route_meta: Dict[str, Dict[str, Any]] = {}
        routes = cur.execute(
            "SELECT route_code, route_id, route_name FROM canonical_route_master ORDER BY route_code"
        ).fetchall()
        for idx, (rc, r_id, r_name) in enumerate(routes):
            self.route_meta[str(rc)] = {
                "route_id": int(r_id),
                "route_id_idx": int(idx),
                "route_name": str(r_name),
            }

        # 2. Stations
        self.stations_by_dir: Dict[Tuple[str, str], List[Tuple[int, int, str, float]]] = defaultdict(list)
        self.station_coords: Dict[Tuple[str, str, int], Tuple[float, float]] = {}
        self.station_details: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
        st_rows = cur.execute(
            """
            SELECT route_code, direction, station_order, station_id, station_name, lat, lon, cum_distance_m
            FROM canonical_station_master
            ORDER BY route_code, direction, station_order
            """
        ).fetchall()
        for rc, dir_raw, s_ord, s_id, s_name, lat, lon, s_m in st_rows:
            d_str = "go" if str(dir_raw) in ("0", "go", "Chiều đi") else "re"
            k_rd = (str(rc), d_str)
            self.stations_by_dir[k_rd].append(
                (int(s_ord), int(s_id), str(s_name), float(s_m))
            )
            self.station_coords[(str(rc), d_str, int(s_ord))] = (float(lat), float(lon))
            self.station_details[k_rd].append({
                "station_order": int(s_ord),
                "station_id": int(s_id),
                "station_name": str(s_name),
                "lat": float(lat),
                "lon": float(lon),
                "cum_distance_m": float(s_m),
            })

        # Precompute station distance arrays and order mappings
        self.st_s_vals: Dict[Tuple[str, str], np.ndarray] = {}
        self.st_orders: Dict[Tuple[str, str], np.ndarray] = {}
        self.ord_to_k: Dict[Tuple[str, str], Dict[int, int]] = {}
        for k_rd, st_list in self.stations_by_dir.items():
            self.st_s_vals[k_rd] = np.array([st[3] for st in st_list], dtype=np.float64)
            self.st_orders[k_rd] = np.array([st[0] for st in st_list], dtype=np.int32)
            self.ord_to_k[k_rd] = {int(st[0]): i for i, st in enumerate(st_list)}

        # 3. Shapes & Route lengths
        self.route_shape_pts: Dict[Tuple[str, str], List[Tuple[int, float, float, float]]] = defaultdict(list)
        self.route_shape_len: Dict[Tuple[str, str], float] = {}
        shape_rows = cur.execute(
            """
            SELECT crm.route_code, csm.direction, csm.point_order, csm.lat, csm.lon, csm.cum_distance_m
            FROM canonical_shape_master csm
            JOIN canonical_route_master crm ON csm.route_id = crm.route_id
            ORDER BY crm.route_code, csm.direction, csm.point_order
            """
        ).fetchall()
        for rc, dir_raw, pt_ord, lat, lon, s_m in shape_rows:
            d_str = "go" if str(dir_raw) in ("0", "go", "Chiều đi") else "re"
            self.route_shape_pts[(str(rc), d_str)].append(
                (int(pt_ord), float(lat), float(lon), float(s_m))
            )
            self.route_shape_len[(str(rc), d_str)] = max(
                self.route_shape_len.get((str(rc), d_str), 0.0), float(s_m)
            )

        conn.close()

    def _preload_baseline_matrices(self) -> None:
        """Preloads agg_segment_travel_times into O(1) prefix sum arrays per (day_type, hr_slot)."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        bm_cells: Dict[Tuple[str, str, int, int, int, int], Tuple[float, float, float, float, float, int, float]] = {}
        bm_rows = cur.execute(
            """
            SELECT route_code, direction, from_station_order, to_station_order, day_type, hour_slot,
                   tt_p50_sec, tt_mean_sec, tt_p10_sec, tt_p90_sec, tt_std_sec, quality_tier, segment_length_m
            FROM agg_segment_travel_times
            """
        ).fetchall()
        for (
            rc, dir_raw, o_a, o_b, dt_v, hr_v,
            p50, mean_v, p10, p90, std_v, q_t, s_len
        ) in bm_rows:
            d_str = "go" if str(dir_raw) in ("0", "go", "Chiều đi") else "re"
            bm_cells[(str(rc), d_str, int(o_a), int(o_b), int(dt_v), int(hr_v))] = (
                float(p50), float(mean_v), float(p10), float(p90),
                float(std_v) if std_v is not None else 0.0,
                int(q_t), float(s_len)
            )

        conn.close()

        # Build route profile and O(1) prefix arrays
        self.route_profile: Dict[Tuple[str, str], Tuple[float, float]] = {}
        self.bm_arrays: Dict[Tuple[str, str, int, int], Dict[str, np.ndarray]] = {}

        for (rc, d_str), st_list in self.stations_by_dir.items():
            m_st = len(st_list)
            if m_st < 2:
                continue
            n_seg = m_st - 1
            corridor_len = max(100.0, st_list[-1][3] - st_list[0][3])
            r_spacing_m = round(corridor_len / max(1, n_seg), 1)

            # Route base speed from day_type=0, hr_slot=12 (or average of cells)
            tot_d = 0.0
            tot_t = 0.0
            for k in range(n_seg):
                c = bm_cells.get((rc, d_str, st_list[k][0], st_list[k + 1][0], DAY_TYPE_WEEKDAY, 12))
                if c:
                    tot_d += c[6]
                    tot_t += c[0]
            r_base_spd_kmh = round((tot_d / tot_t) * 3.6, 2) if tot_t > 0 else DEFAULT_URBAN_BUS_SPEED_KMPH
            self.route_profile[(rc, d_str)] = (r_base_spd_kmh, r_spacing_m)
            base_spd_mps = r_base_spd_kmh / 3.6

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
                        cell = bm_cells.get((rc, d_str, o_a, o_b, dt_v, hr_v))
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

                    self.bm_arrays[(rc, d_str, dt_v, hr_v)] = {
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

    def project_coordinate(
        self, route_code: str, direction: str, lat: float, lon: float
    ) -> Tuple[float, float, bool]:
        """
        Projects (lat, lon) onto the route shape polyline using local tangent plane coordinates.
        Returns: (s_bus_m, cross_track_m, is_on_corridor) where is_on_corridor is True if d_perp <= 35.0m.
        """
        d_str = "go" if str(direction) in ("0", "go", "Chiều đi") else "re"
        shape = self.route_shape_pts.get((str(route_code), d_str), [])
        if len(shape) < 2:
            return (0.0, 999.0, False)

        s_lats = np.array([p[1] for p in shape], dtype=np.float64)
        s_lons = np.array([p[2] for p in shape], dtype=np.float64)
        s_cums = np.array([p[3] for p in shape], dtype=np.float64)

        mean_lat = np.mean(s_lats)
        kx = METERS_PER_DEG_LON_EQUATOR * math.cos(math.radians(mean_lat))
        ky = METERS_PER_DEG_LAT

        x1 = s_lons[:-1] * kx
        y1 = s_lats[:-1] * ky
        x2 = s_lons[1:] * kx
        y2 = s_lats[1:] * ky

        dx = x2 - x1
        dy = y2 - y1
        seg_lens_sq = dx * dx + dy * dy
        safe_lens_sq = np.maximum(seg_lens_sq, 1e-6)

        px = lon * kx
        py = lat * ky

        vx = px - x1
        vy = py - y1

        t = np.clip((vx * dx + vy * dy) / safe_lens_sq, 0.0, 1.0)
        proj_x = x1 + t * dx
        proj_y = y1 + t * dy

        dist_sq = (px - proj_x) ** 2 + (py - proj_y) ** 2
        best_idx = int(np.argmin(dist_sq))

        d_perp = float(math.sqrt(dist_sq[best_idx]))
        s_bus = float(s_cums[best_idx] + t[best_idx] * math.sqrt(safe_lens_sq[best_idx]))
        is_on_corridor = (d_perp <= 35.0)

        return (s_bus, d_perp, is_on_corridor)

    def get_terminal_gate_status(
        self, route_code: str, direction: str, s_bus_m: float
    ) -> str:
        """
        TD-19 Terminal Gate classifier:
          - 'AT_ORIGIN_TERMINAL'      : s_bus_m < s_station[1] (waiting for dispatch / staging)
          - 'AT_DESTINATION_TERMINAL' : s_bus_m >= s_station[N-1] (entered destination gate)
          - 'ACTIVE_IN_TRANSIT'       : s_station[1] <= s_bus_m < s_station[N-1] (eligible for kinematic ETA)
        """
        d_str = "go" if str(direction) in ("0", "go", "Chiều đi") else "re"
        st_list = self.stations_by_dir.get((str(route_code), d_str), [])
        if len(st_list) >= 4:
            if s_bus_m < st_list[1][3]:
                return "AT_ORIGIN_TERMINAL"
            if s_bus_m >= st_list[-2][3]:
                return "AT_DESTINATION_TERMINAL"
        return "ACTIVE_IN_TRANSIT"

    def update_vehicle_ping(
        self,
        route_code: str,
        direction: str,
        vehicle_id: str,
        device_epoch: float,
        s_bus_m: float,
        speed_kmh: float,
    ) -> Tuple[float, float, float, float]:
        """
        Updates rolling kinematic buffer for a vehicle.
        Returns: (v_roll3, v_roll5, ego_accel, ego_spd_ratio).
        """
        d_str = "go" if str(direction) in ("0", "go", "Chiều đi") else "re"
        trace = self.vehicle_traces[str(vehicle_id)]
        trace.append((device_epoch, s_bus_m, speed_kmh))

        v_inst = max(0.0, speed_kmh)
        n_p = len(trace)

        if n_p >= 4:
            dt_3 = device_epoch - trace[-4][0]
            ds_3 = s_bus_m - trace[-4][1]
            v_roll3 = min(80.0, max(0.0, (ds_3 / dt_3) * 3.6 if dt_3 >= 10.0 else v_inst))
        else:
            v_roll3 = v_inst

        if n_p >= 6:
            dt_5 = device_epoch - trace[-6][0]
            ds_5 = s_bus_m - trace[-6][1]
            v_roll5 = min(80.0, max(0.0, (ds_5 / dt_5) * 3.6 if dt_5 >= 15.0 else v_roll3))
            dt_accel_min = max(0.5, dt_5 / 60.0)
            ego_accel = (v_roll3 - v_roll5) / dt_accel_min
        else:
            v_roll5 = v_roll3
            ego_accel = 0.0

        r_base_spd_kmh, _ = self.route_profile.get((route_code, d_str), (DEFAULT_URBAN_BUS_SPEED_KMPH, 500.0))
        ego_spd_ratio = min(3.0, max(0.1, v_roll3 / max(3.0, r_base_spd_kmh)))

        # Update active fleet buffer
        self.active_fleet[(route_code, d_str)][str(vehicle_id)] = (
            device_epoch, s_bus_m, v_roll3, ego_spd_ratio
        )

        return (v_roll3, v_roll5, ego_accel, ego_spd_ratio)

    def update_segment_completion(
        self,
        route_code: str,
        direction: str,
        to_station_order: int,
        tt_seg_sec: float,
        completion_epoch: float,
    ) -> None:
        """Updates recent segment completion buffer for preceding bus probe features (Family c)."""
        d_str = "go" if str(direction) in ("0", "go", "Chiều đi") else "re"
        key = (str(route_code), d_str)
        if key not in self.ord_to_k:
            return
        k_map = self.ord_to_k[key]
        if to_station_order not in k_map:
            return
        k_dest = k_map[to_station_order]
        k_seg = k_dest - 1
        if 0 <= k_seg < len(self.latest_seg[key][0]):
            self.latest_seg[key][0][k_seg] = tt_seg_sec
            self.latest_seg[key][1][k_seg] = completion_epoch

    def extract_features_for_ego(
        self,
        route_code: str,
        direction: str,
        vehicle_id: str,
        device_epoch: float,
        s_bus_m: float,
        speed_kmh: float,
        target_station_order: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        Extracts the exact 54 features for a vehicle to a specific target station,
        or for all upcoming corridor stations (k_curr + 1 .. N - 1) if target_station_order is None.
        Returns pd.DataFrame with columns matching ALL_54_FEATURES.
        """
        r_code = str(route_code)
        d_str = "go" if str(direction) in ("0", "go", "Chiều đi") else "re"
        dir_id = 0 if d_str == "go" else 1

        if r_code not in self.route_meta:
            raise KeyError(f"Tuyến route_code '{r_code}' không tồn tại trong canonical_route_master")
        r_id_idx = self.route_meta[r_code]["route_id_idx"]

        key = (r_code, d_str)
        st_list = self.stations_by_dir.get(key, [])
        m_st = len(st_list)
        if m_st < 3:
            return pd.DataFrame(columns=ALL_54_FEATURES)

        n_seg = m_st - 1
        st_s_vals = self.st_s_vals[key]
        st_orders = self.st_orders[key]
        r_len = self.route_shape_len.get(key, st_s_vals[-1])
        r_base_spd_kmh, r_spacing_m = self.route_profile.get(key, (DEFAULT_URBAN_BUS_SPEED_KMPH, 500.0))

        # 1. Update kinematics
        v_roll3, v_roll5, ego_accel, ego_spd_ratio = self.update_vehicle_ping(
            r_code, d_str, vehicle_id, device_epoch, s_bus_m, speed_kmh
        )
        v_inst = max(0.0, speed_kmh)

        # 2. Time & Calendar features
        dt_obj = datetime.fromtimestamp(device_epoch, tz=TZ_HANOI)
        wd = dt_obj.weekday()
        day_type = DAY_TYPE_WEEKDAY if wd < 5 else (DAY_TYPE_SATURDAY if wd == 5 else DAY_TYPE_SUNDAY)
        hr_slot = min(BASELINE_MAX_HOUR_SLOT, max(BASELINE_MIN_HOUR_SLOT, dt_obj.hour))
        hour_float = dt_obj.hour + dt_obj.minute / 60.0
        sin_t = math.sin(2.0 * math.pi * hour_float / 24.0)
        cos_t = math.cos(2.0 * math.pi * hour_float / 24.0)

        # 3. Spatial current position
        k_curr = int(np.searchsorted(st_s_vals, s_bus_m, side="right")) - 1
        k_curr = min(n_seg - 1, max(0, k_curr))

        # Determine target station indices
        if target_station_order is not None:
            if target_station_order not in self.ord_to_k[key]:
                raise ValueError(f"target_station_order {target_station_order} không thuộc tuyến {r_code}")
            tk_target = self.ord_to_k[key][target_station_order]
            if tk_target <= k_curr:
                return pd.DataFrame(columns=ALL_54_FEATURES)
            target_indices = [tk_target]
        else:
            # All upcoming stations on corridor (up to terminal N - 1)
            target_indices = list(range(k_curr + 1, m_st))

        if not target_indices:
            return pd.DataFrame(columns=ALL_54_FEATURES)

        # 4. Fleet Ahead & Behind features (Family b)
        active_f = self.active_fleet[key]
        stale_vids = [vk for vk, vv in active_f.items() if device_epoch - vv[0] > FLEET_ACTIVE_WINDOW_SEC]
        for sv in stale_vids:
            del active_f[sv]

        lead_dist = 25000.0
        lead_spd = r_base_spd_kmh
        lead_ratio = 1.0
        follow_dist = 25000.0
        follow_spd = r_base_spd_kmh
        other_ahead_s: List[float] = []

        for other_vid, (o_t, o_s, o_spd, o_rat) in active_f.items():
            if other_vid == str(vehicle_id):
                continue
            ds_fleet = o_s - s_bus_m
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

        n_active_route = len(active_f)
        lead_headway_sec = min(3600.0, lead_dist / max(1.5, v_roll3 / 3.6))

        # 5. Baseline matrix prefix sum arrays (Family d)
        bm_slice = self.bm_arrays[(r_code, d_str, day_type, hr_slot)]
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

        dist_to_next_st = max(0.0, float(st_s_vals[k_curr + 1] - s_bus_m))
        alpha_curr = min(1.0, max(0.0, dist_to_next_st / a_len[k_curr]))

        trace_pts = self.vehicle_traces[str(vehicle_id)]
        trip_elapsed = max(0.0, device_epoch - trace_pts[0][0]) if trace_pts else 0.0
        first_s = trace_pts[0][1] if trace_pts else s_bus_m
        first_k = min(n_seg - 1, max(0, int(np.searchsorted(st_s_vals, first_s, side="right")) - 1))
        if k_curr > first_k:
            ego_cum_delay = max(-600.0, min(1800.0, trip_elapsed - float(pref_p50[k_curr] - pref_p50[first_k])))
        else:
            ego_cum_delay = 0.0

        # 6. Recent Preceding-Bus Probe features (Family c)
        latest_tt, latest_epoch = self.latest_seg[key]
        fresh_mask = ((device_epoch - latest_epoch) <= RECENT_PROBE_WINDOW_SEC) & (~np.isnan(latest_tt))
        eff_rec_seg = np.where(fresh_mask, latest_tt, a_p50)
        pref_rec_tt = np.concatenate(([0.0], np.cumsum(eff_rec_seg)))
        pref_rec_cov = np.concatenate(([0], np.cumsum(fresh_mask.astype(np.int32))))
        next_seg_probe_ratio = min(3.5, max(0.3, float(eff_rec_seg[k_curr] / max(1.0, a_p50[k_curr]))))
        eff_ego_mps = max(2.0, min(18.0, (0.6 * v_roll3 + 0.4 * r_base_spd_kmh) / 3.6))

        # 7. Active TomTom incidents (Family e)
        active_incs = self.active_incidents.get(key, [])
        live_incs = [ep for ep in active_incs if ep[0] <= device_epoch <= ep[1]]

        feature_rows: List[List[Any]] = []

        for tk in target_indices:
            s_target = float(st_s_vals[tk])
            rem_dist = max(0.0, s_target - s_bus_m)
            n_hops = tk - k_curr

            # (d) Baseline features
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

            # (c) Recent probe features
            rec_tt_sum = float(alpha_curr * eff_rec_seg[k_curr] + (pref_rec_tt[tk] - pref_rec_tt[k_curr + 1]))
            rec_cov_cnt = int(pref_rec_cov[tk] - pref_rec_cov[k_curr])
            rec_cong_ratio = min(3.5, max(0.3, rec_tt_sum / max(1.0, base_p50)))
            rec_cov_ratio = rec_cov_cnt / max(1, n_hops)

            # (b) Corridor buses ahead
            n_buses_corridor = sum(1 for os_v in other_ahead_s if os_v <= s_target)

            # (e) Incident overlap
            inc_cnt = 0
            inc_tot_delay = 0.0
            inc_max_delay = 0.0
            inc_max_mag = 0.0
            inc_jam_len = 0.0
            inc_near_dist = 25000.0
            if live_incs:
                for _, _, ep_s0, ep_s1, ep_del, ep_mag, _ in live_incs:
                    ov_s0 = max(s_bus_m, ep_s0)
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
                        d_near = max(0.0, ep_s0 - s_bus_m)
                        if d_near < inc_near_dist:
                            inc_near_dist = d_near

            # (f) Physics features
            phys_kin_eta = min(7200.0, rem_dist / eff_ego_mps)
            w_probe = 0.35 * rec_cov_ratio
            w_ego = 0.20 * math.exp(-rem_dist / 2500.0)
            ego_delay_factor = min(1.35, max(0.70, 1.0 / ego_spd_ratio))
            phys_probe_eta = (
                base_p50 * ((1.0 - w_probe - w_ego) + w_probe * rec_cong_ratio + w_ego * ego_delay_factor)
                + min(180.0, 0.25 * inc_tot_delay)
            )

            # Build single row matching ALL_54_FEATURES exactly
            row = [
                # Family a (23)
                int(r_id_idx),
                int(dir_id),
                int(st_orders[k_curr]),
                int(st_orders[tk]),
                int(day_type),
                int(wd),
                int(hr_slot),
                round(sin_t, 4),
                round(cos_t, 4),
                round(s_bus_m, 1),
                round(s_target, 1),
                round(rem_dist, 1),
                int(n_hops),
                round(s_bus_m / max(1.0, r_len), 4),
                round(s_target / max(1.0, r_len), 4),
                round(dist_to_next_st, 1),
                round(v_inst, 2),
                round(v_roll3, 2),
                round(v_roll5, 2),
                round(ego_accel, 2),
                round(ego_spd_ratio, 3),
                round(trip_elapsed, 1),
                round(ego_cum_delay, 1),
                # Family b (8)
                round(lead_dist, 1),
                round(lead_headway_sec, 1),
                round(lead_spd, 2),
                round(lead_ratio, 3),
                round(follow_dist, 1),
                round(follow_spd, 2),
                int(n_active_route),
                int(n_buses_corridor),
                # Family c (4)
                round(rec_tt_sum, 2),
                round(rec_cong_ratio, 3),
                round(rec_cov_ratio, 3),
                round(next_seg_probe_ratio, 3),
                # Family d (9)
                round(base_p50, 2),
                round(base_mean, 2),
                round(base_p10, 2),
                round(base_p90, 2),
                round(base_iqr, 2),
                round(base_rss_std, 2),
                round(base_skew, 2),
                round(max_seg_p90, 2),
                round(t0_frac, 3),
                # Family e (6)
                int(inc_cnt),
                round(inc_tot_delay, 1),
                round(inc_max_delay, 1),
                round(inc_max_mag, 1),
                round(inc_jam_len, 1),
                round(inc_near_dist, 1),
                # Family f (4)
                float(r_base_spd_kmh),
                float(r_spacing_m),
                round(phys_kin_eta, 2),
                round(phys_probe_eta, 2),
            ]
            feature_rows.append(row)

        df_feat = pd.DataFrame(feature_rows, columns=ALL_54_FEATURES)
        for col in ALL_54_FEATURES:
            if col in INT32_COLS:
                df_feat[col] = df_feat[col].astype(np.int32)
            else:
                df_feat[col] = df_feat[col].astype(np.float32)

        return df_feat
