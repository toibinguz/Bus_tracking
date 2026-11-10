"""
Step 3.4 — Chính sách ETA (policy P1-P7/P9/P10, SPEC-16 §2.10).
Module: module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/eta_policy.py

Không I/O mạng, không I/O DB trực tiếp (dùng DataAccess được tiêm). Dead-reckoning (P8) đã HOÃN:
vị trí dùng thẳng sau lọc (staleness/corridor/heading), KHÔNG nội suy/ngoại suy.
ETA_core_p50 = ML (calibrated) nếu khả dụng, ngược lại baseline_p50. P10/P90 lấy từ ma trận baseline.
"""

import math
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple

from config.system_config import (
    BUFFER_ALPHA_SIGMA,
    BUFFER_BETA_TELEMETRY,
    BUFFER_GAMMA_HORIZON,
    CONGESTION_SPEED_THRESHOLD_KMPH,
    FREEFLOW_SPEED_THRESHOLD_KMPH,
    HEADING_COS_SIMILARITY_MIN,
    HEADING_MIN_SPEED_KMPH,
    MAX_CORRIDOR_CROSS_TRACK_M,
    MAX_SAFE_BUFFER_CEILING_SEC,
    MAX_TELEMETRY_STALE_SEC,
    REALTIME_DELAY_ALERT_SEC,
    STATION_BUFFER_ATTEN_MAX_M,
    STATION_BUFFER_ATTEN_MIN_M,
    TELEMETRY_HEARTBEAT_SEC,
    TZ_HANOI,
)
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.dto import (
    ApproachingBusDTO,
    BusVehicleDTO,
    SafeWindowDTO,
    StationItemDTO,
)
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.frenet import ShapeProjectionModel
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.live_feed import parse_ping_epoch


@dataclass
class BusState:
    """Trạng thái xe sau lọc (staleness/corridor/heading) — chưa dead-reckoning (P8 hoãn)."""

    vehicle: BusVehicleDTO
    s_now: float
    d_station: float
    v_obs_mps: float
    delta_t_age: float
    t_ping: float
    seg_idx: int
    ping_time: str


def _format_hms(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=TZ_HANOI).strftime("%H:%M:%S")


def project_filter_extrapolate(
    vehicle: BusVehicleDTO,
    shape_model: ShapeProjectionModel,
    s_target: float,
    now_epoch: float,
) -> Optional[BusState]:
    """SPEC-15 §8.1 (P4 staleness, P3 corridor, P5 heading, station clamp). Dead-reckoning hoãn."""
    t_ping, ping_time_str = parse_ping_epoch(vehicle.updated_at, now_epoch)
    delta_t_age = max(0.0, now_epoch - t_ping)
    if delta_t_age > MAX_TELEMETRY_STALE_SEC:
        return None  # Xe ma tắt máy/mất sóng > 5 phút

    s_ping, d_perp, seg_idx = shape_model.project_point(vehicle.lat, vehicle.lng)
    if d_perp > MAX_CORRIDOR_CROSS_TRACK_M:
        return None  # Lệch hành lang tuyến

    if vehicle.speed_kmh >= HEADING_MIN_SPEED_KMPH and vehicle.deg is not None:
        u_route_x, u_route_y = shape_model.segment_unit_tangent(seg_idx)
        theta_rad = math.radians(vehicle.deg)
        u_bus_x = math.sin(theta_rad)
        u_bus_y = math.cos(theta_rad)
        if u_bus_x * u_route_x + u_bus_y * u_route_y < HEADING_COS_SIMILARITY_MIN:
            return None  # Xe chạy ngược chiều

    # P8 hoãn: s_now = s_ping (không ngoại suy).
    s_now = s_ping
    if s_now > s_target:
        return None  # Xe đã rời trạm

    return BusState(
        vehicle=vehicle,
        s_now=s_now,
        d_station=s_target - s_now,
        v_obs_mps=max(0.0, vehicle.speed_kmh / 3.6),
        delta_t_age=delta_t_age,
        t_ping=t_ping,
        seg_idx=seg_idx,
        ping_time=ping_time_str,
    )


def _kappa(d_station: float) -> float:
    """Hàm bao suy giảm độ đệm cận bến smoothstep bậc 2 (P3)."""
    if d_station > STATION_BUFFER_ATTEN_MAX_M:
        return 1.0
    if d_station <= STATION_BUFFER_ATTEN_MIN_M:
        return 0.0
    xi = (d_station - STATION_BUFFER_ATTEN_MIN_M) / (STATION_BUFFER_ATTEN_MAX_M - STATION_BUFFER_ATTEN_MIN_M)
    return 3.0 * (xi ** 2) - 2.0 * (xi ** 3)


def _quantized_text(m_minutes: int) -> str:
    """P10: '0 phút' nếu M=0; '~1 phút' nếu M=1; '{M} phút' nếu M>=2."""
    if m_minutes <= 0:
        return "0 phút"
    if m_minutes == 1:
        return "~1 phút"
    return f"{m_minutes} phút"


def compute_station_eta(
    bus_state: BusState,
    route_id: int,
    dir_int: int,
    target_st: StationItemDTO,
    station_s: List[float],
    now_epoch: float,
    data_access,
    day_type: int,
    hour_slot: int,
    ml_p50: Optional[float],
    prediction_source: str,
) -> ApproachingBusDTO:
    """
    SPEC-15 §8.2 + ML override cho P50 + buffer LINEX + quantization + traffic (SPEC-16 §2.10).
    `station_s` là danh sách lý trình lũy kế toàn bộ trạm (order == index).
    """
    v = bus_state.vehicle
    s_now = bus_state.s_now
    d_station = bus_state.d_station
    s_target = target_st.cum_distance_m
    v_obs_kmh = v.speed_kmh

    # Phân đoạn trạm hiện tại & baseline tích lũy
    n_st = len(station_s)
    k = 0
    for idx in range(n_st - 1):
        if station_s[idx] <= s_now < station_s[idx + 1]:
            k = idx
            break
    if s_now >= station_s[-1]:
        k = n_st - 2
    station_order = target_st.station_order
    stops_rem = max(1, station_order - k)

    l_k = max(1.0, station_s[k + 1] - station_s[k])
    rem_in_seg = max(0.0, station_s[k + 1] - s_now)
    rho = min(1.0, max(0.0, rem_in_seg / l_k))

    t_k_p10, t_k_p50, t_k_p90, _, std_k = data_access.lookup_baseline_tt(route_id, dir_int, k, k + 1, day_type, hour_slot, l_k)
    sigma_sq = (rho * std_k) ** 2
    base_rem_p10 = rho * t_k_p10
    base_rem_p50 = rho * t_k_p50
    base_rem_p90 = rho * t_k_p90

    for m in range(k + 1, station_order):
        seg_len_m = max(1.0, station_s[m + 1] - station_s[m])
        m_p10, m_p50, m_p90, _, std_m = data_access.lookup_baseline_tt(route_id, dir_int, m, m + 1, day_type, hour_slot, seg_len_m)
        base_rem_p10 += m_p10
        base_rem_p50 += m_p50
        base_rem_p90 += m_p90
        sigma_sq += std_m ** 2

    sigma_accum = math.sqrt(sigma_sq)

    # (P9/P5) ETA core P50 = ML calibrated nếu khả dụng, ngược lại baseline_p50.
    eta_core_p50 = float(ml_p50) if ml_p50 is not None else base_rem_p50

    # (P7) Độ trễ = ML - prior lịch sử; cờ cảnh báo.
    delta_delay = max(0.0, eta_core_p50 - base_rem_p50)
    is_delayed = delta_delay >= REALTIME_DELAY_ALERT_SEC

    # (P2/P3) Độ đệm bất đối xứng LINEX với suy giảm cận bến smoothstep.
    kappa = _kappa(d_station)
    raw_buffer = kappa * (
        BUFFER_ALPHA_SIGMA * sigma_accum + BUFFER_BETA_TELEMETRY * TELEMETRY_HEARTBEAT_SEC + BUFFER_GAMMA_HORIZON * eta_core_p50
    )
    delta_buffer = max(0.0, min(MAX_SAFE_BUFFER_CEILING_SEC, raw_buffer))

    conservative_eta = eta_core_p50 + delta_buffer

    # (P10) Lượng tử hóa phút nguyên.
    display_min = int(math.ceil(conservative_eta / 60.0))
    display_text = _quantized_text(display_min)

    # (P6) Trạng thái giao thông.
    if v_obs_kmh < CONGESTION_SPEED_THRESHOLD_KMPH or is_delayed:
        traffic_status = "UN_TAC"
    elif v_obs_kmh < FREEFLOW_SPEED_THRESHOLD_KMPH:
        traffic_status = "BINH_THUONG"
    else:
        traffic_status = "THONG_THOANG"

    p10_seconds = max(0.0, min(base_rem_p10, eta_core_p50))
    p90_seconds = max(eta_core_p50, base_rem_p90 + delta_delay)

    safe_window = SafeWindowDTO(
        p10_seconds=round(p10_seconds, 1),
        p50_seconds=round(eta_core_p50, 1),
        p90_seconds=round(p90_seconds, 1),
        p10_minutes=max(0, int(math.ceil(p10_seconds / 60.0))),
        p90_minutes=max(0, int(math.ceil(p90_seconds / 60.0))),
        conservative_eta_seconds=round(conservative_eta, 1),
        buffer_seconds=round(delta_buffer, 1),
        display_eta_minutes=display_min,
        is_delayed=is_delayed,
        delay_seconds=round(delta_delay, 1),
        recommended_arrival_time=_format_hms(now_epoch + base_rem_p10),
    )

    return ApproachingBusDTO(
        vehicle_id=v.id,
        plate=v.plate,
        distance_to_station_m=round(d_station, 1),
        stops_remaining=stops_rem,
        eta_seconds=round(conservative_eta, 1),
        eta_minutes=display_min,
        eta_minutes_precise=round(conservative_eta / 60.0, 1),
        display_eta_minutes=display_min,
        display_text=display_text,
        prediction_source=prediction_source,
        safe_window=safe_window,
        speed_kmh=round(v_obs_kmh, 1),
        traffic_status=traffic_status,
        ping_time=bus_state.ping_time,
        ping_age_seconds=round(bus_state.delta_t_age, 1),
        arrival_time_epoch=round(now_epoch + conservative_eta, 1),
    )
