"""
Module 1.1.3: Realtime Telemetry Sanitizer & Kinematic Filter
- Đảo ngược Lat/Lon (khắc phục lỗi hoán vị của BusMap: raw['Lat'] là Lon, raw['Lng'] là Lat)
- Tính toán vận tốc vi phân động học v_calc và làm mịn EMA
- Phát hiện GPS drift jump vật lý
- Gán cờ trạng thái chất lượng (ACTIVE_VALID, STALE_PING, IDLE_DEPOT, OUT_OF_BOUNDS)
- Gắn nhãn crawled_at chính xác cho từng xe
"""

import time
from datetime import datetime
from .kinematic_engine import haversine_distance
from config import (
    HANOI_BBOX,
    GPS_DRIFT_MAX_SPEED_KMPH,
    GPS_DRIFT_MIN_DIST_M,
    TERMINAL_STATIONARY_TOL_M,
    STALE_DELTA_T_MIN_SEC,
    STALE_DELTA_T_MAX_SEC,
    EMA_ALPHA,
    TZ_HANOI,
    get_hanoi_time
)


def sanitize_and_validate_telemetry(raw, vid, target_route_ids, kinematic_cache, crawl_time_iso=None):
    """
    Chuẩn hóa tọa độ WGS84, tự nội suy vận tốc thực tế v_calc và làm mịn EMA,
    gắn cờ kiểm soát chất lượng dữ liệu (Quality Status).
    Mỗi bản ghi xe sử dụng đúng mốc thời gian phản hồi thực tế của riêng xe đó (_crawled_at).
    """
    if not raw:
        return None
    actual_crawl_time_iso = raw.get("_crawled_at") or crawl_time_iso or get_hanoi_time().isoformat()

    # BusMap đảo ngược Lat và Lng: raw["Lat"] là Kinh độ (Lon), raw["Lng"] là Vĩ độ (Lat)
    try:
        std_lon = float(raw.get("Lat", 0.0))
        std_lat = float(raw.get("Lng", 0.0))
    except (ValueError, TypeError):
        return None

    raw_speed = float(raw.get("Speed", 0.0))
    direction = int(raw.get("direction", 0))
    route_id = int(raw.get("RouteId", 0))
    last_update = raw.get("lastUpdateTime", "")
    station_id = raw.get("currentStationId", 0)

    # 1. Parse device timestamp
    curr_epoch = time.time()
    if last_update:
        try:
            dt_obj = datetime.fromisoformat(last_update.replace("Z", "+00:00"))
            if dt_obj.tzinfo is None:
                dt_obj = dt_obj.replace(tzinfo=TZ_HANOI)
            curr_epoch = dt_obj.timestamp()
        except Exception:
            pass

    in_bounds = (
        HANOI_BBOX["min_lat"] <= std_lat <= HANOI_BBOX["max_lat"]
        and HANOI_BBOX["min_lon"] <= std_lon <= HANOI_BBOX["max_lon"]
    )

    # 2. Nội suy vận tốc động học (Kinematic Velocity) & Làm mịn EMA
    calc_speed = raw_speed
    smoothed_speed = raw_speed
    is_drift_jump = False
    is_stale = False

    if in_bounds and vid in kinematic_cache:
        prev = kinematic_cache[vid]
        prev_lat = prev["lat"]
        prev_lon = prev["lon"]
        prev_epoch = prev["epoch"]
        prev_smoothed = prev["smoothed_speed"]
        prev_update = prev.get("last_update", "")

        delta_t = curr_epoch - prev_epoch
        if prev_update and prev_update == last_update:
            is_stale = True

        if STALE_DELTA_T_MIN_SEC <= delta_t <= STALE_DELTA_T_MAX_SEC:
            dist = haversine_distance(prev_lat, prev_lon, std_lat, std_lon)
            if dist < TERMINAL_STATIONARY_TOL_M:
                calc_speed = 0.0
                smoothed_speed = 0.0
            else:
                v_derived = (dist / delta_t) * 3.6
                if dist >= GPS_DRIFT_MIN_DIST_M and v_derived > GPS_DRIFT_MAX_SPEED_KMPH:
                    is_drift_jump = True
                    calc_speed = prev_smoothed
                    smoothed_speed = prev_smoothed
                else:
                    calc_speed = round(v_derived, 1)
                    smoothed_speed = round(EMA_ALPHA * calc_speed + (1.0 - EMA_ALPHA) * prev_smoothed, 1)
        elif delta_t > STALE_DELTA_T_MAX_SEC:
            calc_speed = raw_speed
            smoothed_speed = raw_speed

    if in_bounds and not is_drift_jump and (vid not in kinematic_cache or curr_epoch >= kinematic_cache[vid]["epoch"]):
        kinematic_cache[vid] = {
            "lat": std_lat,
            "lon": std_lon,
            "epoch": curr_epoch,
            "smoothed_speed": smoothed_speed,
            "last_update": last_update
        }

    # 3. Phân loại chất lượng dữ liệu
    quality_status = "ACTIVE_VALID"

    if not in_bounds:
        quality_status = "OUT_OF_BOUNDS"
    # Trong BusMap thực tế: direction 0 = go, 1 = re, -1 = unassigned/depot
    elif (direction == -1 or route_id <= 0) and smoothed_speed == 0.0:
        quality_status = "IDLE_DEPOT"
    elif route_id not in target_route_ids:
        quality_status = "REASSIGNED_ROUTE"
    elif is_drift_jump:
        quality_status = "GPS_DRIFT_JUMP"
    elif is_stale:
        quality_status = "STALE_PING"

    return {
        "vehicle_id": vid,
        "plate": raw.get("VehicleNumber", ""),
        "route_id": route_id,
        "lat": round(std_lat, 6),
        "lon": round(std_lon, 6),
        "speed": smoothed_speed,
        "raw_speed": raw_speed,
        "calculated_speed": calc_speed,
        "direction": direction,
        "heading_deg": raw.get("Deg", 0),
        "current_station_id": station_id,
        "next_station_id": raw.get("nextStationId", 0),
        "device_update_time": last_update,
        "crawled_at": actual_crawl_time_iso,
        "quality_status": quality_status
    }

