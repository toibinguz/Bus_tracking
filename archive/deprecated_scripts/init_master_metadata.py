import ssl
import socket
import json
import time
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

DATA_DIR = "data/metadata"
ROUTES_FILE = os.path.join(DATA_DIR, "routes.json")
VEHICLES_FILE = os.path.join(DATA_DIR, "vehicles_catalog.json")

context = ssl.create_default_context()

def fetch_json(path):
    raw_req = (
        f"GET {path} HTTP/1.1\r\n"
        "Host: api.busmap.city\r\n"
        "language: vi\r\n"
        "client-version: android|20600\r\n"
        "device-id: 7ab54c3ba04cceac\r\n"
        "package-name: com.t7.busmaphn\r\n"
        "Accept-Encoding: identity\r\n"
        "Connection: close\r\n\r\n"
    )
    try:
        with socket.create_connection(("api.busmap.city", 443), timeout=5) as s:
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
                    return None
                return json.loads(body.decode("utf-8", errors="ignore"))
    except Exception as e:
        return None

def init_routes():
    print("[1/2] Dang khoi tao danh muc tuyen xe buyt...")
    # Neu da co san file list_route_raw.txt thi load truc tiep de tiet kiem request
    if os.path.exists("list_route_raw.txt"):
        with open("list_route_raw.txt", "r", encoding="utf-8") as f:
            c = f.read()
        routes = json.loads(c[c.find("["):])
    else:
        routes = fetch_json("/v2/route/public/list?regionCode=hn")
    
    if routes:
        with open(ROUTES_FILE, "w", encoding="utf-8") as f:
            json.dump(routes, f, ensure_ascii=False, indent=2)
        print(f"  -> Da luu {len(routes)} tuyen xe buyt vao {ROUTES_FILE}")
    return routes

def init_vehicles():
    print("[2/2] Dang quet danh ba xe toan thanh pho (Tien to 1 -> 9)...")
    vehicles = {}
    
    # 1. Nap xe da phat hien tu truoc neu co
    if os.path.exists("discovered_vehicles.json"):
        with open("discovered_vehicles.json", "r", encoding="utf-8") as f:
            old_data = json.load(f)
            for v in old_data:
                vehicles[v.get("Id")] = {
                    "id": v.get("Id"),
                    "title": v.get("VehicleNumber"),
                    "routeId": v.get("RouteId")
                }
        print(f"  -> Da ke thua {len(vehicles)} xe tu discovered_vehicles.json")

    # 2. Quet cac tien to tu 1 den 9 qua API search_vehicle_v2
    for prefix in range(1, 10):
        page = 0
        while True:
            path = f"/v2/public/busmap/search_vehicle_v2?regionCode=hn&limit=100&vehicleId={prefix}&page={page}"
            res = fetch_json(path)
            if not res or not isinstance(res, list) or len(res) == 0:
                break
            
            new_in_page = 0
            for item in res:
                v_id = item.get("id")
                if v_id and v_id not in vehicles:
                    vehicles[v_id] = item
                    new_in_page += 1
            
            print(f"  Prefix {prefix} | Page {page}: Tim thay {len(res)} xe ({new_in_page} xe moi)")
            page += 1
            time.sleep(0.1) # Politeness delay
            if len(res) < 100:
                break
                
    with open(VEHICLES_FILE, "w", encoding="utf-8") as f:
        json.dump(list(vehicles.values()), f, ensure_ascii=False, indent=2)
        
    print(f"\n[HOAN TAT] Tong so xe doc nhat toan thanh pho: {len(vehicles)}")
    print(f"  -> Da luu vao {VEHICLES_FILE}")

if __name__ == "__main__":
    os.makedirs(DATA_DIR, exist_ok=True)
    init_routes()
    init_vehicles()

