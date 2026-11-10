"""
Step 3.4 — Live feed BusMap + cache RAM + parse ping.
Module: module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/live_feed.py

Kế thừa logic `busmap_service.py:175-335`, đã sửa blocker B2: dùng đúng key HANOI_BBOX
(`min_lat/max_lat/min_lon/max_lon`) thay vì `lat_min/...` gây KeyError.
"""

import time
from datetime import datetime
from typing import Any, Dict, List, Tuple

from config.system_config import HANOI_BBOX, LIVE_CACHE_TTL_SEC, TZ_HANOI
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.dto import (
    BusVehicleDTO,
    RouteLiveResponse,
)


def now_hanoi_iso() -> str:
    """Thời gian hiện tại theo múi giờ Hà Nội (ISO 8601)."""
    return datetime.now(TZ_HANOI).isoformat()


def parse_ping_epoch(ts_val: Any, default_epoch: float) -> Tuple[float, str]:
    """
    Parse timestamp viễn trắc GPS xe thành (epoch_seconds, iso_string).
    Hỗ trợ ISO 8601, Unix epoch giây/mili-giây; fallback an toàn về default_epoch.
    """
    if ts_val is None:
        dt = datetime.fromtimestamp(default_epoch, tz=TZ_HANOI)
        return default_epoch, dt.isoformat()

    if isinstance(ts_val, (int, float)):
        epoch = float(ts_val)
        if epoch > 1e11:  # milliseconds
            epoch /= 1000.0
        dt = datetime.fromtimestamp(epoch, tz=TZ_HANOI)
        return epoch, dt.isoformat()

    s = str(ts_val).strip()
    if not s:
        dt = datetime.fromtimestamp(default_epoch, tz=TZ_HANOI)
        return default_epoch, dt.isoformat()

    try:
        val = float(s)
        if val > 1e11:
            val /= 1000.0
        dt = datetime.fromtimestamp(val, tz=TZ_HANOI)
        return val, dt.isoformat()
    except ValueError:
        pass

    try:
        clean_s = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean_s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ_HANOI)
        return dt.timestamp(), dt.isoformat()
    except Exception:
        pass

    dt = datetime.fromtimestamp(default_epoch, tz=TZ_HANOI)
    return default_epoch, dt.isoformat()


# Cache RAM ngắn hạn (TTL = LIVE_CACHE_TTL_SEC) bảo đảm SLA < 20ms và bảo vệ upstream BusMap.
live_cache: Dict[Tuple[int, int], Tuple[float, RouteLiveResponse]] = {}


def fetch_live_vehicles_for_route(route_id: int, direction: int = 0) -> RouteLiveResponse:
    """
    Truy vấn xe đang chạy trực tiếp từ BusMap, lọc bản ghi không hợp lệ / ngoài phạm vi Hà Nội.
    Trả về RouteLiveResponse chứa danh sách BusVehicleDTO.
    """
    from module_1_data_ingestion_and_preprocessing.step_1_1_busmap_crawler_and_relay.catalog_refresher import (
        fetch_route_buses_live,
    )

    if direction not in (0, 1):
        direction = 0

    cache_key = (route_id, direction)
    now_mono = time.monotonic()
    if cache_key in live_cache:
        cached_ts, cached_res = live_cache[cache_key]
        if now_mono - cached_ts < LIVE_CACHE_TTL_SEC:
            return cached_res

    raw_items = fetch_route_buses_live(route_id=route_id, direction=direction)
    timestamp_str = now_hanoi_iso()
    now_fetch_epoch = datetime.now(TZ_HANOI).timestamp()

    if not raw_items or not isinstance(raw_items, list):
        empty_res = RouteLiveResponse(
            route_id=route_id, direction=direction, count=0, timestamp=timestamp_str, vehicles=[]
        )
        live_cache[cache_key] = (now_mono, empty_res)
        return empty_res

    seen_ids = set()
    cleaned_vehicles: List[BusVehicleDTO] = []

    for raw in raw_items:
        if not isinstance(raw, dict):
            continue

        vehicle_id = raw.get("Id")
        if not vehicle_id or not isinstance(vehicle_id, int) or vehicle_id <= 0:
            continue
        if vehicle_id in seen_ids:
            continue

        try:
            lat = float(raw.get("Lat", 0.0))
            lng = float(raw.get("Lng", 0.0))
        except (ValueError, TypeError):
            continue

        # Data Hygiene: kiểm tra Bounding Box Hà Nội (key đúng từ config).
        if not (
            HANOI_BBOX["min_lat"] <= lat <= HANOI_BBOX["max_lat"]
            and HANOI_BBOX["min_lon"] <= lng <= HANOI_BBOX["max_lon"]
        ):
            continue

        plate = str(raw.get("VehicleNumber") or "").strip()
        if not plate:
            plate = f"BUS-{vehicle_id}"

        try:
            deg = float(raw.get("Deg", 0.0)) % 360.0
        except (ValueError, TypeError):
            deg = 0.0

        try:
            speed = max(0.0, float(raw.get("Speed", 0.0)))
        except (ValueError, TypeError):
            speed = 0.0

        _, updated_at = parse_ping_epoch(raw.get("lastUpdateTime"), now_fetch_epoch)

        current_station_id = raw.get("currentStationId")
        if isinstance(current_station_id, int) and current_station_id <= 0:
            current_station_id = None

        next_station_id = raw.get("nextStationId")
        if isinstance(next_station_id, int) and next_station_id <= 0:
            next_station_id = None

        dto = BusVehicleDTO(
            id=vehicle_id,
            plate=plate,
            route_id=route_id,
            direction=direction,
            lat=lat,
            lng=lng,
            deg=round(deg, 2),
            speed_kmh=round(speed, 1),
            updated_at=str(updated_at),
            current_station_id=current_station_id,
            next_station_id=next_station_id,
        )

        seen_ids.add(vehicle_id)
        cleaned_vehicles.append(dto)

    resp = RouteLiveResponse(
        route_id=route_id, direction=direction, count=len(cleaned_vehicles),
        timestamp=timestamp_str, vehicles=cleaned_vehicles,
    )
    live_cache[cache_key] = (now_mono, resp)
    return resp
