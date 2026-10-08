"""
Daily Vehicle Catalog Health Check & Auto-Discovery Routine
Runs daily at 05:00 AM Hanoi Time (22:00 UTC) on GitHub Actions & Termux
Features:
- Audits all 220 configured vehicles (active, depot, reassigned, offline)
- Auto-discovers replacement vehicles for routes with missing capacity
- Synchronizes and updates data/metadata/hust_cluster_config.json
- Emits structured health report for monitoring
"""

import os
import sys
import json
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Add parent directory to sys.path so core package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import (
    CONFIG_FILE,
    BUS_MICRO_BATCH_SIZE,
    BUS_MICRO_BATCH_DELAY_SEC,
    get_hanoi_time
)
from core.bus_client import fetch_single_bus_raw, search_vehicles_by_query, load_cluster_config, save_cluster_config

VEHICLES_CATALOG_FILE = "data/metadata/vehicles_catalog.json"

def audit_vehicle(vid):
    """Kiểm tra trạng thái sống và tuyến hiện tại của một xe buýt."""
    raw = fetch_single_bus_raw(vid)
    if not raw:
        return {"id": vid, "status": "OFFLINE", "route_id": None, "plate": ""}
    
    route_id = int(raw.get("RouteId", 0))
    plate = raw.get("VehicleNumber", "")
    speed = float(raw.get("Speed", 0.0))
    direction = int(raw.get("direction", 0))
    
    if direction == -1 and speed == 0:
        status = "DEPOT"
    else:
        status = "ACTIVE"
        
    return {
        "id": vid,
        "status": status,
        "route_id": route_id,
        "plate": plate,
        "raw": raw
    }

def run_daily_catalog_refresh():
    hn_time = get_hanoi_time()
    ts_str = hn_time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts_str}] 🌅 BẮT ĐẦU RÀ SOÁT VÀ CẬP NHẬT DANH BẠ XE ĐẦU NGÀY (05:00 AM)...", flush=True)

    if not os.path.exists(CONFIG_FILE):
        print(f"[ERROR] Không tìm thấy {CONFIG_FILE}!", flush=True)
        return

    config = load_cluster_config(CONFIG_FILE)
    target_route_ids = set(config.get("target_route_ids", []))
    configured_vehicles = config.get("vehicles", [])
    configured_vids = [v["id"] for v in configured_vehicles if "id" in v]
    
    print(f"[*] Tổng số xe cấu hình hiện tại: {len(configured_vids)} xe trên {len(target_route_ids)} tuyến hành lang.", flush=True)

    # 1. Khảo sát 220 xe hiện có (Pacing micro-batches để bảo vệ WAF)
    print("[*] [Pha 1/3] Đang ping kiểm tra trạng thái 220 xe...", flush=True)
    audit_results = {}
    micro_batches = [configured_vids[i:i + BUS_MICRO_BATCH_SIZE] for i in range(0, len(configured_vids), BUS_MICRO_BATCH_SIZE)]

    for batch in micro_batches:
        with ThreadPoolExecutor(max_workers=BUS_MICRO_BATCH_SIZE) as executor:
            futures = {executor.submit(audit_vehicle, vid): vid for vid in batch}
            for fut in futures:
                res = fut.result()
                audit_results[res["id"]] = res
        time.sleep(BUS_MICRO_BATCH_DELAY_SEC)

    active_count = sum(1 for r in audit_results.values() if r["status"] == "ACTIVE")
    depot_count = sum(1 for r in audit_results.values() if r["status"] == "DEPOT")
    offline_count = sum(1 for r in audit_results.values() if r["status"] == "OFFLINE")
    reassigned = [r for r in audit_results.values() if r["route_id"] and r["route_id"] not in target_route_ids]

    print(f"   -> Kết quả: {active_count} lăn bánh, {depot_count} đỗ bãi, {offline_count} chưa online.", flush=True)
    if reassigned:
        print(f"   ⚠️ Phát hiện {len(reassigned)} xe đã bị nhà xe điều chuyển sang tuyến khác!", flush=True)
        for r in reassigned[:5]:
            print(f"      - Xe {r['id']} ({r['plate']}) hiện thuộc Tuyến {r['route_id']}", flush=True)

    # 2. Thống kê theo từng tuyến & Tìm kiếm bù xe mới nếu thiếu
    print("[*] [Pha 2/3] Đối soát từng tuyến và quét xe mới thay thế...", flush=True)
    route_vehicle_map = {r_id: [] for r_id in target_route_ids}
    for vid, r in audit_results.items():
        if r["route_id"] in route_vehicle_map:
            route_vehicle_map[r["route_id"]].append(vid)

    # Tải danh bạ toàn thành phố (nếu có) để tìm xe dự phòng
    city_vehicles = []
    if os.path.exists(VEHICLES_CATALOG_FILE):
        try:
            with open(VEHICLES_CATALOG_FILE, "r", encoding="utf-8") as f:
                city_vehicles = json.load(f)
        except Exception:
            pass

    new_discovered_vehicles = []
    existing_vid_set = set(configured_vids)

    # Kiểm tra xem trong city_vehicles có xe nào đang thuộc 19 tuyến mà chưa có trong danh sách 220 xe không
    for cv in city_vehicles:
        cv_id = cv.get("id") or cv.get("Id")
        cv_route = cv.get("routeId") or cv.get("RouteId")
        if cv_id and cv_route in target_route_ids and cv_id not in existing_vid_set:
            # Ping thử xem xe có thực sự hoạt động trên tuyến không
            test_res = audit_vehicle(cv_id)
            if test_res["route_id"] in target_route_ids:
                new_discovered_vehicles.append({
                    "id": cv_id,
                    "plate": test_res["plate"],
                    "route_id": test_res["route_id"],
                    "route_no": next((r.get("route_no", "") for r in config.get("routes", []) if r.get("route_id") == test_res["route_id"]), "")
                })
                existing_vid_set.add(cv_id)

    print(f"   -> Tìm thấy {len(new_discovered_vehicles)} xe hoạt động hợp lệ bổ sung trên 19 tuyến.", flush=True)

    # 3. Cập nhật file cấu hình nếu có bổ sung
    if new_discovered_vehicles:
        print(f"[*] [Pha 3/3] Đang cập nhật {CONFIG_FILE}...", flush=True)
        for nv in new_discovered_vehicles:
            config["vehicles"].append({
                "id": nv["id"],
                "plate": nv["plate"],
                "route_id": nv["route_id"],
                "route_no": nv["route_no"]
            })
        config["total_vehicles"] = len(config["vehicles"])
        config["last_catalog_refresh"] = ts_str
        save_cluster_config(config, CONFIG_FILE)
        print(f"[OK] Đã cập nhật tổng số xe lên {config['total_vehicles']} xe!", flush=True)
    else:
        print("[OK] Danh mục 220 xe ổn định, không có biến động cần cập nhật.", flush=True)

    # Lưu log báo cáo sức khỏe danh mục
    health_report = {
        "timestamp": ts_str,
        "total_configured": len(configured_vids),
        "active_responding": active_count + depot_count,
        "active_rolling": active_count,
        "depot_idle": depot_count,
        "offline": offline_count,
        "reassigned_count": len(reassigned),
        "newly_added_count": len(new_discovered_vehicles)
    }
    
    os.makedirs("data/metadata", exist_ok=True)
    with open("data/metadata/daily_catalog_health.json", "w", encoding="utf-8") as f:
        json.dump(health_report, f, ensure_ascii=False, indent=2)

    print(f"[{hn_time.strftime('%H:%M:%S')}] 🎉 HOÀN TẤT RÀ SOÁT DANH BẠ ĐẦU NGÀY!\n", flush=True)

if __name__ == "__main__":
    run_daily_catalog_refresh()
