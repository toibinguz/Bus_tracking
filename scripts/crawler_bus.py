import os
import sys
import json
import time
import socket
import ssl
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

sys.stdout.reconfigure(encoding='utf-8')

CATALOG_FILE = "data/metadata/vehicles_catalog.json"
OUTPUT_DIR = "data/raw/bus"
TARGET_ROUTES = [1, 2, 8, 27, 28, 32, 54, 708, 101102] # Chon cac tuyen trong diem de thu thap lien tuc
LOOP_INTERVAL = 75 # Chu ky quet 75 giay (khop chu ky may chu BusMap)

context = ssl.create_default_context()

def fetch_vehicle(v_id):
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
            with context.wrap_socket(s, server_hostname="api.busmap.city") as ss:
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

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    if not os.path.exists(CATALOG_FILE):
        print(f"Loi: Chua tim thay {CATALOG_FILE}. Hay chay init_master_metadata.py truoc!")
        return

    with open(CATALOG_FILE, "r", encoding="utf-8") as f:
        all_vehicles = json.load(f)

    # Loc danh sach xe thuoc cac tuyen muc tieu
    target_vehicles = [v for v in all_vehicles if v.get("routeId") in TARGET_ROUTES]
    if not target_vehicles:
        target_vehicles = all_vehicles[:100] # Fallback neu khong loc duoc

    print(f"[*] Bat dau Crawler GPS Xe Buyt 24/7...")
    print(f"[*] Theo doi {len(target_vehicles)} xe thuoc cac tuyen: {TARGET_ROUTES}")
    print(f"[*] Chu ky quet: {LOOP_INTERVAL}s/lan (Ghi vao {OUTPUT_DIR})")

    round_idx = 1
    while True:
        start_time = time.time()
        now_str = datetime.now().strftime("%Y-%m-%d_%H")
        out_file = os.path.join(OUTPUT_DIR, f"telemetry_{now_str}.jsonl")
        
        records = []
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(fetch_vehicle, v["id"]): v for v in target_vehicles}
            for fut in futures:
                res = fut.result()
                if res:
                    records.append(res)
                time.sleep(0.04) # Nghi nhe 40ms giua cac request

        # Ghi append vao file JSONL
        if records:
            with open(out_file, "a", encoding="utf-8") as f:
                for r in records:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
                    
        elapsed = time.time() - start_time
        print(f"[Vong {round_idx}] Thu duoc {len(records)}/{len(target_vehicles)} ping GPS trong {elapsed:.1f}s | Ghi vao {os.path.basename(out_file)}")
        round_idx += 1
        
        sleep_time = max(5, LOOP_INTERVAL - elapsed)
        time.sleep(sleep_time)

if __name__ == "__main__":
    main()

