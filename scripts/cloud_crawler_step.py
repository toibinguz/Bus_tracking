"""
Single-step Cloud Crawler for GitHub Actions -> Hugging Face Dataset
Author: Antigravity Big Data Architecture Team
Upgrades:
- 220 Corridor Buses with Micro-batch Pacing (~4 req/s, Anti-WAF Stealth)
- Real-time Data Quality & Sanity Guard (Standard WGS84, Depot, Stale, Geofence)
- Two-tier TomTom Dynamic Governor (Peak: every 9m, Off-peak: every 18m -> ~1,380 calls/day)
- Native Zero-Dependency HF Commit API (No pip install required)
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
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

CONFIG_FILE = "data/metadata/hust_cluster_config.json"
HF_DATASET_ID = os.environ.get("HF_DATASET_ID", "Toibinguz/hust-bus-data")
HF_TOKEN = os.environ.get("HF_TOKEN")
TOMTOM_KEY = os.environ.get("TOMTOM_KEY", "")

# Load TomTom key from local file if running locally
if not TOMTOM_KEY and os.path.exists("Test_tomtom/TOMTOM_API_KEY.txt"):
    with open("Test_tomtom/TOMTOM_API_KEY.txt", "r", encoding="utf-8") as f:
        TOMTOM_KEY = f.read().strip()

# Load HF token from local file if running locally
if not HF_TOKEN and os.path.exists("access_token_hf.txt"):
    with open("access_token_hf.txt", "r", encoding="utf-8") as f:
        HF_TOKEN = f.read().strip()

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

def get_hanoi_time():
    # UTC + 7
    return datetime.now(timezone.utc) + timedelta(hours=7)

def is_operating_hours(hn_time):
    hour = hn_time.hour + hn_time.minute / 60.0
    return 5.0 <= hour <= 22.0

def fetch_single_bus_raw(v_id):
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
    R = 6371000.0  # meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2.0)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0)**2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c

def sanitize_and_validate_telemetry(raw, vid, target_route_ids, kinematic_cache, crawl_time_iso):
    if not raw:
        return None

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

    # 1. Parse device timestamp for kinematic velocity
    curr_epoch = time.time()
    if last_update:
        try:
            curr_epoch = datetime.fromisoformat(last_update).timestamp()
        except Exception:
            pass

    # 2. Kinematic Velocity & EMA Smoothing
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
                if v_derived > 80.0:  # City bus cannot exceed 80 km/h in Hanoi
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

HUST_CORRIDOR_BBOX = "105.7500,20.9500,105.9000,21.0800"

def fetch_tomtom_flow(lat, lon, api_key):
    global TOMTOM_CIRCUIT_OPEN
    if TOMTOM_CIRCUIT_OPEN or not api_key:
        return None
    url = f"https://api.tomtom.com/traffic/services/4/flowSegmentData/relative0/10/json?key={api_key}&point={lat},{lon}&unit=KMPH"
    req = urllib.request.Request(url, headers={"User-Agent": "GitHubActionsBusCrawler/2.0"})
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
    req = urllib.request.Request(url, headers={"User-Agent": "GitHubActionsBusCrawler/2.0"})
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

def get_hf_today_traffic_batch_count(date_tag, token):
    """Truy vấn số lượng batch traffic đã tải lên Hugging Face hôm nay để kiểm soát hạn mức ngày."""
    if not token or not HF_DATASET_ID:
        return 0
    url = f"https://huggingface.co/api/datasets/{HF_DATASET_ID}/tree/main/raw_data/{date_tag}/traffic"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, context=ssl_context, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, list):
                return len(data)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return 0
    except Exception:
        pass
    return 0

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

def execute_tomtom_poll(cur_hn_time, api_key):
    """Thực hiện một lượt quét đồng bộ 19 Flow Segments + 1 Incident BBox."""
    flow_records = []
    inc_records = []
    if not api_key or TOMTOM_CIRCUIT_OPEN:
        return flow_records, inc_records

    # A. 19 Flow Segments
    for node in HUST_BOTTLENECK_NODES:
        res = fetch_tomtom_flow(node["lat"], node["lon"], api_key)
        if res:
            raw_coords = res.get("coordinates", {}).get("coordinate", [])
            seg_coords = [[round(c["longitude"], 6), round(c["latitude"], 6)] for c in raw_coords if "longitude" in c and "latitude" in c]
            flow_records.append({
                "timestamp": cur_hn_time.isoformat(),
                "node_name": node["name"],
                "lat": node["lat"],
                "lon": node["lon"],
                "current_speed": res.get("currentSpeed"),
                "free_flow_speed": res.get("freeFlowSpeed"),
                "travel_time": res.get("currentTravelTime"),
                "confidence": res.get("confidence"),
                "road_closure": res.get("roadClosure", False),
                "coordinates": seg_coords
            })
        time.sleep(0.08)

    # B. Incident Details
    raw_incidents = fetch_tomtom_incidents(api_key)
    for inc in raw_incidents:
        props = inc.get("properties", {})
        geom = inc.get("geometry", {})
        events = props.get("events", [])
        desc = events[0].get("description", "") if events else ""
        inc_records.append({
            "timestamp": cur_hn_time.isoformat(),
            "incident_id": props.get("id", ""),
            "icon_category": props.get("iconCategory", 0),
            "magnitude_of_delay": props.get("magnitudeOfDelay", 0),
            "delay_seconds": props.get("delay", 0),
            "length_meters": round(props.get("length", 0), 2),
            "description": desc,
            "geometry_type": geom.get("type", "LineString"),
            "coordinates": geom.get("coordinates", [])
        })

    return flow_records, inc_records

def upload_batches_to_hf_native(bus_chunk, traffic_chunk, incident_chunk, date_tag, time_tag, token):
    if not token or not HF_DATASET_ID:
        print("[INFO] Khong co HF_TOKEN hoac HF_DATASET_ID. Chi ghi file cuc bo.", flush=True)
        return

    operations = []

    if bus_chunk and os.path.exists(bus_chunk):
        with open(bus_chunk, "rb") as f:
            b_bytes = f.read()
        if b_bytes:
            operations.append({
                "key": "file",
                "value": {
                    "path": f"raw_data/{date_tag}/bus/batch_{time_tag}.jsonl",
                    "encoding": "base64",
                    "content": base64.b64encode(b_bytes).decode("ascii")
                }
            })

    if traffic_chunk and os.path.exists(traffic_chunk):
        with open(traffic_chunk, "rb") as f:
            t_bytes = f.read()
        if t_bytes:
            operations.append({
                "key": "file",
                "value": {
                    "path": f"raw_data/{date_tag}/traffic/batch_{time_tag}.jsonl",
                    "encoding": "base64",
                    "content": base64.b64encode(t_bytes).decode("ascii")
                }
            })

    if incident_chunk and os.path.exists(incident_chunk):
        with open(incident_chunk, "rb") as f:
            i_bytes = f.read()
        if i_bytes:
            operations.append({
                "key": "file",
                "value": {
                    "path": f"raw_data/{date_tag}/incidents/batch_{time_tag}.jsonl",
                    "encoding": "base64",
                    "content": base64.b64encode(i_bytes).decode("ascii")
                }
            })

    if not operations:
        return

    commit_url = f"https://huggingface.co/api/datasets/{HF_DATASET_ID}/commit/main"
    ndjson_lines = [
        json.dumps({"key": "header", "value": {"summary": f"Cloud Relay Batch ({date_tag} {time_tag}): {len(operations)} files", "description": ""}}).encode("utf-8")
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
                print(f"[OK] Da day thanh cong {len(operations)} batches len HF Dataset: {HF_DATASET_ID}", flush=True)
            else:
                print(f"[WARN] HF tra ve ma {resp.getcode()}", flush=True)
    except Exception as e:
        print(f"[WARN] Loi upload HF Dataset: {e}", flush=True)

def main():
    hn_time = get_hanoi_time()
    ts_str = hn_time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts_str}] Khoi chay Cloud Crawler Phien 9 Phut tren GitHub Actions...", flush=True)

    if not is_operating_hours(hn_time) and "--force" not in sys.argv:
        print(f"[{ts_str}] Ngoai khung gio xe buyt (22:00 - 05:00). Tam dung day chuyen.", flush=True)
        with open(".stop_chain", "w") as f:
            f.write("night")
        return

    # Xoa file stop_chain neu ton tai truoc do
    if os.path.exists(".stop_chain"):
        try: os.remove(".stop_chain")
        except: pass

    if not os.path.exists(CONFIG_FILE):
        print(f"[ERROR] Khong tim thay {CONFIG_FILE}!", flush=True)
        return

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)
    v_ids = [v["id"] for v in config.get("vehicles", []) if "id" in v]
    target_route_ids = set(config.get("target_route_ids", []))

    print(f"[INFO] Khoi dong phien cào 220 xe buyt ({len(target_route_ids)} tuyen hanh lang)...", flush=True)

    SESSION_DURATION = 540  # 9 phut
    session_start = time.time()
    single_test = "--test" in sys.argv
    round_no = 1
    
    all_session_bus_records = []
    traffic_records = []
    incident_records = []
    kinematic_cache = {}

    # Chinh sach TomTom chuan han muc thang (Monthly Freemium: 20k Flow, 2.5k Incident):
    # Cao diem (06:30-09:00, 16:30-19:30): Moi 18 phut (step_9m % 2 == 0) goi 1 lan
    # Thap diem binh thuong: Moi 54 phut (step_9m % 6 == 0) goi 1 lan
    # Thap diem co UN TAC (xe buyt cham): Rut xuong moi 18 phut (step_9m % 2 == 0)
    # -> Toi da <= 31 dot/ngay * 19 flow = 589 flow/ngay (< 600 budget/ngay)
    date_tag = hn_time.strftime("%Y-%m-%d")
    no_tomtom = "--no-tomtom" in sys.argv
    today_traffic_batches = get_hf_today_traffic_batch_count(date_tag, HF_TOKEN) if (HF_TOKEN and not single_test) else 0
    can_poll_tomtom = (today_traffic_batches < 31) and not TOMTOM_CIRCUIT_OPEN and not no_tomtom

    if today_traffic_batches >= 31 and not single_test:
        print(f"[{ts_str}] 🚦 [BUDGET GOVERNOR] Đã dùng {today_traffic_batches}/31 đợt TomTom hôm nay (~{today_traffic_batches*19}/600 flow). Đạt trần ngân sách ngày an toàn, bỏ qua TomTom.", flush=True)

    total_mins = hn_time.hour * 60 + hn_time.minute
    step_9m = total_mins // 9
    hour_val = hn_time.hour + hn_time.minute / 60.0
    is_peak = (6.5 <= hour_val <= 9.0) or (16.5 <= hour_val <= 19.5)
    baseline_tomtom = single_test or (is_peak and step_9m % 2 == 0) or (not is_peak and step_9m % 6 == 0)

    tomtom_polled_in_session = False

    # 1. Thu thap TomTom o dau phien neu dung lich baseline
    if TOMTOM_KEY and can_poll_tomtom and baseline_tomtom:
        print(f"[{hn_time.strftime('%H:%M:%S')}] 🚦 Thu thap TomTom (19 Flow Segments + 1 Incident BBox, {'Cao diem' if is_peak else 'Thuong'})...", flush=True)
        traffic_records, incident_records = execute_tomtom_poll(hn_time, TOMTOM_KEY)
        tomtom_polled_in_session = True
        print(f"   🚦 Hoan tat: {len(traffic_records)} flow segments (kem seg_line), {len(incident_records)} incidents.", flush=True)

    # 2. Vong lap cào GPS 220 xe buyt moi 60 giay voi Micro-batch Pacing
    batch_size = 8
    micro_batches = [v_ids[i:i + batch_size] for i in range(0, len(v_ids), batch_size)]

    while (time.time() - session_start) < SESSION_DURATION:
        round_start = time.time()
        cur_hn_time = get_hanoi_time()
        round_ts = cur_hn_time.strftime("%H:%M:%S")

        round_bus_records = []
        active_count = 0
        depot_count = 0

        for batch in micro_batches:
            with ThreadPoolExecutor(max_workers=batch_size) as executor:
                futures = {executor.submit(fetch_single_bus_raw, vid): vid for vid in batch}
                for fut in futures:
                    vid = futures[fut]
                    raw_res = fut.result()
                    if raw_res:
                        clean_rec = sanitize_and_validate_telemetry(
                            raw_res, vid, target_route_ids, kinematic_cache, cur_hn_time.isoformat()
                        )
                        if clean_rec:
                            round_bus_records.append(clean_rec)
                            if clean_rec["quality_status"] == "ACTIVE_VALID":
                                active_count += 1
                            elif clean_rec["quality_status"] == "IDLE_DEPOT":
                                depot_count += 1

            # Micro-pacing delay (~0.35s giua cac micro-batch de hoan thanh trong ~25-28s)
            if not single_test:
                time.sleep(0.35)

        all_session_bus_records.extend(round_bus_records)
        round_elapsed = time.time() - round_start
        print(f"[{round_ts}] [Vong {round_no:02d}] 🚌 {len(round_bus_records)}/{len(v_ids)} xe buyt "
              f"({active_count} lan banh, {depot_count} do bai) | {round_elapsed:.1f}s", flush=True)

        # Watchdog: Kiem tra ty le phan hoi xe buyt
        total_vids = len(v_ids)
        resp_rate = (len(round_bus_records) / total_vids) if total_vids > 0 else 0
        if resp_rate < 0.60:
            print(f"   ⚠️ [WATCHDOG] Canh bao: Ty le xe buyt phan hoi thap ({len(round_bus_records)}/{total_vids} = {resp_rate*100:.1f}%).", flush=True)

        # Dynamic Congestion Trigger: Neu chua goi TomTom dau phien, danh gia un tac sau vong 1
        if round_no == 1 and not tomtom_polled_in_session and TOMTOM_KEY and can_poll_tomtom:
            congestion_eval = evaluate_hotspot_congestion(round_bus_records, HUST_BOTTLENECK_NODES)
            if congestion_eval["is_congested"]:
                if (step_9m % 2 == 0):
                    print(f"[{round_ts}] 🚨 [DYN-CONGESTION] Phat hien un tac tai {len(congestion_eval['congested_nodes'])} nut: {congestion_eval['congested_nodes']}. Kich hoat TomTom dong!", flush=True)
                    dyn_flow, dyn_inc = execute_tomtom_poll(cur_hn_time, TOMTOM_KEY)
                    traffic_records.extend(dyn_flow)
                    incident_records.extend(dyn_inc)
                    tomtom_polled_in_session = True
                    print(f"   🚦 Hoan tat quet dong: {len(dyn_flow)} flow segments, {len(dyn_inc)} incidents.", flush=True)

        round_no += 1

        if single_test or (SESSION_DURATION - (time.time() - session_start)) < 60:
            break

        sleep_wait = max(3, 60 - round_elapsed)
        time.sleep(sleep_wait)

    print(f"\n[SUMMARY] Ket thuc phien: Thu duoc {len(all_session_bus_records)} pings ({round_no-1} vong), {len(traffic_records)} TomTom flow va {len(incident_records)} TomTom incidents.", flush=True)

    # 3. Ghi file batch va day len Hugging Face Dataset qua Native Commit API
    tmp_dir = "temp_cloud_output"
    os.makedirs(tmp_dir, exist_ok=True)
    date_tag = hn_time.strftime("%Y-%m-%d")
    time_tag = hn_time.strftime("%H%M%S")

    bus_chunk = os.path.join(tmp_dir, f"bus_batch_{time_tag}.jsonl")
    with open(bus_chunk, "w", encoding="utf-8") as f:
        for r in all_session_bus_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    traffic_chunk = os.path.join(tmp_dir, f"traffic_batch_{time_tag}.jsonl")
    if traffic_records:
        with open(traffic_chunk, "w", encoding="utf-8") as f:
            for r in traffic_records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    incident_chunk = os.path.join(tmp_dir, f"incident_batch_{time_tag}.jsonl")
    if incident_records:
        with open(incident_chunk, "w", encoding="utf-8") as f:
            for r in incident_records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    if single_test:
        print("\n[INFO] Che do --test: Da ghi file batch cuc bo, KHONG day len Hugging Face de bao toan dataset.", flush=True)
    else:
        upload_batches_to_hf_native(bus_chunk, traffic_chunk, incident_chunk, date_tag, time_tag, HF_TOKEN)

if __name__ == "__main__":
    main()
