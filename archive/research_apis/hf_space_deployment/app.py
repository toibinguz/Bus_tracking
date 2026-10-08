import os
import sys
import json
import time
import socket
import ssl
import urllib.request
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import gradio as gr
from huggingface_hub import HfApi

CONFIG_FILE = "hust_cluster_config.json"
DATA_DIR = "crawled_data"
BUS_DIR = os.path.join(DATA_DIR, "bus")
TRAFFIC_DIR = os.path.join(DATA_DIR, "traffic")

os.makedirs(BUS_DIR, exist_ok=True)
os.makedirs(TRAFFIC_DIR, exist_ok=True)

# Environment variables from Hugging Face Space Settings
HF_TOKEN = os.environ.get("HF_TOKEN")
HF_DATASET_ID = os.environ.get("HF_DATASET_ID")
TOMTOM_KEY = os.environ.get("TOMTOM_KEY", "")

# Load configuration
if os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)
    TARGET_VEHICLES = [v["id"] for v in config.get("vehicles", []) if "id" in v]
else:
    TARGET_VEHICLES = []

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

# Shared state for Gradio dashboard
dashboard_state = {
    "status": "Khoi dong...",
    "rounds": 0,
    "last_active_buses": 0,
    "total_pings": 0,
    "tomtom_count": 0,
    "last_sync": "Chua dong bo",
    "logs": []
}

def log_msg(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    formatted = f"[{ts}] {msg}"
    print(formatted)
    dashboard_state["logs"].append(formatted)
    if len(dashboard_state["logs"]) > 50:
        dashboard_state["logs"].pop(0)

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
    req = urllib.request.Request(url, headers={"User-Agent": "HFBusCrawler/1.0"})
    try:
        with urllib.request.urlopen(req, context=ssl_context, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("flowSegmentData")
    except Exception:
        return None

def sync_to_dataset(file_path, repo_path):
    if not HF_TOKEN or not HF_DATASET_ID:
        return False
    try:
        api = HfApi(token=HF_TOKEN)
        api.upload_file(
            path_or_fileobj=file_path,
            path_in_repo=repo_path,
            repo_id=HF_DATASET_ID,
            repo_type="dataset",
            commit_message=f"Auto-sync telemetry: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )
        return True
    except Exception as e:
        log_msg(f"Loi sync HF Dataset: {e}")
        return False

def background_crawler_loop():
    log_msg(f"Crawler khoi dong! Theo doi {len(TARGET_VEHICLES)} xe buyt Bach Khoa...")
    last_sync_time = time.time()
    last_tomtom_time = 0

    while True:
        now = datetime.now()
        # Check operating hours (05:00 - 22:00)
        hour_val = now.hour + now.minute / 60.0
        if hour_val < 5.0 or hour_val > 22.0:
            dashboard_state["status"] = "🌙 Ngu dem (22:00 - 05:00)"
            time.sleep(300)
            continue

        dashboard_state["status"] = "🟢 Dang chay (Active Crawling)"
        start_t = time.time()
        date_str = now.strftime("%Y-%m-%d")
        hour_str = now.strftime("%H")

        bus_out = os.path.join(BUS_DIR, f"bus_{date_str}_{hour_str}.jsonl")
        bus_records = []
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = {executor.submit(fetch_single_bus, vid): vid for vid in TARGET_VEHICLES}
            for fut in futures:
                res = fut.result()
                if res:
                    res["crawled_at"] = now.isoformat()
                    bus_records.append(res)
                time.sleep(0.03)

        if bus_records:
            with open(bus_out, "a", encoding="utf-8") as f:
                for r in bus_records:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            dashboard_state["total_pings"] += len(bus_records)
            dashboard_state["last_active_buses"] = len(bus_records)

        # TomTom polling
        is_peak = (6.5 <= hour_val <= 9.0) or (16.5 <= hour_val <= 19.5)
        tt_interval = 360 if is_peak else 720
        if TOMTOM_KEY and (time.time() - last_tomtom_time >= tt_interval):
            traffic_out = os.path.join(TRAFFIC_DIR, f"tomtom_{date_str}.jsonl")
            tt_records = []
            for node in HUST_BOTTLENECK_NODES:
                res = fetch_tomtom_flow(node["lat"], node["lon"], TOMTOM_KEY)
                if res:
                    dashboard_state["tomtom_count"] += 1
                    tt_records.append({
                        "timestamp": now.isoformat(),
                        "node_name": node["name"],
                        "current_speed": res.get("currentSpeed"),
                        "free_flow_speed": res.get("freeFlowSpeed"),
                        "travel_time": res.get("currentTravelTime")
                    })
                time.sleep(0.1)
            if tt_records:
                with open(traffic_out, "a", encoding="utf-8") as f:
                    for r in tt_records:
                        f.write(json.dumps(r, ensure_ascii=False) + "\n")
            last_tomtom_time = time.time()

        dashboard_state["rounds"] += 1
        elapsed = time.time() - start_t
        log_msg(f"[Vong {dashboard_state['rounds']:04d}] Thu thap {len(bus_records)}/{len(TARGET_VEHICLES)} xe buyt ({elapsed:.1f}s)")

        # Sync to HF Dataset every 30 minutes
        if time.time() - last_sync_time >= 1800:
            if HF_DATASET_ID and HF_TOKEN:
                log_msg("Dang dong bo du lieu sang HF Dataset...")
                if os.path.exists(bus_out):
                    ok = sync_to_dataset(bus_out, f"bus/{os.path.basename(bus_out)}")
                    if ok:
                        dashboard_state["last_sync"] = now.strftime("%H:%M:%S")
                        log_msg("Dong bo thanh cong!")
            last_sync_time = time.time()

        wait_sec = max(5, 60 - elapsed)
        time.sleep(wait_sec)

# Start background thread
crawler_thread = threading.Thread(target=background_crawler_loop, daemon=True)
crawler_thread.start()

def get_status_markdown():
    return f"""
    ### 📊 BẢNG ĐIỀU KHIỂN CRAWLER CỤM BÁCH KHOA
    * **Trạng thái:** `{dashboard_state['status']}`
    * **Số vòng đã chạy:** `{dashboard_state['rounds']}`
    * **Xe buýt hoạt động vòng gần nhất:** `{dashboard_state['last_active_buses']} / {len(TARGET_VEHICLES)} xe`
    * **Tổng số ping GPS thu được:** `{dashboard_state['total_pings']:,} pings`
    * **Số request TomTom đã gọi:** `{dashboard_state['tomtom_count']} requests`
    * **Lần đồng bộ Dataset gần nhất:** `{dashboard_state['last_sync']}`
    """

def get_logs_text():
    return "\n".join(dashboard_state["logs"][-20:])

with gr.Blocks(title="HUST Bus Telemetry Crawler") as demo:
    gr.Markdown("# 🚌 Hệ Thống Giám Sát & Thu Thập Dữ Liệu Xe Buýt Bách Khoa (24/7)")
    with gr.Row():
        status_box = gr.Markdown(value=get_status_markdown)
    with gr.Row():
        log_view = gr.Textbox(label="Logs Thời Gian Thực (Tự động cập nhật mỗi 10s)", value=get_logs_text, lines=12)
    
    timer = gr.Timer(10)
    timer.tick(fn=get_status_markdown, outputs=status_box)
    timer.tick(fn=get_logs_text, outputs=log_view)

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)

