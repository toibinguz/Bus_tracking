"""
Single-step Cloud Crawler for GitHub Actions -> Hugging Face Dataset
Author: Antigravity Big Data Architecture Team
Target: Run every 5-10 minutes on GitHub Actions runner
"""

import os
import sys
import json
import time
import socket
import ssl
import urllib.request
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor

# Force UTF-8 encoding
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

# Bottlenecks around HUST routes
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

def fetch_single_bus(v_id):
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
        with socket.create_connection(("api.busmap.city", 443), timeout=3) as s:
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

def fetch_tomtom_flow(lat, lon, api_key):
    url = f"https://api.tomtom.com/traffic/services/4/flowSegmentData/relative0/10/json?key={api_key}&point={lat},{lon}&unit=KMPH"
    req = urllib.request.Request(url, headers={"User-Agent": "GitHubActionsBusCrawler/1.0"})
    try:
        with urllib.request.urlopen(req, context=ssl_context, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("flowSegmentData")
    except Exception:
        return None

def main():
    hn_time = get_hanoi_time()
    ts_str = hn_time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts_str}] Khoi chay Cloud Crawler Step tren GitHub Actions...")

    if not is_operating_hours(hn_time) and "--force" not in sys.argv:
        print(f"[{ts_str}] NGoai khung gio xe buyt (22:00 - 05:00). Ket thuc som de tiet kiem runner.")
        return

    if not os.path.exists(CONFIG_FILE):
        print(f"[ERROR] Khong tim thay {CONFIG_FILE}!")
        return

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)
    v_ids = [v["id"] for v in config.get("vehicles", []) if "id" in v]

    # 1. Thu thap GPS 52 xe buyt
    bus_records = []
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(fetch_single_bus, vid): vid for vid in v_ids}
        for fut in futures:
            res = fut.result()
            if res:
                res["crawled_at"] = hn_time.isoformat()
                bus_records.append(res)
            time.sleep(0.02)

    # 2. Thu thap TomTom 19 nut giao
    traffic_records = []
    if TOMTOM_KEY:
        for node in HUST_BOTTLENECK_NODES:
            res = fetch_tomtom_flow(node["lat"], node["lon"], TOMTOM_KEY)
            if res:
                traffic_records.append({
                    "timestamp": hn_time.isoformat(),
                    "node_name": node["name"],
                    "current_speed": res.get("currentSpeed"),
                    "free_flow_speed": res.get("freeFlowSpeed"),
                    "travel_time": res.get("currentTravelTime")
                })
            time.sleep(0.08)

    print(f"[{ts_str}] Thu thap thanh cong: {len(bus_records)}/{len(v_ids)} xe buyt | {len(traffic_records)}/{len(HUST_BOTTLENECK_NODES)} nut giao TomTom")

    # 3. Luu file tam de day len Hugging Face Dataset
    tmp_dir = "temp_cloud_output"
    os.makedirs(tmp_dir, exist_ok=True)
    date_tag = hn_time.strftime("%Y-%m-%d")
    time_tag = hn_time.strftime("%H%M%S")

    bus_chunk = os.path.join(tmp_dir, f"bus_{time_tag}.jsonl")
    with open(bus_chunk, "w", encoding="utf-8") as f:
        for r in bus_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    traffic_chunk = os.path.join(tmp_dir, f"traffic_{time_tag}.jsonl")
    with open(traffic_chunk, "w", encoding="utf-8") as f:
        for r in traffic_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # 4. Day len Hugging Face Dataset (neu co HF_TOKEN)
    if HF_TOKEN and HF_DATASET_ID:
        try:
            from huggingface_hub import HfApi
            api = HfApi(token=HF_TOKEN)
            
            # Upload bus chunk
            repo_bus_path = f"raw_data/{date_tag}/bus/chunk_{time_tag}.jsonl"
            api.upload_file(
                path_or_fileobj=bus_chunk,
                path_in_repo=repo_bus_path,
                repo_id=HF_DATASET_ID,
                repo_type="dataset",
                commit_message=f"Ping {len(bus_records)} buses at {ts_str}"
            )
            print(f"[OK] Da day bus chunk len HF Dataset: {repo_bus_path}")

            # Upload traffic chunk
            if traffic_records:
                repo_traffic_path = f"raw_data/{date_tag}/traffic/chunk_{time_tag}.jsonl"
                api.upload_file(
                    path_or_fileobj=traffic_chunk,
                    path_in_repo=repo_traffic_path,
                    repo_id=HF_DATASET_ID,
                    repo_type="dataset",
                    commit_message=f"Ping {len(traffic_records)} traffic nodes at {ts_str}"
                )
                print(f"[OK] Da day traffic chunk len HF Dataset: {repo_traffic_path}")

        except Exception as e:
            print(f"[WARN] Loi upload HF Dataset: {e}")
    else:
        print("[INFO] Khong co HF_TOKEN hoac HF_DATASET_ID. Chi ghi file cuc bo.")

if __name__ == "__main__":
    main()

