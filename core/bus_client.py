"""
BusMap API Client, Telemetry Sanitizer, Kinematic Interpolation & Vehicle Catalog Management
"""

import socket
import ssl
import json
import time
import math
from datetime import datetime
from .config import (
    HANOI_BBOX, CONFIG_FILE,
    GPS_DRIFT_MAX_SPEED_KMPH, BUS_STOPPED_SPEED_KMPH,
    STALE_DELTA_T_MIN_SEC, STALE_DELTA_T_MAX_SEC,
    EMA_ALPHA, get_busmap_device_id, get_hanoi_time
)

ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

# Bộ đệm phân giải DNS trong RAM (Dynamic DNS Cache) & Cấu hình Timeout Chặt Chẽ
_BUSMAP_HOST = "api.busmap.city"
_BUSMAP_IP_CACHE = None
_BUSMAP_IP_RESOLVED_AT = 0
SOCKET_TIMEOUT_SEC = 2.2       # Ngưỡng timeout tối ưu (gấp đôi thời gian phản hồi bình thường)
SOCKET_RETRY_TIMEOUT_SEC = 1.5 # Ngưỡng timeout cho đợt retry nếu gặp 429

def get_busmap_ip():
    """Cache phân giải IP của api.busmap.city trong RAM để triệt tiêu 504 lần truy vấn DNS/vòng."""
    global _BUSMAP_IP_CACHE, _BUSMAP_IP_RESOLVED_AT
    now = time.time()
    if _BUSMAP_IP_CACHE is None or (now - _BUSMAP_IP_RESOLVED_AT) > 600:  # Làm mới mỗi 10 phút
        try:
            _BUSMAP_IP_CACHE = socket.gethostbyname(_BUSMAP_HOST)
            _BUSMAP_IP_RESOLVED_AT = now
        except Exception:
            _BUSMAP_IP_CACHE = _BUSMAP_HOST
    return _BUSMAP_IP_CACHE

def fetch_single_bus_raw(v_id):
    """Gửi HTTP request cấp thấp qua raw socket SSL đến BusMap API với DNS Cache và Timeout chặt chẽ."""
    dev_id = get_busmap_device_id(v_id=v_id)
    raw_req = (
        f"GET /v2/public/busmap/vehicle_hn/get?id={v_id} HTTP/1.1\r\n"
        f"Host: {_BUSMAP_HOST}\r\n"
        "language: vi\r\n"
        "client-version: android|20600\r\n"
        f"device-id: {dev_id}\r\n"
        "package-name: com.t7.busmaphn\r\n"
        "Connection: close\r\n\r\n"
    )
    target_host = get_busmap_ip()
    try:
        with socket.create_connection((target_host, 443), timeout=SOCKET_TIMEOUT_SEC) as s:
            s.settimeout(SOCKET_TIMEOUT_SEC)
            with ssl_context.wrap_socket(s, server_hostname=_BUSMAP_HOST) as ss:
                ss.settimeout(SOCKET_TIMEOUT_SEC)
                ss.sendall(raw_req.encode("utf-8"))
                resp = b""
                while True:
                    d = ss.recv(4096)
                    if not d: break
                    resp += d
                header, _, body = resp.partition(b"\r\n\r\n")
                if not body: return None
                if b"429 Too Many Requests" in header or b"LOCKED" in body:
                    new_dev_id = get_busmap_device_id(v_id=v_id, bad_device_id=dev_id, force_rotate=True)
                    # Thử lại 1 lần với device ID mới vừa cấp và timeout gọn gàng
                    retry_req = (
                        f"GET /v2/public/busmap/vehicle_hn/get?id={v_id} HTTP/1.1\r\n"
                        f"Host: {_BUSMAP_HOST}\r\n"
                        "language: vi\r\n"
                        "client-version: android|20600\r\n"
                        f"device-id: {new_dev_id}\r\n"
                        "package-name: com.t7.busmaphn\r\n"
                        "Connection: close\r\n\r\n"
                    )
                    with socket.create_connection((target_host, 443), timeout=SOCKET_RETRY_TIMEOUT_SEC) as s2:
                        s2.settimeout(SOCKET_RETRY_TIMEOUT_SEC)
                        with ssl_context.wrap_socket(s2, server_hostname=_BUSMAP_HOST) as ss2:
                            ss2.settimeout(SOCKET_RETRY_TIMEOUT_SEC)
                            ss2.sendall(retry_req.encode("utf-8"))
                            resp2 = b""
                            while True:
                                d2 = ss2.recv(4096)
                                if not d2: break
                                resp2 += d2
                            _, _, body2 = resp2.partition(b"\r\n\r\n")
                            if body2:
                                data2 = json.loads(body2.decode("utf-8", errors="ignore"))
                                if data2 and isinstance(data2, list) and len(data2) > 0:
                                    item2 = data2[0]
                                    if isinstance(item2, dict):
                                        item2["_crawled_at"] = get_hanoi_time().isoformat()
                                    return item2
                    return None
                data = json.loads(body.decode("utf-8", errors="ignore"))
                if data and isinstance(data, list) and len(data) > 0:
                    item = data[0]
                    if isinstance(item, dict):
                        item["_crawled_at"] = get_hanoi_time().isoformat()
                    return item
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

        if STALE_DELTA_T_MIN_SEC <= delta_t <= STALE_DELTA_T_MAX_SEC:
            dist = haversine_distance(prev_lat, prev_lon, std_lat, std_lon)
            if dist < BUS_STOPPED_SPEED_KMPH:
                calc_speed = 0.0
                smoothed_speed = 0.0
            else:
                v_derived = (dist / delta_t) * 3.6
                if v_derived > GPS_DRIFT_MAX_SPEED_KMPH:  # Vượt quá giới hạn vật lý nội đô
                    is_drift_jump = True
                    calc_speed = prev_smoothed
                    smoothed_speed = prev_smoothed
                else:
                    calc_speed = round(v_derived, 1)
                    smoothed_speed = round(EMA_ALPHA * calc_speed + (1.0 - EMA_ALPHA) * prev_smoothed, 1)
        elif delta_t > STALE_DELTA_T_MAX_SEC:
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
        "crawled_at": actual_crawl_time_iso,
        "quality_status": quality_status
    }

def search_vehicles_by_query(query, limit=50):
    """Tìm kiếm xe buýt trên API BusMap theo mã tuyến hoặc biển số."""
    dev_id = get_busmap_device_id()
    raw_req = (
        f"GET /v2/public/busmap/search_vehicle_v2?regionCode=hn&limit={limit}&vehicleId={query}&page=0 HTTP/1.1\r\n"
        "Host: api.busmap.city\r\n"
        "language: vi\r\n"
        "client-version: android|20600\r\n"
        f"device-id: {dev_id}\r\n"
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

