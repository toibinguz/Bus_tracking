"""
Production Multi-Tier Crawler for HUST Bus Cluster (5 Routes, 52 Buses)
Author: Antigravity Big Data Architecture Team
Target Operating Schedule: 05:00 - 22:00 (Daily) or 24/7 with flag
"""

import os
import sys
import json
import time
import socket
import ssl
import urllib.request
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

BUS_POLL_INTERVAL = 60 # seconds (each bus cycle)
HF_SYNC_INTERVAL = 600 # seconds (sync to Cloud every 10 mins if token available)
MAX_TOMTOM_DAILY = 2200

# Top 19 critical bottlenecks for HUST cluster routes
HUST_BOTTLENECK_NODES = [
    {"name": "Kim_Lien_Ham_Chui", "lat": 21.0084, "lon": 105.8427, "weight": "core"},
    {"name": "Dai_Co_Viet_Pho_Hue", "lat": 21.0092, "lon": 105.8503, "weight": "core"},
    {"name": "Nga_Tu_Vong", "lat": 20.9987, "lon": 105.8415, "weight": "core"},
    {"name": "Le_Thanh_Nghi_Bach_Mai", "lat": 21.0028, "lon": 105.8497, "weight": "core"},
    {"name": "Nga_Tu_Cau_Giay", "lat": 21.0315, "lon": 105.8016, "weight": "route_32_26"},
    {"name": "Nga_Tu_Mai_Dich", "lat": 21.0378, "lon": 105.7788, "weight": "route_32_26"},
    {"name": "Cau_Dien_QL32", "lat": 21.0422, "lon": 105.7582, "weight": "route_32"},
    {"name": "Nhon_DH_Cong_Nghiep", "lat": 21.0543, "lon": 105.7351, "weight": "route_32"},
    {"name": "Pham_Ngoc_Thach_DH_Y", "lat": 21.0089, "lon": 105.8324, "weight": "route_26"},
    {"name": "Chua_Boc_Tay_Son", "lat": 21.0097, "lon": 105.8239, "weight": "route_26"},
    {"name": "Huynh_Thuc_Khang_NCT", "lat": 21.0211, "lon": 105.8118, "weight": "route_26"},
    {"name": "Nga_Tu_So", "lat": 21.0012, "lon": 105.8197, "weight": "route_21A"},
    {"name": "Nguyen_Trai_Khuat_Duy_Tien", "lat": 20.9922, "lon": 105.8005, "weight": "route_21A"},
    {"name": "Nguyen_Trai_Cau_Trang", "lat": 20.9765, "lon": 105.7832, "weight": "route_21A"},
    {"name": "Trang_Tien_Bo_Ho", "lat": 21.0251, "lon": 105.8542, "weight": "route_31"},
    {"name": "Yen_Phu_Cau_Chuong_Duong", "lat": 21.0415, "lon": 105.8552, "weight": "route_31"},
    {"name": "Nghi_Tam_Au_Co", "lat": 21.0665, "lon": 105.8285, "weight": "route_31"},
    {"name": "Giai_Phong_Kim_Dong_Giap_Bat", "lat": 20.9812, "lon": 105.8422, "weight": "route_08A_32_21A"},
    {"name": "Ngoc_Hoi_Phan_Trong_Tue", "lat": 20.9498, "lon": 105.8451, "weight": "route_08A"}
]

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

def sync_to_hf(local_bus_file, local_traffic_file, date_str, token):
    if not token:
        return
    try:
        from huggingface_hub import HfApi
        api = HfApi(token=token)
        
        if local_bus_file and os.path.exists(local_bus_file):
            repo_bus_path = f"raw_data/{date_str}/bus/{os.path.basename(local_bus_file)}"
            api.upload_file(
                path_or_fileobj=local_bus_file,
                path_in_repo=repo_bus_path,
                repo_id=HF_DATASET_ID,
                repo_type="dataset",
                commit_message=f"Sync {os.path.basename(local_bus_file)}"
            )

        if local_traffic_file and os.path.exists(local_traffic_file):
            repo_traffic_path = f"raw_data/{date_str}/traffic/{os.path.basename(local_traffic_file)}"
            api.upload_file(
                path_or_fileobj=local_traffic_file,
                path_in_repo=repo_traffic_path,
                repo_id=HF_DATASET_ID,
                repo_type="dataset",
                commit_message=f"Sync {os.path.basename(local_traffic_file)}"
            )
        print(f"   ☁️ [HF-Sync] Đồng bộ thành công lên Dataset {HF_DATASET_ID}", flush=True)
    except Exception as e:
        print(f"   ⚠️ [HF-Sync] Tạm thời chưa đẩy được lên Cloud ({e}). Dữ liệu đã lưu an toàn tại máy.", flush=True)

def fetch_single_bus(vehicle_id):
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
    req = urllib.request.Request(url, headers={"User-Agent": "HUSTBusCrawler/1.0"})
    try:
        with urllib.request.urlopen(req, context=ssl_context, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("flowSegmentData")
    except Exception:
        return None

def main():
    run_24x7 = "--24x7" in sys.argv or "--always" in sys.argv
    single_test = "--test" in sys.argv

    os.makedirs(BUS_OUTPUT_DIR, exist_ok=True)
    os.makedirs(TOMTOM_OUTPUT_DIR, exist_ok=True)

    if not os.path.exists(CONFIG_FILE):
        print(f"[ERROR] Chua tim thay file cau hinh: {CONFIG_FILE}")
        return

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)

    target_vehicles = config.get("vehicles", [])
    v_ids = [v["id"] for v in target_vehicles if "id" in v]
    tomtom_key = get_tomtom_api_key()
    hf_token = get_hf_token()

    print("=" * 70, flush=True)
    print("🚀 HỆ THỐNG CRAWLER 24/7 - CỤM TUYẾN BÁCH KHOA (HUST CLUSTER)", flush=True)
    print(f"📍 Tuyến theo dõi: 32, 31, 08A, 26, 21A ({len(v_ids)} xe buýt)", flush=True)
    print(f"🚦 Điểm nghẽn TomTom: {len(HUST_BOTTLENECK_NODES)} nút giao trọng yếu", flush=True)
    print(f"⏰ Khung giờ hoạt động: {'24/7 (Bắt buộc)' if run_24x7 else '05:00 - 22:00 (Tự động ngủ ban đêm)'}", flush=True)
    print(f"🔑 TomTom API Key: {'Đã nạp' if tomtom_key else 'Thiếu key'}", flush=True)
    print(f"☁️ Cloud Sync (Hugging Face): {'Đã kích hoạt (Mỗi 10 phút)' if hf_token else 'Tắt (Lưu 100% trong máy)'}", flush=True)
    print("=" * 70, flush=True)

    daily_tomtom_count = 0
    current_day = datetime.now().day
    last_tomtom_poll = 0
    last_hf_sync = time.time()
    round_no = 1

    while True:
        try:
            now = datetime.now()
            # Reset counter on new day
            if now.day != current_day:
                daily_tomtom_count = 0
                current_day = now.day

            # Check operating hours
            if not is_operating_hours(run_24x7):
                print(f"[{now.strftime('%H:%M:%S')}] 🌙 Ngoài khung giờ xe buýt (22:00 - 05:00). Hệ thống nghỉ ngơi...", flush=True)
                time.sleep(300) # Sleep 5 minutes and check again
                continue

            round_start = time.time()
            date_str = now.strftime("%Y-%m-%d")
            hour_str = now.strftime("%H")
            bus_out_file = os.path.join(BUS_OUTPUT_DIR, f"bus_telemetry_{date_str}_{hour_str}.jsonl")
            traffic_out_file = os.path.join(TOMTOM_OUTPUT_DIR, f"tomtom_flow_{date_str}.jsonl")

            # 1. CRAWL 52 BUSES
            bus_records = []
            with ThreadPoolExecutor(max_workers=6) as executor:
                futures = {executor.submit(fetch_single_bus, vid): vid for vid in v_ids}
                for fut in futures:
                    res = fut.result()
                    if res:
                        res["crawled_at"] = now.isoformat()
                        bus_records.append(res)
                    time.sleep(0.03)

            if bus_records:
                with open(bus_out_file, "a", encoding="utf-8") as f:
                    for rec in bus_records:
                        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

            # 2. CRAWL TOMTOM BOTTLENECKS (Peak: every 6 mins, Off-peak: every 12 mins)
            hour_val = now.hour + now.minute / 60.0
            is_peak = (6.5 <= hour_val <= 9.0) or (16.5 <= hour_val <= 19.5)
            tomtom_interval = 360 if is_peak else 720 # 6 mins or 12 mins

            tomtom_sampled = 0
            if tomtom_key and (time.time() - last_tomtom_poll >= tomtom_interval):
                if daily_tomtom_count + len(HUST_BOTTLENECK_NODES) < MAX_TOMTOM_DAILY:
                    traffic_records = []
                    for node in HUST_BOTTLENECK_NODES:
                        flow_res = fetch_tomtom_flow(node["lat"], node["lon"], tomtom_key)
                        daily_tomtom_count += 1
                        tomtom_sampled += 1
                        if flow_res:
                            traffic_records.append({
                                "timestamp": now.isoformat(),
                                "node_name": node["name"],
                                "lat": node["lat"],
                                "lon": node["lon"],
                                "current_speed": flow_res.get("currentSpeed"),
                                "free_flow_speed": flow_res.get("freeFlowSpeed"),
                                "travel_time": flow_res.get("currentTravelTime"),
                                "confidence": flow_res.get("confidence")
                            })
                        time.sleep(0.1) # 100ms throttle

                    if traffic_records:
                        with open(traffic_out_file, "a", encoding="utf-8") as f:
                            for tr in traffic_records:
                                f.write(json.dumps(tr, ensure_ascii=False) + "\n")
                    last_tomtom_poll = time.time()

            elapsed = time.time() - round_start
            tomtom_info = f"TomTom: +{tomtom_sampled} reqs ({daily_tomtom_count}/{MAX_TOMTOM_DAILY})" if tomtom_sampled > 0 else f"TomTom: Chờ chu kỳ ({daily_tomtom_count}/{MAX_TOMTOM_DAILY})"
            print(f"[{now.strftime('%H:%M:%S')}] [Vòng {round_no:03d}] 🚌 Xe buýt: {len(bus_records)}/{len(v_ids)} xe hoạt động | {tomtom_info} | {elapsed:.1f}s", flush=True)
            round_no += 1

            # 3. PERIODIC CLOUD SYNC (Mỗi 10 phút hoặc khi test)
            if hf_token and (time.time() - last_hf_sync >= HF_SYNC_INTERVAL or single_test):
                sync_to_hf(bus_out_file, traffic_out_file, date_str, hf_token)
                last_hf_sync = time.time()

            if single_test:
                print("\n[INFO] Test run 1 vòng hoàn tất thành công! Dừng tiến trình.", flush=True)
                break

            sleep_wait = max(5, BUS_POLL_INTERVAL - elapsed)
            time.sleep(sleep_wait)

        except KeyboardInterrupt:
            print("\n[INFO] Người dùng bấm Ctrl+C. Đang dừng Crawler an toàn...", flush=True)
            break
        except Exception as err:
            print(f"⚠️ [CẢNH BÁO] Có lỗi tạm thời trong vòng lặp ({err}). Tự động tiếp tục sau 10s...", flush=True)
            time.sleep(10)

if __name__ == "__main__":
    main()

