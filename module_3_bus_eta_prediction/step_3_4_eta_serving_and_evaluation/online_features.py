"""
Step 3.4 — OnlineFeatureExtractor: dựng vector 54 feature cấp serving.
Module: module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/online_features.py

Parity source of truth (FROZEN, chỉ đọc tham chiếu): 
`module_3_bus_eta_prediction/step_3_2_feature_store_extractor/feature_store_builder.py`.
Thứ tự 54 feature cố định theo SPEC-16 §1.3.2 / eta_model_trainer.ALL_54_FEATURES.
Cold-start dùng Baseline Inversion (SPEC-09 §4.2): v_roll3=v_roll5=v_inst, accel=0,
rec_seg=p50, rec_cov=0, rec_cong=1, next_seg_probe=1, T_elapsed=pref_p50[k]+(1-ρ)*p50[k], D_cum=0.

Các hằng số mô phỏng FROZEN builder không có trong SSOT được đặt tên tường minh ở đây.
"""

import math
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np

from config.system_config import (
    BASELINE_MAX_HOUR_SLOT,
    BASELINE_MIN_HOUR_SLOT,
    DAY_TYPE_SATURDAY,
    DAY_TYPE_SUNDAY,
    DAY_TYPE_WEEKDAY,
    FLEET_ACTIVE_WINDOW_SEC,
    GPS_DRIFT_MAX_SPEED_KMPH,
    PHYS_DECAY_M,
    PHYS_INC_DELAY_CAP,
    PHYS_INC_DELAY_FACTOR,
    PHYS_W_EGO,
    PHYS_W_PROBE,
    TZ_HANOI,
)
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.data_access import (
    DataAccess,
    IncidentsProvider,
)
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.dto import BusVehicleDTO
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.frenet import ShapeProjectionModel

# ---- Hằng số mô phỏng FROZEN feature_store_builder.py (không có tương đương trong SSOT) ----
_ROLL3_MIN_DT_SEC = 10.0
_ROLL5_MIN_DT_SEC = 15.0
_ACCEL_MIN_DT_MIN = 0.5
_RATIO_MIN_KMPH = 3.0
_RATIO_MIN = 0.1
_RATIO_MAX = 3.0
_FLEET_EPS_M = 20.0
_FLEET_DIST_DEFAULT_M = 25000.0
_HEADWAY_MAX_SEC = 3600.0
_HEADWAY_SPEED_FLOOR_MPS = 1.5
_PROBE_MIN = 0.3
_PROBE_MAX = 3.5
_EGO_DELAY_FACTOR_MIN = 0.70
_EGO_DELAY_FACTOR_MAX = 1.35
_EFF_EGO_MPS_MIN = 2.0
_EFF_EGO_MPS_MAX = 18.0
_EFF_EGO_W_OBS = 0.6
_EFF_EGO_W_BASE = 0.4
_PHYS_KIN_MAX_SEC = 7200.0
_INC_NEAR_DEFAULT_M = 25000.0
_INC_MIN_SPAN_M = 20.0
_INC_FRAC_MIN = 0.1
_RING_SIZE = 8

FAMILY_A: List[str] = [
    "route_id_idx", "direction_id", "current_station_order", "target_station_order", "day_type",
    "day_of_week", "hour_slot", "sin_time", "cos_time", "s_bus_m", "s_target_m", "remaining_distance_m",
    "n_stations_ahead", "progress_ratio", "target_progress_ratio", "dist_to_next_station_m",
    "ego_speed_instant_kmh", "ego_speed_roll3_kmh", "ego_speed_roll5_kmh", "ego_accel_kmh_per_min",
    "ego_speed_ratio_vs_baseline", "ego_trip_elapsed_sec", "ego_cum_delay_vs_baseline_sec",
]
FAMILY_B: List[str] = [
    "lead_bus_dist_ahead_m", "lead_bus_time_headway_sec", "lead_bus_speed_kmh", "lead_bus_speed_ratio",
    "follow_bus_dist_behind_m", "follow_bus_speed_kmh", "n_active_buses_on_route", "n_buses_in_corridor_ahead",
]
FAMILY_C: List[str] = [
    "recent_corridor_tt_sum_sec", "recent_corridor_congestion_ratio",
    "recent_seg_coverage_ratio", "recent_next_seg_congestion_ratio",
]
FAMILY_D: List[str] = [
    "baseline_eta_p50_sec", "baseline_eta_mean_sec", "baseline_eta_p10_sec", "baseline_eta_p90_sec",
    "baseline_eta_iqr_sec", "baseline_eta_rss_std_sec", "baseline_skew_sec",
    "baseline_max_seg_p90_sec", "baseline_tier0_frac",
]
FAMILY_E: List[str] = [
    "inc_ahead_count", "inc_ahead_total_delay_sec", "inc_ahead_max_delay_sec",
    "inc_ahead_max_magnitude", "inc_ahead_jam_length_m", "inc_dist_to_nearest_m",
]
FAMILY_F: List[str] = [
    "route_base_speed_kmh", "route_station_spacing_m",
    "physics_kinematic_eta_sec", "physics_probe_corrected_eta_sec",
]
ALL_54_FEATURES: List[str] = FAMILY_A + FAMILY_B + FAMILY_C + FAMILY_D + FAMILY_E + FAMILY_F

INT_FEATURES = {
    "route_id_idx", "direction_id", "current_station_order", "target_station_order", "day_type",
    "day_of_week", "hour_slot", "n_stations_ahead", "n_active_buses_on_route",
    "n_buses_in_corridor_ahead", "inc_ahead_count",
}


def _clip(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


class OnlineFeatureExtractor:
    """Dựng vector 54 feature cho 1 xe ego tại thời điểm hiện tại (state sống trong RAM tiến trình)."""

    def __init__(self, data_access: DataAccess, incidents_provider: Optional[IncidentsProvider] = None):
        self._da = data_access
        self._incidents = incidents_provider or IncidentsProvider()
        # (route_id, dir_int, vehicle_id) -> [(epoch, s_bus, speed_kmh), ...] (ring buffer)
        self._obs: Dict[Tuple[int, int, int], List[Tuple[float, float, float]]] = {}
        # (route_id, dir_int) -> {vehicle_id: (epoch, s_bus, speed_kmh, ratio)}
        self._fleet: Dict[Tuple[int, int], Dict[int, Tuple[float, float, float, float]]] = {}
        self._shape_models: Dict[Tuple[int, str], Optional[ShapeProjectionModel]] = {}

    # ------------------------------------------------------------------ state
    def _get_shape_model(self, route_id: int, dir_str: str) -> Optional[ShapeProjectionModel]:
        key = (route_id, dir_str)
        if key not in self._shape_models:
            points = self._da.get_shape_points(route_id, dir_str)
            self._shape_models[key] = ShapeProjectionModel.build(points) if len(points) >= 2 else None
        return self._shape_models[key]

    def update_observation(
        self, route_id: int, dir_int: int, vehicles: List[BusVehicleDTO], now_epoch: float
    ) -> None:
        """Cập nhật state nội bộ: RingBuffer(≤8) mỗi xe + snapshot fleet theo tuyến/chiều."""
        dir_str = "go" if dir_int == 0 else "re"
        shape_model = self._get_shape_model(route_id, dir_str)
        corridor = self._da.get_corridor_stations(route_id, dir_str)
        route_base_spd = self._da.get_route_profile(route_id, dir_str)[0]

        fleet: Dict[int, Tuple[float, float, float, float]] = {}
        if shape_model is not None and len(corridor) >= 2:
            st_s = [st[3] for st in corridor]
            day_type, hour_slot, _, _, _ = self._calendar(now_epoch)
            seg_p50 = self._segment_array(route_id, dir_int, corridor, day_type, hour_slot, route_base_spd, index=1)

            for v in vehicles:
                s_bus, _, _ = shape_model.project_point(v.lat, v.lng)
                ring_key = (route_id, dir_int, v.id)
                ring = self._obs.setdefault(ring_key, [])
                ring.append((now_epoch, s_bus, max(0.0, float(v.speed_kmh))))
                if len(ring) > _RING_SIZE:
                    del ring[: len(ring) - _RING_SIZE]

                k_curr = self._current_segment_index(st_s, s_bus)
                cur_base_spd = (max(1.0, st_s[k_curr + 1] - st_s[k_curr]) / max(1.0, seg_p50[k_curr])) * 3.6
                ratio = _clip(max(0.0, v.speed_kmh) / max(_RATIO_MIN_KMPH, cur_base_spd), _RATIO_MIN, _RATIO_MAX)
                fleet[v.id] = (now_epoch, s_bus, max(0.0, float(v.speed_kmh)), ratio)

        # Dọn fleet cũ theo cửa sổ hoạt động
        for v_id, (o_t, _, _, _) in list(fleet.items()):
            if now_epoch - o_t > FLEET_ACTIVE_WINDOW_SEC:
                del fleet[v_id]
        self._fleet[(route_id, dir_int)] = fleet

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _calendar(now_epoch: float) -> Tuple[int, int, int, float, float]:
        dt_obj = datetime.fromtimestamp(now_epoch, tz=TZ_HANOI)
        wd = dt_obj.weekday()
        day_type = DAY_TYPE_WEEKDAY if wd < 5 else (DAY_TYPE_SATURDAY if wd == 5 else DAY_TYPE_SUNDAY)
        hour_slot = min(BASELINE_MAX_HOUR_SLOT, max(BASELINE_MIN_HOUR_SLOT, dt_obj.hour))
        hour_float = dt_obj.hour + dt_obj.minute / 60.0
        return day_type, hour_slot, wd, math.sin(2.0 * math.pi * hour_float / 24.0), math.cos(2.0 * math.pi * hour_float / 24.0)

    @staticmethod
    def _current_segment_index(st_s: List[float], s_bus: float) -> int:
        n_seg = len(st_s) - 1
        k = int(np.searchsorted(st_s, s_bus, side="right")) - 1
        return min(n_seg - 1, max(0, k))

    def _segment_array(
        self, route_id: int, dir_int: int, corridor: List[Tuple[int, int, str, float]],
        day_type: int, hour_slot: int, route_base_spd_kmh: float, index: int,
    ) -> List[float]:
        """Mảng [p10,p50,p90,mean,var,t0,len][index] cho từng phân đoạn hành lang (parity feature_store)."""
        base_mps = route_base_spd_kmh / 3.6
        values: List[float] = []
        for m in range(len(corridor) - 1):
            o_a = corridor[m][0]
            o_b = corridor[m + 1][0]
            s_len = max(15.0, corridor[m + 1][3] - corridor[m][3])
            cell = self._da.get_baseline_cell(route_id, dir_int, o_a, o_b, day_type, hour_slot)
            if cell is not None:
                p10, p50, p90, mean_v, std_v, q_t, _ = cell
            else:
                p50 = s_len / max(1.0, base_mps)
                mean_v, p10, p90, std_v, q_t = p50, p50 * 0.75, p50 * 1.35, p50 * 0.2, 3
            arr = [float(p10), float(p50), float(p90), float(mean_v), float(std_v) ** 2, 1.0 if q_t == 0 else 0.0, s_len]
            values.append(arr[index])
        return values

    def _roll_speeds(self, route_id: int, dir_int: int, vehicle_id: int, s_bus: float, v_inst: float, now_epoch: float):
        """Trả (v_roll3, v_roll5, accel) theo feature_store; tự nhiên suy biến về cold-start khi thiếu ping."""
        ring = self._obs.get((route_id, dir_int, vehicle_id), [])
        if not ring:
            return v_inst, v_inst, 0.0
        s_cur = s_bus
        i_3 = ring[max(0, len(ring) - 4)]
        i_5 = ring[max(0, len(ring) - 6)]
        dt_3 = now_epoch - i_3[0]
        dt_5 = now_epoch - i_5[0]

        if dt_3 >= _ROLL3_MIN_DT_SEC:
            v_roll3 = min(GPS_DRIFT_MAX_SPEED_KMPH, max(0.0, ((s_cur - i_3[1]) / dt_3) * 3.6))
        else:
            v_roll3 = v_inst

        if dt_5 >= _ROLL5_MIN_DT_SEC:
            v_roll5 = min(GPS_DRIFT_MAX_SPEED_KMPH, max(0.0, ((s_cur - i_5[1]) / dt_5) * 3.6))
        else:
            v_roll5 = v_roll3

        dt_accel_min = max(_ACCEL_MIN_DT_MIN, dt_5 / 60.0) if dt_5 >= _ROLL5_MIN_DT_SEC else 1.0
        accel = (v_roll3 - v_roll5) / dt_accel_min
        return v_roll3, v_roll5, accel

    # ------------------------------------------------------------- build (54)
    def build_features(
        self, route_id: int, dir_int: int, vehicle: BusVehicleDTO,
        target_order: int, s_target_m: float, s_bus_m: float, now_epoch: float,
    ) -> Dict[str, float]:
        """Trả dict đủ 54 khóa theo ALL_54_FEATURES."""
        dir_str = "go" if dir_int == 0 else "re"
        corridor = self._da.get_corridor_stations(route_id, dir_str)
        if len(corridor) < 2:
            return {k: 0.0 for k in ALL_54_FEATURES}

        st_orders = [st[0] for st in corridor]
        st_s_vals = [st[3] for st in corridor]
        n_seg = len(st_s_vals) - 1
        r_len = self._da.get_route_profile(route_id, dir_str)[2]
        route_base_spd, r_spacing, _ = self._da.get_route_profile(route_id, dir_str)
        route_id_idx = self._da.get_route_idx(route_id) or 0

        day_type, hour_slot, wd, sin_t, cos_t = self._calendar(now_epoch)

        k_curr = self._current_segment_index(st_s_vals, s_bus_m)

        # Ánh xạ trạm đích về chỉ mục hành lang gần nhất theo lý trình.
        tk = int(np.searchsorted(st_s_vals, s_target_m, side="right")) - 1
        tk = min(len(st_s_vals) - 1, max(0, tk))
        if tk <= k_curr:
            tk = min(len(st_s_vals) - 1, k_curr + 1)
        n_hops = tk - k_curr

        a_p10 = self._segment_array(route_id, dir_int, corridor, day_type, hour_slot, route_base_spd, 0)
        a_p50 = self._segment_array(route_id, dir_int, corridor, day_type, hour_slot, route_base_spd, 1)
        a_p90 = self._segment_array(route_id, dir_int, corridor, day_type, hour_slot, route_base_spd, 2)
        a_mean = self._segment_array(route_id, dir_int, corridor, day_type, hour_slot, route_base_spd, 3)
        a_var = self._segment_array(route_id, dir_int, corridor, day_type, hour_slot, route_base_spd, 4)
        a_t0 = self._segment_array(route_id, dir_int, corridor, day_type, hour_slot, route_base_spd, 5)
        a_len = self._segment_array(route_id, dir_int, corridor, day_type, hour_slot, route_base_spd, 6)

        pref_p50 = [0.0] + list(np.cumsum(a_p50))
        pref_mean = [0.0] + list(np.cumsum(a_mean))
        pref_p10 = [0.0] + list(np.cumsum(a_p10))
        pref_p90 = [0.0] + list(np.cumsum(a_p90))
        pref_var = [0.0] + list(np.cumsum(a_var))
        pref_t0 = [0.0] + list(np.cumsum(a_t0))

        rem_in_seg = max(0.0, st_s_vals[k_curr + 1] - s_bus_m)
        rho = min(1.0, max(0.0, rem_in_seg / max(1.0, a_len[k_curr])))
        dist_to_next_st = max(0.0, st_s_vals[k_curr + 1] - s_bus_m)

        # (a) Ego state & kinematics
        v_inst = max(0.0, float(vehicle.speed_kmh))
        v_roll3, v_roll5, ego_accel = self._roll_speeds(route_id, dir_int, vehicle.id, s_bus_m, v_inst, now_epoch)
        cur_seg_base_spd = (a_len[k_curr] / max(1.0, a_p50[k_curr])) * 3.6
        ego_spd_ratio = _clip(v_roll3 / max(_RATIO_MIN_KMPH, cur_seg_base_spd), _RATIO_MIN, _RATIO_MAX)

        # Baseline inversion cho thời gian đã chạy & độ trễ (SPEC-09 §4.2, Phương án A).
        trip_elapsed = pref_p50[k_curr] + (1.0 - rho) * a_p50[k_curr]
        ego_cum_delay = 0.0

        # (d) Historical baseline (prefix-sum O(1))
        base_p50 = rho * a_p50[k_curr] + (pref_p50[tk] - pref_p50[k_curr + 1])
        base_mean = rho * a_mean[k_curr] + (pref_mean[tk] - pref_mean[k_curr + 1])
        base_p10 = rho * a_p10[k_curr] + (pref_p10[tk] - pref_p10[k_curr + 1])
        base_p90 = rho * a_p90[k_curr] + (pref_p90[tk] - pref_p90[k_curr + 1])
        base_iqr = max(1.0, base_p90 - base_p10)
        base_var = (rho ** 2) * a_var[k_curr] + (pref_var[tk] - pref_var[k_curr + 1])
        base_rss_std = math.sqrt(max(1.0, base_var))
        base_skew = base_mean - base_p50
        max_seg_p90 = max(a_p90[k_curr:tk]) if tk > k_curr else a_p90[k_curr]
        t0_frac = _clip((pref_t0[tk] - pref_t0[k_curr]) / max(1, n_hops), 0.0, 1.0)

        # (c) Recent preceding-bus probe — cold-start inversion (SPEC-09 §4.2).
        rec_tt_sum = base_p50
        rec_cov_ratio = 0.0
        rec_cong_ratio = 1.0
        next_seg_probe_ratio = 1.0

        # (b) Same-route fleet ahead & behind (1 snapshot hiện tại)
        fleet = self._fleet.get((route_id, dir_int), {})
        lead_dist, lead_spd, lead_ratio = _FLEET_DIST_DEFAULT_M, route_base_spd, 1.0
        follow_dist, follow_spd = _FLEET_DIST_DEFAULT_M, route_base_spd
        n_ahead = 0
        for o_id, (_, o_s, o_spd, o_rat) in fleet.items():
            if o_id == vehicle.id:
                continue
            ds_fleet = o_s - s_bus_m
            if ds_fleet > _FLEET_EPS_M:
                if o_s <= s_target_m:
                    n_ahead += 1
                if ds_fleet < lead_dist:
                    lead_dist, lead_spd, lead_ratio = ds_fleet, o_spd, o_rat
            elif ds_fleet < -_FLEET_EPS_M and -ds_fleet < follow_dist:
                follow_dist, follow_spd = -ds_fleet, o_spd
        n_active_route = len(fleet)
        lead_headway = min(_HEADWAY_MAX_SEC, lead_dist / max(_HEADWAY_SPEED_FLOOR_MPS, v_roll3 / 3.6))

        # (e) TomTom incidents chủ động bao phủ [s_bus, s_target]
        inc = self._incident_features(route_id, dir_str, s_bus_m, s_target_m, now_epoch)

        # (f) Route profile & physics interactions
        eff_ego_mps = _clip((_EFF_EGO_W_OBS * v_roll3 + _EFF_EGO_W_BASE * route_base_spd) / 3.6, _EFF_EGO_MPS_MIN, _EFF_EGO_MPS_MAX)
        phys_kin_eta = min(_PHYS_KIN_MAX_SEC, max(0.0, s_target_m - s_bus_m) / eff_ego_mps)
        w_probe = PHYS_W_PROBE * rec_cov_ratio
        w_ego = PHYS_W_EGO * math.exp(-max(0.0, s_target_m - s_bus_m) / PHYS_DECAY_M)
        ego_delay_factor = _clip(1.0 / max(1e-6, ego_spd_ratio), _EGO_DELAY_FACTOR_MIN, _EGO_DELAY_FACTOR_MAX)
        phys_probe_eta = (
            base_p50 * ((1.0 - w_probe - w_ego) + w_probe * rec_cong_ratio + w_ego * ego_delay_factor)
            + min(PHYS_INC_DELAY_CAP, PHYS_INC_DELAY_FACTOR * inc["inc_ahead_total_delay_sec"])
        )

        features: Dict[str, float] = {
            # (a)
            "route_id_idx": route_id_idx,
            "direction_id": dir_int,
            "current_station_order": st_orders[k_curr],
            "target_station_order": st_orders[tk],
            "day_type": day_type,
            "day_of_week": wd,
            "hour_slot": hour_slot,
            "sin_time": round(sin_t, 4),
            "cos_time": round(cos_t, 4),
            "s_bus_m": round(s_bus_m, 1),
            "s_target_m": round(s_target_m, 1),
            "remaining_distance_m": round(s_target_m - s_bus_m, 1),
            "n_stations_ahead": int(n_hops),
            "progress_ratio": round(s_bus_m / max(1.0, r_len), 4),
            "target_progress_ratio": round(s_target_m / max(1.0, r_len), 4),
            "dist_to_next_station_m": round(dist_to_next_st, 1),
            "ego_speed_instant_kmh": round(v_inst, 2),
            "ego_speed_roll3_kmh": round(v_roll3, 2),
            "ego_speed_roll5_kmh": round(v_roll5, 2),
            "ego_accel_kmh_per_min": round(ego_accel, 2),
            "ego_speed_ratio_vs_baseline": round(ego_spd_ratio, 3),
            "ego_trip_elapsed_sec": round(trip_elapsed, 1),
            "ego_cum_delay_vs_baseline_sec": round(ego_cum_delay, 1),
            # (b)
            "lead_bus_dist_ahead_m": round(lead_dist, 1),
            "lead_bus_time_headway_sec": round(lead_headway, 1),
            "lead_bus_speed_kmh": round(lead_spd, 2),
            "lead_bus_speed_ratio": round(lead_ratio, 3),
            "follow_bus_dist_behind_m": round(follow_dist, 1),
            "follow_bus_speed_kmh": round(follow_spd, 2),
            "n_active_buses_on_route": int(n_active_route),
            "n_buses_in_corridor_ahead": int(n_ahead),
            # (c)
            "recent_corridor_tt_sum_sec": round(rec_tt_sum, 2),
            "recent_corridor_congestion_ratio": round(rec_cong_ratio, 3),
            "recent_seg_coverage_ratio": round(rec_cov_ratio, 3),
            "recent_next_seg_congestion_ratio": round(next_seg_probe_ratio, 3),
            # (d)
            "baseline_eta_p50_sec": round(base_p50, 2),
            "baseline_eta_mean_sec": round(base_mean, 2),
            "baseline_eta_p10_sec": round(base_p10, 2),
            "baseline_eta_p90_sec": round(base_p90, 2),
            "baseline_eta_iqr_sec": round(base_iqr, 2),
            "baseline_eta_rss_std_sec": round(base_rss_std, 2),
            "baseline_skew_sec": round(base_skew, 2),
            "baseline_max_seg_p90_sec": round(max_seg_p90, 2),
            "baseline_tier0_frac": round(t0_frac, 3),
            # (e)
            "inc_ahead_count": int(inc["inc_ahead_count"]),
            "inc_ahead_total_delay_sec": round(inc["inc_ahead_total_delay_sec"], 1),
            "inc_ahead_max_delay_sec": round(inc["inc_ahead_max_delay_sec"], 1),
            "inc_ahead_max_magnitude": round(inc["inc_ahead_max_magnitude"], 1),
            "inc_ahead_jam_length_m": round(inc["inc_ahead_jam_length_m"], 1),
            "inc_dist_to_nearest_m": round(inc["inc_dist_to_nearest_m"], 1),
            # (f)
            "route_base_speed_kmh": float(route_base_spd),
            "route_station_spacing_m": float(r_spacing),
            "physics_kinematic_eta_sec": round(phys_kin_eta, 2),
            "physics_probe_corrected_eta_sec": round(phys_probe_eta, 2),
        }
        return features

    def _incident_features(self, route_id: int, dir_str: str, s_cur: float, s_target: float, now_epoch: float) -> Dict[str, float]:
        """(e) Sự cố TomTom đang hiệu lực, chồng lấn [s_cur, s_target]; thiếu dữ liệu -> 0/25000."""
        out = {
            "inc_ahead_count": 0, "inc_ahead_total_delay_sec": 0.0, "inc_ahead_max_delay_sec": 0.0,
            "inc_ahead_max_magnitude": 0.0, "inc_ahead_jam_length_m": 0.0, "inc_dist_to_nearest_m": _INC_NEAR_DEFAULT_M,
        }
        inc_list = self._incidents.get_incidents(self._da.get_route_code(route_id)).get(dir_str, [])
        near = _INC_NEAR_DEFAULT_M
        for ep in inc_list:
            t_start, t_end, s_min, s_max, delay, mag, _ = ep
            if not (t_start <= now_epoch <= t_end):
                continue
            ov_l = min(s_target, s_max) - max(s_cur, s_min)
            if ov_l < 0.0:
                continue
            out["inc_ahead_count"] += 1
            span_l = max(_INC_MIN_SPAN_M, s_max - s_min)
            frac = _clip(ov_l / span_l, _INC_FRAC_MIN, 1.0)
            out["inc_ahead_total_delay_sec"] += delay * frac
            out["inc_ahead_max_delay_sec"] = max(out["inc_ahead_max_delay_sec"], delay)
            out["inc_ahead_max_magnitude"] = max(out["inc_ahead_max_magnitude"], mag)
            out["inc_ahead_jam_length_m"] += ov_l
            near = min(near, max(0.0, s_min - s_cur))
        out["inc_dist_to_nearest_m"] = near
        return out
