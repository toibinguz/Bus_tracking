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
    {"name": "Kim_Lien_Ham_Chui", "lat": 21.0084, "lon": 105.8427},
    {"name": "Dai_Co_Viet_Pho_Hue", "lat": 21.0092, "lon": 105.8503},
    {"name": "Nga_Tu_Vong", "lat": 20.9987, "lon": 105.8415},
    {"name": "Le_Thanh_Nghi_Bach_Mai", "lat": 21.0028, "lon": 105.8497},
    {"name": "Nga_Tu_Cau_Giay", "lat": 21.0315, "lon": 105.8016},
    {"name": "Nga_Tu_Mai_Dich", "lat": 21.0378, "lon": 105.7788},
    {"name": "Cau_Dien_QL32", "lat": 21.0422, "lon": 105.7582},
    {"name": "Nhon_DH_Cong_Nghiep", "lat": 21.0543, "lon": 105.7351},
    {"name": "Pham_Ngoc_Thach_DH_Y", "lat": 21.0089, "lon": 105.8324},
    {"name": "Chua_Boc_Tay_Son", "lat": 21.0097, "lon": 105.8239},
    {"name": "Huynh_Thuc_Khang_NCT", "lat": 21.0211, "lon": 105.8118},
    {"name": "Nga_Tu_So", "lat": 21.0012, "lon": 105.8197},
    {"name": "Nguyen_Trai_Khuat_Duy_Tien", "lat": 20.9922, "lon": 105.8005},
    {"name": "Nguyen_Trai_Cau_Trang", "lat": 20.9765, "lon": 105.7832},
    {"name": "Trang_Tien_Bo_Ho", "lat": 21.0251, "lon": 105.8542},
    {"name": "Yen_Phu_Cau_Chuong_Duong", "lat": 21.0415, "lon": 105.8552},
    {"name": "Nghi_Tam_Au_Co", "lat": 21.0665, "lon": 105.8285},
    {"name": "Giai_Phong_Kim_Dong_Giap_Bat", "lat": 20.9812, "lon": 105.8422},
    {"name": "Ngoc_Hoi_Phan_Trong_Tue", "lat": 20.9498, "lon": 105.8451}
]

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

def sanitize_and_validate_telemetry(raw, vid, target_route_ids, last_updates_cache, crawl_time_iso):
    if not raw:
        return None

    try:
        std_lon = float(raw.get("Lat", 0.0))
        std_lat = float(raw.get("Lng", 0.0))
    except (ValueError, TypeError):
        return None

    speed = float(raw.get("Speed", 0.0))
    direction = int(raw.get("direction", 0))
    route_id = int(raw.get("RouteId", 0))
    last_update = raw.get("lastUpdateTime", "")
    station_id = raw.get("currentStationId", 0)

    quality_status = "ACTIVE_VALID"

    if direction == -1 and speed == 0 and station_id == 0:
        quality_status = "IDLE_DEPOT"
    elif not (HANOI_BBOX["min_lat"] <= std_lat <= HANOI_BBOX["max_lat"] and
              HANOI_BBOX["min_lon"] <= std_lon <= HANOI_BBOX["max_lon"]):
        quality_status = "OUT_OF_BOUNDS"
    elif route_id not in target_route_ids:
        quality_status = "REASSIGNED_ROUTE"
    elif speed > 90.0:
        quality_status = "SPEED_ANOMALY"
    elif vid in last_updates_cache and last_updates_cache[vid] == last_update:
        quality_status = "STALE_PING"

    last_updates_cache[vid] = last_update

    return {
        "vehicle_id": vid,
        "plate": raw.get("VehicleNumber", ""),
        "route_id": route_id,
        "lat": round(std_lat, 6),
        "lon": round(std_lon, 6),
        "speed": speed,
        "direction": direction,
        "heading_deg": raw.get("Deg", 0),
        "current_station_id": station_id,
        "next_station_id": raw.get("nextStationId", 0),
        "device_update_time": last_update,
        "crawled_at": crawl_time_iso,
        "quality_status": quality_status
    }

def fetch_tomtom_flow(lat, lon, api_key):
    url = f"https://api.tomtom.com/traffic/services/4/flowSegmentData/relative0/10/json?key={api_key}&point={lat},{lon}&unit=KMPH"
    req = urllib.request.Request(url, headers={"User-Agent": "GitHubActionsBusCrawler/2.0"})
    try:
        with urllib.request.urlopen(req, context=ssl_context, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("flowSegmentData")
    except Exception:
        return None

def upload_batches_to_hf_native(bus_chunk, traffic_chunk, date_tag, time_tag, token):
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

    if not operations:
        return

    commit_url = f"https://huggingface.co/api/datasets/{HF_DATASET_ID}/commit/main"
    payload = {
        "operations": operations,
        "summary": f"Cloud Relay Batch ({date_tag} {time_tag}): {len(operations)} files"
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        commit_url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
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
    round_no = 1
    
    all_session_bus_records = []
    traffic_records = []
    last_updates_cache = {}

    # Chinh sach TomTom:
    # Gio cao diem (06:30-09:00, 16:30-19:30): Moi phien 9 phut goi 1 lan
    # Gio thap diem: Chi goi o phien chan de gioi han ~1,380 calls/ngay (< 2,200 quota)
    hour_val = hn_time.hour + hn_time.minute / 60.0
    is_peak = (6.5 <= hour_val <= 9.0) or (16.5 <= hour_val <= 19.5)
    should_query_tomtom = is_peak or ((hn_time.minute // 9) % 2 == 0)

    # 1. Thu thap TomTom o dau phien neu du dieu kien
    if TOMTOM_KEY and should_query_tomtom:
        print(f"[{hn_time.strftime('%H:%M:%S')}] 🚦 Thu thap 19 nut giao TomTom ({'Cao diem' if is_peak else 'Thuong'})...", flush=True)
        for node in HUST_BOTTLENECK_NODES:
            res = fetch_tomtom_flow(node["lat"], node["lon"], TOMTOM_KEY)
            if res:
                traffic_records.append({
                    "timestamp": hn_time.isoformat(),
                    "node_name": node["name"],
                    "lat": node["lat"],
                    "lon": node["lon"],
                    "current_speed": res.get("currentSpeed"),
                    "free_flow_speed": res.get("freeFlowSpeed"),
                    "travel_time": res.get("currentTravelTime"),
                    "confidence": res.get("confidence")
                })
            time.sleep(0.08)

    # 2. Vong lap cào GPS 220 xe buyt moi 60 giay voi Micro-batch Pacing
    batch_size = 4
    micro_batches = [v_ids[i:i + batch_size] for i in range(0, len(v_ids), batch_size)]
    single_test = "--test" in sys.argv

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
                            raw_res, vid, target_route_ids, last_updates_cache, cur_hn_time.isoformat()
                        )
                        if clean_rec:
                            round_bus_records.append(clean_rec)
                            if clean_rec["quality_status"] == "ACTIVE_VALID":
                                active_count += 1
                            elif clean_rec["quality_status"] == "IDLE_DEPOT":
                                depot_count += 1

            # Micro-pacing delay (~0.85s giua cac micro-batch de trai deu trong 48s)
            if not single_test:
                time.sleep(0.85)

        all_session_bus_records.extend(round_bus_records)
        round_elapsed = time.time() - round_start
        print(f"[{round_ts}] [Vong {round_no:02d}] 🚌 {len(round_bus_records)}/{len(v_ids)} xe buyt "
              f"({active_count} lan banh, {depot_count} do bai) | {round_elapsed:.1f}s", flush=True)
        round_no += 1

        if single_test or (SESSION_DURATION - (time.time() - session_start)) < 60:
            break

        sleep_wait = max(3, 60 - round_elapsed)
        time.sleep(sleep_wait)

    print(f"\n[SUMMARY] Ket thuc phien: Thu duoc {len(all_session_bus_records)} pings ({round_no-1} vong) va {len(traffic_records)} ban ghi TomTom.", flush=True)

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

    upload_batches_to_hf_native(bus_chunk, traffic_chunk, date_tag, time_tag, HF_TOKEN)

if __name__ == "__main__":
    main()
