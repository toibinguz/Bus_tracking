#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Experiment: audit_api_parity_vehicle_vs_route.py
Kiểm chứng thực nghiệm tính thống nhất (Parity & Consistency) giữa 2 API BusMap:
1. vehicle_hn/get?id=VID (Raw GPS ping theo từng xe)
2. route_bus_gps?routeId=R&direction=D (Snapshot theo tuyến có xác thực MD5)

Mục tiêu kiểm chứng:
- Lat/Lng: Có bị snap tim đường hay làm tròn không?
- Timestamp: Có chênh lệch độ trễ (cache) giữa 2 API không?
- Speed: Có khớp giá trị không?
- Tồn tại xe: Có xe nào chạy trên tuyến nhưng bị route_bus_gps ẩn/lọc không?
"""

import sys
import os
import json
import time
import math
from datetime import datetime

# Đảm bảo UTF-8
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from module_1_data_ingestion_and_preprocessing.step_1_1_busmap_crawler_and_relay.catalog_refresher import (
    fetch_route_buses_live
)
from module_1_data_ingestion_and_preprocessing.step_1_1_busmap_crawler_and_relay.socket_client import (
    fetch_single_bus_raw
)

def haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0)**2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c

def audit_route_parity(route_id: int):
    print(f"\n=======================================================")
    print(f"[*] KIỂM TRA ĐỐI SOÁT TUYẾN ROUTE_ID = {route_id}")
    print(f"=======================================================")
    
    # 1. Lấy dữ liệu qua route_bus_gps (cả 2 chiều)
    route_buses = {}
    for d in [0, 1]:
        buses = fetch_route_buses_live(route_id, direction=d)
        for b in buses:
            vid = b.get("Id")
            b["_direction_queried"] = d
            route_buses[vid] = b
            
    print(f"[+] route_bus_gps: Tìm thấy {len(route_buses)} xe đang phát tín hiệu trên tuyến {route_id}.")
    
    if not route_buses:
        print(f"[-] Tuyến {route_id} hiện không có xe nào đang chạy.")
        return
        
    # 2. Truy vấn song song/tuần tự từng xe qua vehicle_hn/get
    parity_results = []
    for vid, r_bus in route_buses.items():
        v_raw_data = fetch_single_bus_raw(vid)
        
        if not v_raw_data:
            print(f"  [!] Xe VID={vid} ({r_bus.get('VehicleNumber')}): vehicle_hn/get không trả về dữ liệu")
            continue
            
        r_lat = float(r_bus.get("Lat", 0.0))
        r_lng = float(r_bus.get("Lng", 0.0))
        r_spd = float(r_bus.get("Speed", 0.0))
        r_time = r_bus.get("lastUpdateTime", "")
        r_cur_sta = r_bus.get("currentStationId")
        r_nxt_sta = r_bus.get("nextStationId")
        
        # CHÚ Ý ĐẶC BIỆT: Trong vehicle_hn/get, backend BusMap bị đảo ngược:
        # raw["Lat"] thực chất là Kinh độ (105.x), raw["Lng"] thực chất là Vĩ độ (20.x).
        # Trong khi đó, trong route_bus_gps, Lat là Vĩ độ (20.x), Lng là Kinh độ (105.x).
        v_lat = float(v_raw_data.get("Lng", 0.0))
        v_lng = float(v_raw_data.get("Lat", 0.0))
        v_spd = float(v_raw_data.get("Speed", 0.0))
        v_time = v_raw_data.get("lastUpdateTime", "")
        v_dir = v_raw_data.get("direction", 0)
        
        dist_diff_m = haversine_m(r_lat, r_lng, v_lat, v_lng)
        
        parity_results.append({
            "vid": vid,
            "plate": r_bus.get("VehicleNumber"),
            "dist_diff_m": dist_diff_m,
            "r_lat": r_lat, "r_lng": r_lng,
            "v_lat": v_lat, "v_lng": v_lng,
            "r_spd": r_spd, "v_spd": v_spd,
            "r_time": r_time, "v_time": v_time,
            "time_match": (r_time == v_time),
            "r_cur_sta": r_cur_sta,
            "r_nxt_sta": r_nxt_sta,
            "v_dir": v_dir
        })
        time.sleep(0.1)
        
    print(f"\n--- BẢNG ĐỐI CHIẾU CHI TIẾT CÁC XE TUYẾN {route_id} ---")
    print(f"{'VID':<8} | {'Biển số':<11} | {'Lệch kc (m)':<12} | {'r_spd':<6} | {'v_spd':<6} | {'Trùng time?':<12} | {'current_station':<15}")
    print("-" * 80)
    for p in parity_results:
        print(f"{p['vid']:<8} | {p['plate']:<11} | {p['dist_diff_m']:<12.3f} | {p['r_spd']:<6.0f} | {p['v_spd']:<6.0f} | {str(p['time_match']):<12} | {str(p['r_cur_sta']):<15}")
        if not p['time_match'] or p['dist_diff_m'] > 1.0:
            print(f"    -> route_time:   {p['r_time']} | ({p['r_lat']:.6f}, {p['r_lng']:.6f})")
            print(f"    -> vehicle_time: {p['v_time']} | ({p['v_lat']:.6f}, {p['v_lng']:.6f})")

if __name__ == "__main__":
    test_routes = [2, 32, 40]
    for r in test_routes:
        audit_route_parity(r)
