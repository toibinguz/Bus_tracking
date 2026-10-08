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
MAX_TOMTOM_DAILY = 2200

# Geographic bounding box for Hanoi Urban Core
HANOI_BBOX = {
    "min_lat": 20.80,
    "max_lat": 21.30,
    "min_lon": 105.65,
    "max_lon": 106.05
}

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

def load_tomtom_quota_state():
    today_str = datetime.now().strftime("%Y-%m-%d")
    if os.path.exists(TOMTOM_QUOTA_FILE):
        try:
            with open(TOMTOM_QUOTA_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
                if state.get("date") == today_str:
                    return state.get("used_today", 0)
        except Exception:
            pass
    return 0

def save_tomtom_quota_state(used_today):
    today_str = datetime.now().strftime("%Y-%m-%d")
    os.makedirs(os.path.dirname(TOMTOM_QUOTA_FILE), exist_ok=True)
    state = {
        "date": today_str,
        "daily_limit": MAX_TOMTOM_DAILY,
        "used_today": used_today,
        "remaining_today": max(0, MAX_TOMTOM_DAILY - used_today),
        "last_updated": datetime.now().strftime("%H:%M:%S")
    }
    try:
        with open(TOMTOM_QUOTA_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def render_tomtom_cli_bar(used, limit, next_poll_seconds):
    percent = min(1.0, used / float(limit))
    bar_width = 16
    filled = int(percent * bar_width)
    empty = bar_width - filled
    bar_str = "█" * filled + "░" * empty
    remaining = max(0, limit - used)
    pct_str = f"{percent * 100:.1f}%"
    countdown_str = f"{int(next_poll_seconds // 60):02d}:{int(next_poll_seconds % 60):02d}s" if next_poll_seconds > 0 else "Sẵn sàng"
    return f"🚦 TomTom: [{bar_str}] {used}/{limit} ({pct_str}) | Còn: {remaining:,} reqs | Đợt tới: {countdown_str}"

def sync_to_hf(local_bus_file, local_traffic_file, date_str, token):
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

def sanitize_and_validate_telemetry(raw, vid, target_route_ids, last_updates_cache, crawl_time_iso):
    """
    Chuẩn hóa dữ liệu thực tế và gắn cờ kiểm soát chất lượng (Quality Status)
    Xử lý: Đảo trục tọa độ BusMap, xe đỗ bãi, trôi GPS, xe đổi tuyến, ping đông cứng
    """
    if not raw:
        return None

    # 1. BusMap đảo ngược Lat và Lng: raw["Lat"] là Kinh độ (Lon), raw["Lng"] là Vĩ độ (Lat)
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

    # 2. Đánh giá chất lượng thực tế
    quality_status = "ACTIVE_VALID"

    # Edge Case A: Xe nằm bãi / Đỗ nghỉ đầu bến
    if direction == -1 and speed == 0 and station_id == 0:
        quality_status = "IDLE_DEPOT"
    # Edge Case B: Tọa độ nằm ngoài phạm vi đô thị Hà Nội (Geofence)
    elif not (HANOI_BBOX["min_lat"] <= std_lat <= HANOI_BBOX["max_lat"] and
              HANOI_BBOX["min_lon"] <= std_lon <= HANOI_BBOX["max_lon"]):
        quality_status = "OUT_OF_BOUNDS"
    # Edge Case C: Xe bị điều động luân chuyển sang tuyến ngoài hành lang
    elif route_id not in target_route_ids:
        quality_status = "REASSIGNED_ROUTE"
    # Edge Case D: Vận tốc dị thường (trôi GPS hầm chui / cầu vượt)
    elif speed > 90.0:
        quality_status = "SPEED_ANOMALY"
    # Edge Case E: Ping đông cứng (mất sóng trên xe, server trả tọa độ cũ)
    elif vid in last_updates_cache and last_updates_cache[vid] == last_update:
        quality_status = "STALE_PING"

    last_updates_cache[vid] = last_update

    clean_record = {
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
    return clean_record

def fetch_tomtom_flow(lat, lon, api_key):
    url = f"https://api.tomtom.com/traffic/services/4/flowSegmentData/relative0/10/json?key={api_key}&point={lat},{lon}&unit=KMPH"
    req = urllib.request.Request(url, headers={"User-Agent": "HUSTBusCrawler/2.0"})
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

    daily_tomtom_count = load_tomtom_quota_state()
    current_day = datetime.now().day
    last_tomtom_poll = 0
    last_hf_sync = time.time()
    last_updates_cache = {}  # {vid: lastUpdateTime}
    round_no = 1

    print("=" * 75, flush=True)
    print("🚀 HỆ THỐNG CRAWLER 24/7 - MẠNG LƯỚI HÀNH LANG BÁCH KHOA (220 XE BUÝT)", flush=True)
    print(f"📍 Quy mô theo dõi: {len(target_route_ids)} tuyến hành lang ({len(v_ids)} xe buýt probe)", flush=True)
    print(f"🌊 Cơ chế Pacing: Trải đều 55 micro-batches (~4 req/s liên tục, không dồn burst)", flush=True)
    print(f"🚦 Điểm nghẽn TomTom: {len(HUST_BOTTLENECK_NODES)} nút giao trọng yếu", flush=True)
    print(f"⏰ Khung giờ hoạt động: {'24/7 (Bắt buộc)' if run_24x7 else '05:00 - 22:00 (Tự động ngủ ban đêm)'}", flush=True)
    print(f"🔑 TomTom API Key: {'Đã nạp' if tomtom_key else 'Thiếu key'}", flush=True)
    print(f"☁️ Cloud Sync (Hugging Face): {'Đã kích hoạt (Mỗi 10 phút)' if hf_token else 'Tắt (Lưu 100% trong máy)'}", flush=True)
    print("=" * 75, flush=True)

    while True:
        try:
            now = datetime.now()
            # Reset counter on new day
            if now.day != current_day:
                daily_tomtom_count = 0
                save_tomtom_quota_state(daily_tomtom_count)
                current_day = now.day

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

            # -------------------------------------------------------------
            # 1. CRAWL 220 BUSES VỚI CƠ CHẾ PACING TRẢI ĐỀU (MICRO-BATCHING)
            # -------------------------------------------------------------
            bus_records = []
            active_count = 0
            depot_count = 0
            stale_count = 0

            # Chia 220 xe thành các micro-batch 4 xe
            batch_size = 4
            micro_batches = [v_ids[i:i + batch_size] for i in range(0, len(v_ids), batch_size)]
            
            # Pacing delay giữa các micro-batch (55 batches x ~0.95s ≈ 52 giây)
            micro_delay = 0.05 if single_test else 0.95

            for b_idx, batch in enumerate(micro_batches):
                with ThreadPoolExecutor(max_workers=batch_size) as executor:
                    futures = {executor.submit(fetch_single_bus_raw, vid): vid for vid in batch}
                    for fut in futures:
                        vid = futures[fut]
                        raw_res = fut.result()
                        if raw_res:
                            clean_rec = sanitize_and_validate_telemetry(
                                raw_res, vid, target_route_ids, last_updates_cache, now.isoformat()
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

            # -------------------------------------------------------------
            # 2. CRAWL TOMTOM BOTTLENECKS (Theo lịch biểu đỉnh / ngoài đỉnh)
            # -------------------------------------------------------------
            hour_val = now.hour + now.minute / 60.0
            is_peak = (6.5 <= hour_val <= 9.0) or (16.5 <= hour_val <= 19.5)
            tomtom_interval = 360 if is_peak else 720  # 6 phút hoặc 12 phút
            next_tomtom_in = max(0, tomtom_interval - (time.time() - last_tomtom_poll))

            tomtom_sampled = 0
            if tomtom_key and (time.time() - last_tomtom_poll >= tomtom_interval or (single_test and round_no == 1)):
                if daily_tomtom_count + len(HUST_BOTTLENECK_NODES) <= MAX_TOMTOM_DAILY:
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
                        time.sleep(0.08)  # 80ms throttle

                    if traffic_records:
                        with open(traffic_out_file, "a", encoding="utf-8") as f:
                            for tr in traffic_records:
                                f.write(json.dumps(tr, ensure_ascii=False) + "\n")

                    last_tomtom_poll = time.time()
                    save_tomtom_quota_state(daily_tomtom_count)
                    next_tomtom_in = tomtom_interval

            # -------------------------------------------------------------
            # 3. TRÌNH DIỄN DASHBOARD CLI TRỰC QUAN
            # -------------------------------------------------------------
            elapsed = time.time() - round_start
            tt_dashboard = render_tomtom_cli_bar(daily_tomtom_count, MAX_TOMTOM_DAILY, next_tomtom_in)
            
            print(f"[{now.strftime('%H:%M:%S')}] [Vòng {round_no:03d}] "
                  f"🚌 Xe buýt: {len(bus_records)}/{len(v_ids)} phản hồi "
                  f"({active_count} lăn bánh, {depot_count} đỗ bãi, {stale_count} lặp) | "
                  f"{elapsed:.1f}s", flush=True)
            print(f"   {tt_dashboard}", flush=True)
            round_no += 1

            # -------------------------------------------------------------
            # 4. ĐỒNG BỘ ĐỊNH KỲ LÊN HUGGING FACE DATASET
            # -------------------------------------------------------------
            if hf_token and (time.time() - last_hf_sync >= HF_SYNC_INTERVAL or single_test):
                sync_to_hf(bus_out_file, traffic_out_file, date_str, hf_token)
                last_hf_sync = time.time()

            if single_test:
                print("\n[INFO] Test run 1 vòng 220 xe hoàn tất thành công! Dừng tiến trình.", flush=True)
                break

            sleep_wait = max(3, BUS_POLL_INTERVAL - elapsed)
            time.sleep(sleep_wait)

        except KeyboardInterrupt:
            print("\n[INFO] Người dùng bấm Ctrl+C. Đang dừng Crawler an toàn...", flush=True)
            save_tomtom_quota_state(daily_tomtom_count)
            break
        except Exception as err:
            print(f"⚠️ [CẢNH BÁO] Có lỗi tạm thời trong vòng lặp ({err}). Tự động tiếp tục sau 5s...", flush=True)
            time.sleep(5)

if __name__ == "__main__":
    main()
