"""
BusMap API Client, Telemetry Sanitizer, Kinematic Interpolation & Vehicle Catalog Management
"""

import socket
import ssl
import json
import time
import math
from datetime import datetime
from .config import HANOI_BBOX, CONFIG_FILE

ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

def fetch_single_bus_raw(v_id):
    """Gửi HTTP request cấp thấp qua raw socket SSL đến BusMap API để tối ưu tốc độ và né WAF."""
    raw_req = (
        f"GET /v2/public/busmap/vehicle_hn/get?id={v_id} HTTP/1.1\r\n"
        "Host: api.busmap.city\r\n"
        "language: vi\r\n"
        "client-version: android|20600\r\n"
        "device-id: 7ab54c3ba04cceac\r\n"
        "package-name: com.t7.busmaphn\r\n"
        "Connection: close\r\n\r\n"
    )
    try:
        with socket.create_connection(("api.busmap.city", 443), timeout=3.5) as s:
            with ssl_context.wrap_socket(s, server_hostname="api.busmap.city") as ss:
                ss.sendall(raw_req.encode("utf-8"))
                resp = b""
                while True:
                    d = ss.recv(4096)
                    if not d: break
                    resp += d
                header, _, body = resp.partition(b"\r\n\r\n")
                if not body: return None
                data = json.loads(body.decode("utf-8", errors="ignore"))
                if data and isinstance(data, list) and len(data) > 0:
                    return data[0]
    except Exception:
        return None
    return None

def haversine_distance(lat1, lon1, lat2, lon2):
    """Tính khoảng cách Great-circle giữa 2 tọa độ (mét)."""
    R = 6371000.0  # meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2.0)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0)**2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c

def sanitize_and_validate_telemetry(raw, vid, target_route_ids, kinematic_cache, crawl_time_iso):
    """
    Chuẩn hóa tọa độ WGS84, tự nội suy vận tốc thực tế v_calc và làm mịn EMA,
    gắn cờ kiểm soát chất lượng dữ liệu (Quality Status).
    """
    if not raw:
        return None

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
            curr_epoch = datetime.fromisoformat(last_update).timestamp()
        except Exception:
            pass

    # 2. Nội suy vận tốc động học (Kinematic Velocity) & Làm mịn EMA
    calc_speed = raw_speed
    smoothed_speed = raw_speed
    is_drift_jump = False
    is_stale = False

    if vid in kinematic_cache:
        prev = kinematic_cache[vid]
        prev_lat = prev["lat"]
        prev_lon = prev["lon"]
        prev_epoch = prev["epoch"]
        prev_smoothed = prev["smoothed_speed"]
        prev_update = prev.get("last_update", "")

        delta_t = curr_epoch - prev_epoch
        if prev_update and prev_update == last_update:
            is_stale = True

        if 3.0 <= delta_t <= 300.0:
            dist = haversine_distance(prev_lat, prev_lon, std_lat, std_lon)
            if dist < 5.0:
                calc_speed = 0.0
                smoothed_speed = 0.0
            else:
                v_derived = (dist / delta_t) * 3.6
                if v_derived > 80.0:  # Xe buýt nội đô không thể vượt quá 80 km/h
                    is_drift_jump = True
                    calc_speed = prev_smoothed
                    smoothed_speed = prev_smoothed
                else:
                    calc_speed = round(v_derived, 1)
                    smoothed_speed = round(0.65 * calc_speed + 0.35 * prev_smoothed, 1)
        elif delta_t > 300.0:
            calc_speed = raw_speed
            smoothed_speed = raw_speed

    kinematic_cache[vid] = {
        "lat": std_lat,
        "lon": std_lon,
        "epoch": curr_epoch,
        "smoothed_speed": smoothed_speed,
        "last_update": last_update
    }

    # 3. Phân loại chất lượng dữ liệu
    quality_status = "ACTIVE_VALID"

    if direction == -1 and raw_speed == 0 and station_id == 0:
        quality_status = "IDLE_DEPOT"
    elif not (HANOI_BBOX["min_lat"] <= std_lat <= HANOI_BBOX["max_lat"] and
              HANOI_BBOX["min_lon"] <= std_lon <= HANOI_BBOX["max_lon"]):
        quality_status = "OUT_OF_BOUNDS"
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
        "crawled_at": crawl_time_iso,
        "quality_status": quality_status
    }

def search_vehicles_by_query(query, limit=50):
    """Tìm kiếm xe buýt trên API BusMap theo mã tuyến hoặc biển số."""
    raw_req = (
        f"GET /v2/public/busmap/search_vehicle_v2?regionCode=hn&limit={limit}&vehicleId={query}&page=0 HTTP/1.1\r\n"
        "Host: api.busmap.city\r\n"
        "language: vi\r\n"
        "client-version: android|20600\r\n"
        "device-id: 7ab54c3ba04cceac\r\n"
        "package-name: com.t7.busmaphn\r\n"
        "Connection: close\r\n\r\n"
    )
    try:
        with socket.create_connection(("api.busmap.city", 443), timeout=5.0) as s:
            with ssl_context.wrap_socket(s, server_hostname="api.busmap.city") as ss:
                ss.sendall(raw_req.encode("utf-8"))
                resp = b""
                while True:
                    d = ss.recv(4096)
                    if not d: break
                    resp += d
                header, _, body = resp.partition(b"\r\n\r\n")
                if not body: return []
                data = json.loads(body.decode("utf-8", errors="ignore"))
                if isinstance(data, list):
                    return data
    except Exception:
        return []
    return []

def load_cluster_config(config_path=CONFIG_FILE):
    """Đọc file cấu hình cụm 19 tuyến hành lang."""
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_cluster_config(config, config_path=CONFIG_FILE):
    """Ghi cập nhật file cấu hình cụm 19 tuyến hành lang."""
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

