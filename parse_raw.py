import json
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

def analyze_timeline():
    with open("timeline_raw.txt", "r", encoding="utf-8") as f:
        content = f.read()
    json_str = content[content.find("{"):]
    data = json.loads(json_str)
    
    forward = data.get("forWardStationList", [])
    backward = data.get("backWardStationList", [])
    
    print("=== 1. TIMELINE RAW ===")
    print(f"Forward stations: {len(forward)}, Backward stations: {len(backward)}")
    if forward:
        first = forward[0]
        schedule = [int(x) for x in first.get("timeTableOut", "").split(",") if x]
        print(f"Station dau: {first.get('stationName')} (ID: {first.get('stationId')})")
        print(f"Tong so luot xuat ben trong ngay: {len(schedule)}")
        if schedule:
            t_start = f"{schedule[0]//3600:02d}:{(schedule[0]%3600)//60:02d}"
            t_end = f"{schedule[-1]//3600:02d}:{(schedule[-1]%3600)//60:02d}"
            print(f"Gio xuat ben dau: {t_start}, Gio xuat ben cuoi: {t_end}")
            headways = [schedule[i+1] - schedule[i] for i in range(len(schedule)-1)]
            avg_hw = sum(headways) / len(headways) / 60
            print(f"Gian cach trung binh (Headway): {avg_hw:.1f} phut (Min: {min(headways)/60:.1f}p, Max: {max(headways)/60:.1f}p)")

def analyze_routes():
    with open("list_route_raw.txt", "r", encoding="utf-8") as f:
        content = f.read()
    json_str = content[content.find("["):]
    routes = json.loads(json_str)
    
    print("\n=== 2. LIST ROUTE RAW ===")
    print(f"Tong so tuyen trong he thong: {len(routes)}")
    
    numeric_routes = []
    special_routes = []
    for r in routes:
        no = str(r.get("routeNo"))
        if no.isdigit():
            numeric_routes.append(r)
        else:
            special_routes.append(r)
            
    print(f"Tuyen so thuan: {len(numeric_routes)}")
    print(f"Tuyen dac biet (A/B, E, BRT, CNG...): {len(special_routes)}")
    print("Mau cac tuyen dac biet va RouteId tuong ung:")
    for r in special_routes[:12]:
        print(f"  - Tuyen {r.get('routeNo')}: RouteId = {r.get('routeId')} | Loai: {r.get('routeType')} | {r.get('routeName')}")

def analyze_vehicles():
    with open("list_vehicle_raw.txt", "r", encoding="utf-8") as f:
        content = f.read()
    json_str = content[content.find("["):]
    vehicles = json.loads(json_str)
    
    print("\n=== 3. LIST VEHICLE RAW (SEARCH VEHICLE API) ===")
    print(f"So xe tra ve trong 1 page tim kiem: {len(vehicles)}")
    print("Mau xe tra ve:")
    for v in vehicles[:5]:
        print(f"  - Xe ID: {v.get('id')} | Bien so: {v.get('title')} | BusId: {v.get('busId')} | RouteId: {v.get('routeId')} | {v.get('description')}")

def analyze_map():
    with open("map_raw.txt", "r", encoding="utf-8") as f:
        content = f.read()
    json_str = content[content.find("{"):]
    cfg = json.loads(json_str)
    
    print("\n=== 4. MAP RAW (SYSTEM CONFIG & HIDDEN APIS) ===")
    print("Cac API he thong quan trong tim thay:")
    for k, v in cfg.items():
        if k.startswith("api_") or "url" in k or "region" in k or "speed" in k:
            print(f"  {k}: {v}")

if __name__ == "__main__":
    analyze_timeline()
    analyze_routes()
    analyze_vehicles()
    analyze_map()
