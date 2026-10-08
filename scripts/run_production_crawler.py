"""
Production Multi-Tier Crawler for HUST Corridor Cluster (220 Buses, 19 Routes)
Author: Antigravity Big Data Architecture Team
Features:
- 220 Corridor Buses with Smooth Micro-Batch Pacing (~4 req/s, Flat CPU)
- Stateful TomTom Quota Persistence & CLI Progress Dashboard
- Real-time Data Quality & Sanity Guard (Depot/Stale/Geofence/Reassigned)
- Automated Hugging Face Cloud Synchronization Every 10 Minutes
- Auto Operating Schedule: 05:00 - 22:00 (Sleeps safely at night)
"""

import os
import sys
import json
import time
import socket
import ssl
import base64
import urllib.request
import urllib.parse
import urllib.error
import math
from datetime import datetime, time as dtime
from concurrent.futures import ThreadPoolExecutor

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

CONFIG_FILE = "data/metadata/hust_cluster_config.json"
BUS_OUTPUT_DIR = "data/raw/bus"
TOMTOM_OUTPUT_DIR = "data/raw/traffic"
API_KEY_FILE = "Test_tomtom/TOMTOM_API_KEY.txt"
HF_TOKEN_FILE = "access_token_hf.txt"
HF_DATASET_ID = os.environ.get("HF_DATASET_ID", "Toibinguz/hust-bus-data")
TOMTOM_QUOTA_FILE = "data/metadata/tomtom_quota_tracker.json"

BUS_POLL_INTERVAL = 60  # seconds (target cycle)
HF_SYNC_INTERVAL = 600  # seconds (sync to Cloud every 10 mins)

# TomTom Freemium Limits chuan theo Dashboard (Thang: 20k Flow, 2.5k Incident):
# Phan bo an toan theo ngay (30 ngay/thang):
MAX_TOMTOM_FLOW_DAILY = 600       # 18,000/thang (du 2,000 calls du phong)
MAX_TOMTOM_INCIDENT_DAILY = 75    # 2,250/thang (du 250 calls du phong)
HUST_CORRIDOR_BBOX = "105.7500,20.9500,105.9000,21.0800"

# Geographic bounding box for Hanoi Urban Core
HANOI_BBOX = {
    "min_lat": 20.80,
    "max_lat": 21.30,
    "min_lon": 105.65,
    "max_lon": 106.05
}

# Top 19 critical bottlenecks for HUST cluster routes
HUST_BOTTLENECK_NODES = [
    {"name": "Kim_Lien_Ham_Chui", "lat": 21.0084, "lon": 105.8427, "is_core": True},
    {"name": "Dai_Co_Viet_Pho_Hue", "lat": 21.0092, "lon": 105.8503, "is_core": True},
    {"name": "Nga_Tu_Vong", "lat": 20.9987, "lon": 105.8415, "is_core": True},
    {"name": "Le_Thanh_Nghi_Bach_Mai", "lat": 21.0028, "lon": 105.8497, "is_core": True},
    {"name": "Nga_Tu_Cau_Giay", "lat": 21.0315, "lon": 105.8016, "is_core": False},
    {"name": "Nga_Tu_Mai_Dich", "lat": 21.0378, "lon": 105.7788, "is_core": False},
    {"name": "Cau_Dien_QL32", "lat": 21.0422, "lon": 105.7582, "is_core": False},
    {"name": "Nhon_DH_Cong_Nghiep", "lat": 21.0543, "lon": 105.7351, "is_core": False},
    {"name": "Pham_Ngoc_Thach_DH_Y", "lat": 21.0089, "lon": 105.8324, "is_core": False},
    {"name": "Chua_Boc_Tay_Son", "lat": 21.0097, "lon": 105.8239, "is_core": False},
    {"name": "Huynh_Thuc_Khang_NCT", "lat": 21.0211, "lon": 105.8118, "is_core": False},
    {"name": "Nga_Tu_So", "lat": 21.0012, "lon": 105.8197, "is_core": False},
    {"name": "Nguyen_Trai_Khuat_Duy_Tien", "lat": 20.9922, "lon": 105.8005, "is_core": False},
    {"name": "Nguyen_Trai_Cau_Trang", "lat": 20.9765, "lon": 105.7832, "is_core": False},
    {"name": "Trang_Tien_Bo_Ho", "lat": 21.0251, "lon": 105.8542, "is_core": False},
    {"name": "Yen_Phu_Cau_Chuong_Duong", "lat": 21.0415, "lon": 105.8552, "is_core": False},
    {"name": "Nghi_Tam_Au_Co", "lat": 21.0665, "lon": 105.8285, "is_core": False},
    {"name": "Giai_Phong_Kim_Dong_Giap_Bat", "lat": 20.9812, "lon": 105.8422, "is_core": False},
    {"name": "Ngoc_Hoi_Phan_Trong_Tue", "lat": 20.9498, "lon": 105.8451, "is_core": False}
]

TOMTOM_CIRCUIT_OPEN = False

ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

def is_operating_hours(run_24x7=False):
    if run_24x7:
        return True
    now_t = datetime.now().time()
    start_t = dtime(5, 0)
    end_t = dtime(22, 0)
    return start_t <= now_t <= end_t

def get_tomtom_api_key():
    if os.path.exists(API_KEY_FILE):
        with open(API_KEY_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    return os.environ.get("TOMTOM_KEY", "") or os.environ.get("TOMTOM_API_KEY", "")

def get_hf_token():
    if os.path.exists(HF_TOKEN_FILE):
        with open(HF_TOKEN_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    return os.environ.get("HF_TOKEN", "")

def load_tomtom_quota_state():
    today_str = datetime.now().strftime("%Y-%m-%d")
    current_month_str = datetime.now().strftime("%Y-%m")
    flow_today = 0
    flow_month = 0
    incident_today = 0
    incident_month = 0
    if os.path.exists(TOMTOM_QUOTA_FILE):
        try:
            with open(TOMTOM_QUOTA_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
                saved_month = state.get("month", "")
                saved_date = state.get("date", "")
                if saved_month == current_month_str:
                    flow_month = state.get("flow_used_month", 0)
                    incident_month = state.get("incident_used_month", 0)
                if saved_date == today_str:
                    flow_today = state.get("flow_used_today", state.get("used_today", 0))
                    incident_today = state.get("incident_used_today", 0)
        except Exception:
            pass
    return {
        "flow_today": flow_today,
        "flow_month": flow_month,
        "incident_today": incident_today,
        "incident_month": incident_month
    }

def save_tomtom_quota_state(quota_state):
    today_str = datetime.now().strftime("%Y-%m-%d")
    current_month_str = datetime.now().strftime("%Y-%m")
    os.makedirs(os.path.dirname(TOMTOM_QUOTA_FILE), exist_ok=True)
    state = {
        "date": today_str,
        "month": current_month_str,
        "flow_daily_budget": MAX_TOMTOM_FLOW_DAILY,
        "flow_monthly_limit": 20000,
        "flow_used_today": quota_state["flow_today"],
        "flow_used_month": quota_state["flow_month"],
        "flow_remaining_today": max(0, MAX_TOMTOM_FLOW_DAILY - quota_state["flow_today"]),
        "flow_remaining_month": max(0, 20000 - quota_state["flow_month"]),
        "incident_daily_budget": MAX_TOMTOM_INCIDENT_DAILY,
        "incident_monthly_limit": 2500,
        "incident_used_today": quota_state["incident_today"],
        "incident_used_month": quota_state["incident_month"],
        "incident_remaining_today": max(0, MAX_TOMTOM_INCIDENT_DAILY - quota_state["incident_today"]),
        "incident_remaining_month": max(0, 2500 - quota_state["incident_month"]),
        "last_updated": datetime.now().strftime("%H:%M:%S")
    }
    try:
        with open(TOMTOM_QUOTA_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def render_tomtom_cli_bar(quota_state, next_poll_seconds, is_congested=False, circuit_open=False):
    f_pct = min(1.0, quota_state["flow_today"] / float(MAX_TOMTOM_FLOW_DAILY))
    bar_width = 8
    filled = int(f_pct * bar_width)
    bar_str = "█" * filled + "░" * (bar_width - filled)
    countdown_str = f"{int(next_poll_seconds // 60):02d}:{int(next_poll_seconds % 60):02d}s" if next_poll_seconds > 0 else "Sẵn sàng"
    status_tag = "🔴 CIRCUIT OPEN" if circuit_open else ("🔥 ÙN TẮC" if is_congested else "🟢 BÌNH THƯỜNG")
    return (
        f"🚦 TomTom [{status_tag}]: Flow [{bar_str}] {quota_state['flow_today']}/{MAX_TOMTOM_FLOW_DAILY} "
        f"(Tháng: {quota_state['flow_month']}/20k) | Incidents {quota_state['incident_today']}/{MAX_TOMTOM_INCIDENT_DAILY} | "
        f"Đợt tới: {countdown_str}"
    )

def sync_to_hf(local_bus_file, local_traffic_file, local_incident_file, date_str, token):
    """
    Đồng bộ dữ liệu lên Hugging Face Dataset hoàn toàn bằng thư viện chuẩn (Standard Library).
    Không cần pip, không cần huggingface_hub, không cần Rust hay compilation!
    Chạy mượt mà 100% trên Termux Android và mọi môi trường Python.
    """
    if not token:
        return

    operations = []

    if local_bus_file and os.path.exists(local_bus_file):
        try:
            with open(local_bus_file, "rb") as f:
                content_bytes = f.read()
            if content_bytes:
                b64_content = base64.b64encode(content_bytes).decode("ascii")
                repo_bus_path = f"raw_data/{date_str}/bus/{os.path.basename(local_bus_file)}"
                operations.append({
                    "key": "file",
                    "value": {
                        "path": repo_bus_path,
                        "encoding": "base64",
                        "content": b64_content
                    }
                })
        except Exception:
            pass

    if local_traffic_file and os.path.exists(local_traffic_file):
        try:
            with open(local_traffic_file, "rb") as f:
                content_bytes = f.read()
            if content_bytes:
                b64_content = base64.b64encode(content_bytes).decode("ascii")
                repo_traffic_path = f"raw_data/{date_str}/traffic/{os.path.basename(local_traffic_file)}"
                operations.append({
                    "key": "file",
                    "value": {
                        "path": repo_traffic_path,
                        "encoding": "base64",
                        "content": b64_content
                    }
                })
        except Exception:
            pass

    if local_incident_file and os.path.exists(local_incident_file):
        try:
            with open(local_incident_file, "rb") as f:
                content_bytes = f.read()
            if content_bytes:
                b64_content = base64.b64encode(content_bytes).decode("ascii")
                repo_incident_path = f"raw_data/{date_str}/incidents/{os.path.basename(local_incident_file)}"
                operations.append({
                    "key": "file",
                    "value": {
                        "path": repo_incident_path,
                        "encoding": "base64",
                        "content": b64_content
                    }
                })
        except Exception:
            pass

    if not operations:
        return

    commit_url = f"https://huggingface.co/api/datasets/{HF_DATASET_ID}/commit/main"
    ndjson_lines = [
        json.dumps({"key": "header", "value": {"summary": f"Native Auto-sync {len(operations)} files ({date_str})", "description": ""}}).encode("utf-8")
    ]
    for op in operations:
        ndjson_lines.append(json.dumps(op).encode("utf-8"))
    data = b"\n".join(ndjson_lines) + b"\n"
    
    req = urllib.request.Request(
        commit_url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/x-ndjson"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, context=ssl_context, timeout=30) as resp:
            if resp.getcode() == 200:
                print(f"   ☁️ [HF-Sync] Đồng bộ thành công {len(operations)} files lên Dataset {HF_DATASET_ID}", flush=True)
            else:
                print(f"   ⚠️ [HF-Sync] Server trả về mã HTTP {resp.getcode()}. Dữ liệu đã lưu an toàn tại máy.", flush=True)
    except Exception as e:
        print(f"   ⚠️ [HF-Sync] Tạm thời chưa đẩy được lên Cloud ({e}). Dữ liệu đã lưu an toàn tại máy.", flush=True)

def fetch_single_bus_raw(vehicle_id):
    raw_req = (
        f"GET /v2/public/busmap/vehicle_hn/get?id={vehicle_id} HTTP/1.1\r\n"
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
    Chuẩn hóa dữ liệu thực tế và gắn cờ kiểm soát chất lượng (Quality Status)
    Nội suy vận tốc thực tế v_calc và làm mịn EMA, tránh phụ thuộc vào speed rác của API.
    """
    if not raw:
        return None

    # 1. BusMap đảo ngược Lat và Lng: raw["Lat"] là Kinh độ (Lon), raw["Lng"] là Vĩ độ (Lat)
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

    # 2. Parse device timestamp de noi suy van toc dong hoc
    curr_epoch = time.time()
    if last_update:
        try:
            curr_epoch = datetime.fromisoformat(last_update).timestamp()
        except Exception:
            pass

    # 3. Noi suy van toc (Kinematic Velocity) & Lam min EMA
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
                if v_derived > 80.0:  # Xe buyt noi do Ha Noi khong the chay >80 km/h
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

    # 4. Danh gia chat luong du lieu
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

    clean_record = {
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
    return clean_record

def fetch_tomtom_flow(lat, lon, api_key):
    global TOMTOM_CIRCUIT_OPEN
    if TOMTOM_CIRCUIT_OPEN or not api_key:
        return None
    url = f"https://api.tomtom.com/traffic/services/4/flowSegmentData/relative0/10/json?key={api_key}&point={lat},{lon}&unit=KMPH"
    req = urllib.request.Request(url, headers={"User-Agent": "HUSTBusCrawler/2.0"})
    try:
        with urllib.request.urlopen(req, context=ssl_context, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("flowSegmentData")
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            TOMTOM_CIRCUIT_OPEN = True
            print(f"[CIRCUIT BREAKER] ⚠️ TomTom trả về HTTP {e.code} (Hết hạn mức hoặc bị giới hạn). Kích hoạt ngắt mạch, ngừng gọi TomTom!", flush=True)
        return None
    except Exception:
        return None

def fetch_tomtom_incidents(api_key, bbox=HUST_CORRIDOR_BBOX):
    global TOMTOM_CIRCUIT_OPEN
    if TOMTOM_CIRCUIT_OPEN or not api_key:
        return []
    raw_url = f"https://api.tomtom.com/traffic/services/5/incidentDetails?key={api_key}&bbox={bbox}&language=en-GB&fields={{incidents{{type,geometry{{type,coordinates}},properties{{id,iconCategory,magnitudeOfDelay,delay,length,events{{description}}}}}}}}"
    url = urllib.parse.quote(raw_url, safe=':/?=&')
    req = urllib.request.Request(url, headers={"User-Agent": "HUSTBusCrawler/2.0"})
    try:
        with urllib.request.urlopen(req, context=ssl_context, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("incidents", [])
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            TOMTOM_CIRCUIT_OPEN = True
            print(f"[CIRCUIT BREAKER] ⚠️ TomTom trả về HTTP {e.code} (Hết hạn mức hoặc bị giới hạn). Kích hoạt ngắt mạch, ngừng gọi TomTom!", flush=True)
        return []
    except Exception:
        return []

def evaluate_hotspot_congestion(bus_records, bottleneck_nodes=HUST_BOTTLENECK_NODES, radius_meters=450.0):
    """
    Đo lường mật độ và vận tốc xe buýt xung quanh 19 điểm nghẽn trọng yếu.
    Dùng 220 xe buýt làm cảm biến thăm dò (probe sensors) để phát hiện ùn tắc cục bộ mà không tốn request API bên ngoài.
    """
    if not bus_records:
        return {"is_congested": False, "congested_nodes": [], "details": {}}

    active_buses = [b for b in bus_records if b.get("quality_status") == "ACTIVE_VALID"]
    if not active_buses:
        return {"is_congested": False, "congested_nodes": [], "details": {}}

    congested_nodes = []
    details = {}
    has_critical_core_congestion = False

    for node in bottleneck_nodes:
        n_lat, n_lon = node["lat"], node["lon"]
        name = node["name"]
        is_core = node.get("is_core", False)

        nearby_speeds = []
        for b in active_buses:
            d = haversine_distance(n_lat, n_lon, b["lat"], b["lon"])
            if d <= radius_meters:
                nearby_speeds.append(b.get("speed", 0.0))

        bus_count = len(nearby_speeds)
        if bus_count >= 3:
            avg_speed = sum(nearby_speeds) / bus_count
            crawl_count = sum(1 for s in nearby_speeds if s < 5.0)
            crawl_ratio = crawl_count / bus_count

            # Tiêu chí ùn tắc:
            # 1. Vận tốc trung bình < 13 km/h (khi có >= 3 xe), HOẶC
            # 2. Tỷ lệ xe dừng/bò (v < 5 km/h) >= 35% (khi có >= 4 xe)
            node_congested = (avg_speed < 13.0) or (bus_count >= 4 and crawl_ratio >= 0.35)

            details[name] = {
                "bus_count": bus_count,
                "avg_speed": round(avg_speed, 1),
                "crawl_ratio": round(crawl_ratio, 2),
                "is_congested": node_congested
            }

            if node_congested:
                congested_nodes.append(name)
                if is_core and (avg_speed < 10.0 or crawl_ratio >= 0.50):
                    has_critical_core_congestion = True

    # Ùn tắc hành lang: Có từ 2 nút bị tắc trở lên hoặc có 1 nút lõi tắc nghiêm trọng
    is_corridor_congested = (len(congested_nodes) >= 2) or has_critical_core_congestion

    return {
        "is_congested": is_corridor_congested,
        "congested_nodes": congested_nodes,
        "details": details
    }

def main():
    run_24x7 = "--24x7" in sys.argv or "--always" in sys.argv
    single_test = "--test" in sys.argv

    os.makedirs(BUS_OUTPUT_DIR, exist_ok=True)
    os.makedirs(TOMTOM_OUTPUT_DIR, exist_ok=True)
    os.makedirs("data/metadata", exist_ok=True)

    if not os.path.exists(CONFIG_FILE):
        print(f"[ERROR] Chua tim thay file cau hinh: {CONFIG_FILE}", flush=True)
        return

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)

    target_vehicles = config.get("vehicles", [])
    target_route_ids = set(config.get("target_route_ids", []))
    v_ids = [v["id"] for v in target_vehicles if "id" in v]
    tomtom_key = get_tomtom_api_key()
    hf_token = get_hf_token()

    quota_state = load_tomtom_quota_state()
    current_day = datetime.now().day
    current_month = datetime.now().month
    last_tomtom_poll = 0
    last_hf_sync = time.time()
    kinematic_cache = {}  # {vid: {"lat": ..., "lon": ..., "epoch": ..., "smoothed_speed": ...}}
    round_no = 1
    is_congested = False

    print("=" * 75, flush=True)
    print("🚀 HỆ THỐNG CRAWLER 24/7 - MẠNG LƯỚI HÀNH LANG BÁCH KHOA (220 XE BUÝT)", flush=True)
    print(f"📍 Quy mô theo dõi: {len(target_route_ids)} tuyến hành lang ({len(v_ids)} xe buýt probe)", flush=True)
    print(f"🌊 Cơ chế Pacing: Trải đều micro-batches (~4 req/s liên tục, không dồn burst)", flush=True)
    print(f"🚦 Điểm nghẽn TomTom: {len(HUST_BOTTLENECK_NODES)} nút giao + 1 Incident BBox hành lang", flush=True)
    print(f"📊 Hạn mức TomTom: Flow {MAX_TOMTOM_FLOW_DAILY}/ngày (tháng 20k) | Incident {MAX_TOMTOM_INCIDENT_DAILY}/ngày (tháng 2.5k)", flush=True)
    print(f"⏰ Khung giờ hoạt động: {'24/7 (Bắt buộc)' if run_24x7 else '05:00 - 22:00 (Tự động ngủ ban đêm)'}", flush=True)
    print(f"🔑 TomTom API Key: {'Đã nạp' if tomtom_key else 'Thiếu key'}", flush=True)
    print(f"☁️ Cloud Sync (Hugging Face): {'Đã kích hoạt (Mỗi 10 phút)' if hf_token else 'Tắt (Lưu 100% trong máy)'}", flush=True)
    print("=" * 75, flush=True)

    while True:
        try:
            now = datetime.now()
            # Reset counter on new day or month
            if now.month != current_month:
                quota_state["flow_month"] = 0
                quota_state["incident_month"] = 0
                quota_state["flow_today"] = 0
                quota_state["incident_today"] = 0
                current_month = now.month
                current_day = now.day
                save_tomtom_quota_state(quota_state)
            elif now.day != current_day:
                quota_state["flow_today"] = 0
                quota_state["incident_today"] = 0
                current_day = now.day
                save_tomtom_quota_state(quota_state)

            # Check operating hours
            if not is_operating_hours(run_24x7):
                print(f"[{now.strftime('%H:%M:%S')}] 🌙 Ngoài khung giờ xe buýt (22:00 - 05:00). Hệ thống nghỉ ngơi...", flush=True)
                time.sleep(300)
                continue

            round_start = time.time()
            date_str = now.strftime("%Y-%m-%d")
            hour_str = now.strftime("%H")
            bus_out_file = os.path.join(BUS_OUTPUT_DIR, f"bus_telemetry_{date_str}_{hour_str}.jsonl")
            traffic_out_file = os.path.join(TOMTOM_OUTPUT_DIR, f"tomtom_flow_{date_str}.jsonl")
            incident_out_file = os.path.join(TOMTOM_OUTPUT_DIR, f"tomtom_incidents_{date_str}.jsonl")

            # -------------------------------------------------------------
            # 1. CRAWL 220 BUSES VỚI CƠ CHẾ PACING TRẢI ĐỀU (MICRO-BATCHING)
            # -------------------------------------------------------------
            bus_records = []
            active_count = 0
            depot_count = 0
            stale_count = 0

            # Chia 220 xe thành các micro-batch 8 xe
            batch_size = 8
            micro_batches = [v_ids[i:i + batch_size] for i in range(0, len(v_ids), batch_size)]
            
            # Pacing delay giữa các micro-batch (28 batches x ~0.85s ≈ 24-28 giây)
            micro_delay = 0.05 if single_test else 0.35

            for b_idx, batch in enumerate(micro_batches):
                with ThreadPoolExecutor(max_workers=batch_size) as executor:
                    futures = {executor.submit(fetch_single_bus_raw, vid): vid for vid in batch}
                    for fut in futures:
                        vid = futures[fut]
                        raw_res = fut.result()
                        if raw_res:
                            clean_rec = sanitize_and_validate_telemetry(
                                raw_res, vid, target_route_ids, kinematic_cache, now.isoformat()
                            )
                            if clean_rec:
                                bus_records.append(clean_rec)
                                status = clean_rec["quality_status"]
                                if status == "ACTIVE_VALID":
                                    active_count += 1
                                elif status == "IDLE_DEPOT":
                                    depot_count += 1
                                elif status == "STALE_PING":
                                    stale_count += 1

                # Nghỉ đệm pacing mượt mà
                time.sleep(micro_delay)

            # Lưu file dữ liệu xe buýt cục bộ
            if bus_records:
                with open(bus_out_file, "a", encoding="utf-8") as f:
                    for rec in bus_records:
                        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

            # Watchdog kiểm tra tỷ lệ xe phản hồi
            total_vids = len(v_ids)
            resp_rate = (len(bus_records) / total_vids) if total_vids > 0 else 0
            if resp_rate < 0.60:
                print(f"   ⚠️ [WATCHDOG] Cảnh báo: Tỷ lệ xe phản hồi thấp ({len(bus_records)}/{total_vids} = {resp_rate*100:.1f}%).", flush=True)

            # -------------------------------------------------------------
            # 2. ĐÁNH GIÁ ÙN TẮC & ĐIỀU CHỈNH CHU KỲ TOMTOM ĐỘNG
            # -------------------------------------------------------------
            congestion_eval = evaluate_hotspot_congestion(bus_records, HUST_BOTTLENECK_NODES)
            prev_congested = is_congested
            is_congested = congestion_eval["is_congested"]

            hour_val = now.hour + now.minute / 60.0
            is_peak = (6.5 <= hour_val <= 9.0) or (16.5 <= hour_val <= 19.5)
            
            # Cao điểm hoặc ùn tắc: chu kỳ 18 phút (1080s); Bình thường thấp điểm: 54 phút (3240s)
            tomtom_interval = 1080 if (is_peak or is_congested) else 3240
            next_tomtom_in = max(0, tomtom_interval - (time.time() - last_tomtom_poll))

            if is_congested and not prev_congested:
                print(f"   🚨 [DYN-CONGESTION] Phát hiện ùn tắc tại {len(congestion_eval['congested_nodes'])} nút: {congestion_eval['congested_nodes']}. Rút ngắn chu kỳ TomTom xuống 18 phút!", flush=True)

            # -------------------------------------------------------------
            # 3. CRAWL TOMTOM (Kiểm soát hạn mức ngày và tháng)
            # -------------------------------------------------------------
            if tomtom_key and not TOMTOM_CIRCUIT_OPEN and (time.time() - last_tomtom_poll >= tomtom_interval or (single_test and round_no == 1)):
                can_flow = (quota_state["flow_today"] + len(HUST_BOTTLENECK_NODES) <= MAX_TOMTOM_FLOW_DAILY) and (quota_state["flow_month"] + len(HUST_BOTTLENECK_NODES) <= 20000)
                can_incident = (quota_state["incident_today"] + 1 <= MAX_TOMTOM_INCIDENT_DAILY) and (quota_state["incident_month"] + 1 <= 2500)

                traffic_records = []
                incident_records = []

                # A. 19 Flow Segments
                if can_flow:
                    for node in HUST_BOTTLENECK_NODES:
                        flow_res = fetch_tomtom_flow(node["lat"], node["lon"], tomtom_key)
                        quota_state["flow_today"] += 1
                        quota_state["flow_month"] += 1
                        if flow_res:
                            raw_coords = flow_res.get("coordinates", {}).get("coordinate", [])
                            seg_coords = [[round(c["longitude"], 6), round(c["latitude"], 6)] for c in raw_coords if "longitude" in c and "latitude" in c]
                            traffic_records.append({
                                "timestamp": now.isoformat(),
                                "node_name": node["name"],
                                "lat": node["lat"],
                                "lon": node["lon"],
                                "current_speed": flow_res.get("currentSpeed"),
                                "free_flow_speed": flow_res.get("freeFlowSpeed"),
                                "travel_time": flow_res.get("currentTravelTime"),
                                "confidence": flow_res.get("confidence"),
                                "road_closure": flow_res.get("roadClosure", False),
                                "coordinates": seg_coords
                            })
                        time.sleep(0.08)  # 80ms throttle

                    if traffic_records:
                        with open(traffic_out_file, "a", encoding="utf-8") as f:
                            for tr in traffic_records:
                                f.write(json.dumps(tr, ensure_ascii=False) + "\n")

                # B. 1 Incident BBox Request
                if can_incident:
                    raw_incidents = fetch_tomtom_incidents(tomtom_key)
                    quota_state["incident_today"] += 1
                    quota_state["incident_month"] += 1
                    for inc in raw_incidents:
                        props = inc.get("properties", {})
                        geom = inc.get("geometry", {})
                        events = props.get("events", [])
                        desc = events[0].get("description", "") if events else ""
                        incident_records.append({
                            "timestamp": now.isoformat(),
                            "incident_id": props.get("id", ""),
                            "icon_category": props.get("iconCategory", 0),
                            "magnitude_of_delay": props.get("magnitudeOfDelay", 0),
                            "delay_seconds": props.get("delay", 0),
                            "length_meters": round(props.get("length", 0), 2),
                            "description": desc,
                            "geometry_type": geom.get("type", "LineString"),
                            "coordinates": geom.get("coordinates", [])
                        })
                    if incident_records:
                        with open(incident_out_file, "a", encoding="utf-8") as f:
                            for ir in incident_records:
                                f.write(json.dumps(ir, ensure_ascii=False) + "\n")

                last_tomtom_poll = time.time()
                save_tomtom_quota_state(quota_state)
                next_tomtom_in = tomtom_interval

            # -------------------------------------------------------------
            # 4. TRÌNH DIỄN DASHBOARD CLI TRỰC QUAN
            # -------------------------------------------------------------
            elapsed = time.time() - round_start
            tt_dashboard = render_tomtom_cli_bar(quota_state, next_tomtom_in, is_congested, TOMTOM_CIRCUIT_OPEN)
            
            print(f"[{now.strftime('%H:%M:%S')}] [Vòng {round_no:03d}] "
                  f"🚌 Xe buýt: {len(bus_records)}/{len(v_ids)} phản hồi "
                  f"({active_count} lăn bánh, {depot_count} đỗ bãi, {stale_count} lặp) | "
                  f"{elapsed:.1f}s", flush=True)
            print(f"   {tt_dashboard}", flush=True)
            round_no += 1

            # -------------------------------------------------------------
            # 5. ĐỒNG BỘ ĐỊNH KỲ LÊN HUGGING FACE DATASET
            # -------------------------------------------------------------
            if hf_token and not single_test and (time.time() - last_hf_sync >= HF_SYNC_INTERVAL):
                sync_to_hf(bus_out_file, traffic_out_file, incident_out_file, date_str, hf_token)
                last_hf_sync = time.time()

            if single_test:
                print("\n[INFO] Test run 1 vòng 220 xe hoàn tất thành công! Dừng tiến trình.", flush=True)
                break

            sleep_wait = max(3, BUS_POLL_INTERVAL - elapsed)
            time.sleep(sleep_wait)

        except KeyboardInterrupt:
            print("\n[INFO] Người dùng bấm Ctrl+C. Đang dừng Crawler an toàn...", flush=True)
            save_tomtom_quota_state(quota_state)
            break
        except Exception as err:
            print(f"⚠️ [CẢNH BÁO] Có lỗi tạm thời trong vòng lặp ({err}). Tự động tiếp tục sau 5s...", flush=True)
            time.sleep(5)

if __name__ == "__main__":
    main()
