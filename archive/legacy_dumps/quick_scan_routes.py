import ssl
import socket
import json
import time
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

EPOCH = "1791382691939"
PROOF = "a35f2c368f895176575b575b6bf43739"
OUTPUT_FILE = "discovered_vehicles.json"

context = ssl.create_default_context()

def fetch_route(route_id, direction):
    raw_req = (
        f"GET /v2/public/busmap/route_bus_gps?regionCode=hn&routeId={route_id}&direction={direction} HTTP/1.1\r\n"
        "language: vi\r\n"
        f"epoch: {EPOCH}\r\n"
        "client-version: android|20600\r\n"
        f"proof: {PROOF}\r\n"
        "device-id: 7ab54c3ba04cceac\r\n"
        "package-name: com.t7.busmaphn\r\n"
        "Host: api.busmap.city\r\n"
        "Connection: close\r\n"
        "Accept-Encoding: identity\r\n"
        "User-Agent: okhttp/4.12.0\r\n\r\n"
    )
    
    try:
        with socket.create_connection(("api.busmap.city", 443), timeout=4) as s:
            with context.wrap_socket(s, server_hostname="api.busmap.city") as ss:
                ss.sendall(raw_req.encode("utf-8"))
                resp = b""
                while True:
                    d = ss.recv(4096)
                    if not d:
                        break
                    resp += d
                
                header, _, body = resp.partition(b"\r\n\r\n")
                if not body:
                    return []
                
                data = json.loads(body.decode("utf-8", errors="ignore"))
                if isinstance(data, list):
                    return data
    except Exception as e:
        pass
    return []

def main():
    print(f"[*] Bat dau quet nhanh danh sach xe theo tuyen (Proof: {PROOF[:8]}...)...")
    
    # Danh sach cac tuyen thuong gap o Ha Noi (1 den 165 va cac tuyen nhanh)
    route_ids = list(range(1, 166)) + [708, 903, 101101, 101102, 101103]
    tasks = []
    
    for r in route_ids:
        for d in [0, 1]:
            tasks.append((r, d))
            
    print(f"[*] Tong so truy van can thuc hien: {len(tasks)} (Tu tuyen 1 -> 165, ca 2 chieu)")
    
    vehicles = {}
    total_found = 0
    start_time = time.time()
    
    # Su dung ThreadPoolExecutor voi 4 workers de vua nhanh vua khong gay qua tai
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(fetch_route, r, d): (r, d) for r, d in tasks}
        
        for future in as_completed(futures):
            r, d = futures[future]
            res = future.result()
            if res:
                for v in res:
                    veh_id = v.get("Id")
                    if veh_id and veh_id not in vehicles:
                        vehicles[veh_id] = v
                        total_found += 1
                        print(f"   [+] Phat hien xe moi: ID={veh_id} | Bien so={v.get('VehicleNumber')} | Tuyen={v.get('RouteId')}")
            # Nghi nhe 30ms giua cac ket qua de giu politeness
            time.sleep(0.03)

    elapsed = time.time() - start_time
    print(f"\n[DONE] Hoan tat quet trong {elapsed:.2f}s!")
    print(f"[*] Tong so xe doc nhat thu thap duoc: {len(vehicles)}")
    
    # Luu vao file JSON
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(list(vehicles.values()), f, ensure_ascii=False, indent=2)
        
    print(f"[*] Da luu toan bo du lieu xe vao file: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()

