"""
Runner 5.6: Daily Vehicle Catalog Health Check & Auto-Discovery Routine
Runs daily at 05:00 AM Hanoi Time (22:00 UTC) on GitHub Actions & Termux
Features:
- Audits all configured vehicles (active, depot, reassigned, offline)
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

# Add parent directory to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import (
    CONFIG_FILE,
    BUS_MICRO_BATCH_SIZE,
    BUS_MICRO_BATCH_DELAY_SEC,
    get_hanoi_time
)
from module_1_data_ingestion_and_preprocessing import (
    fetch_single_bus_raw, search_vehicles_by_query, load_cluster_config, save_cluster_config
)

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
    print("=" * 70, flush=True)
    print(f"[{ts_str}] BẮT ĐẦU RÀ SOÁT & TỰ ĐỘNG KHÁM PHÁ DANH MỤC XE BUÝT HÀ NỘI", flush=True)
    print("=" * 70, flush=True)

    if not os.path.exists(CONFIG_FILE):
        print(f"[ERROR] Không tìm thấy file {CONFIG_FILE}!", flush=True)
        return

    config = load_cluster_config(CONFIG_FILE)
    configured_vids = [v["id"] for v in config["vehicles"]]
    configured_routes = {r["route_no"]: r["route_id"] for r in config["routes"]}

    print(f"[*] [Pha 1/3] Đang kiểm tra trạng thái {len(configured_vids)} xe buýt trong danh bạ...", flush=True)

    audit_results = {}
    with ThreadPoolExecutor(max_workers=BUS_MICRO_BATCH_SIZE) as executor:
        futures = {executor.submit(audit_vehicle, vid): vid for vid in configured_vids}
        for future in futures:
            vid = futures[future]
            try:
                res = future.result()
                audit_results[vid] = res
            except Exception as e:
                audit_results[vid] = {"id": vid, "status": "ERROR", "error": str(e)}

    active_count = sum(1 for r in audit_results.values() if r.get("status") == "ACTIVE")
    depot_count = sum(1 for r in audit_results.values() if r.get("status") == "DEPOT")
    offline_count = sum(1 for r in audit_results.values() if r.get("status") == "OFFLINE")

    print(f"[+] Kết quả rà soát: {active_count} xe đang chạy, {depot_count} xe nằm bãi, {offline_count} xe không phản hồi (offline).", flush=True)

    # Kiểm tra các xe đổi tuyến (reassigned)
    reassigned = []
    for v in config["vehicles"]:
        vid = v["id"]
        res = audit_results.get(vid, {})
        actual_route = res.get("route_id")
        if actual_route and actual_route != v["route_id"]:
            reassigned.append((v, actual_route))

    if reassigned:
        print(f"[!] Phát hiện {len(reassigned)} xe đã bị điều chuyển tuyến khác:", flush=True)
        for old_v, new_r in reassigned:
            print(f"    - Xe {old_v['plate']} (ID {old_v['id']}): Tuyến {old_v['route_no']} -> Route ID mới {new_r}", flush=True)

    # Pha 2: Tự động khám phá xe mới cho các tuyến thiếu hụt
    print(f"\n[*] [Pha 2/3] Quét mạng lưới tự động bổ sung xe cho các tuyến...", flush=True)
    all_discovered = {}
    if os.path.exists(VEHICLES_CATALOG_FILE):
        try:
            with open(VEHICLES_CATALOG_FILE, "r", encoding="utf-8") as f:
                all_discovered = json.load(f)
        except Exception:
            all_discovered = {}

    new_discovered_vehicles = []
    configured_vid_set = set(configured_vids)

    for route_no, route_id in configured_routes.items():
        # Đếm số xe active hiện tại của tuyến
        active_on_route = sum(1 for r in audit_results.values() if r.get("route_id") == route_id and r.get("status") in ("ACTIVE", "DEPOT"))
        if active_on_route < 6: # Tuyến có ít hơn 6 xe phản hồi -> Cần quét bổ sung
            print(f"    - Tuyến {route_no} chỉ có {active_on_route} xe hoạt động, đang quét tìm xe bổ sung...", flush=True)
            found_raw = search_vehicles_by_query(route_no)
            for raw in found_raw:
                try:
                    f_vid = int(raw.get("VehicleId") or raw.get("Id") or 0)
                    f_route = int(raw.get("RouteId") or 0)
                    f_plate = str(raw.get("VehicleNumber") or "")
                    if f_vid > 0 and f_route == route_id and f_vid not in configured_vid_set:
                        new_discovered_vehicles.append({
                            "id": f_vid,
                            "plate": f_plate,
                            "route_id": f_route,
                            "route_no": route_no
                        })
                        configured_vid_set.add(f_vid)
                        print(f"      + Tìm thấy xe mới: {f_plate} (ID: {f_vid})", flush=True)
                except Exception:
                    pass
            time.sleep(0.5)

    # Pha 3: Cập nhật cấu hình cluster nếu có xe mới
    if new_discovered_vehicles:
        print(f"\n[*] [Pha 3/3] Đang cập nhật {CONFIG_FILE}...", flush=True)
        for nv in new_discovered_vehicles:
            config["vehicles"].append({
                "id": nv["id"],
                "plate": nv["plate"],
                "route_id": nv["route_id"],
                "route_no": nv["route_no"]
            })
        config["total_vehicles"] = len(config["vehicles"])
        print(f"[OK] Đã cập nhật tổng số xe lên {config['total_vehicles']} xe!", flush=True)
    else:
        print(f"[OK] Danh mục {len(configured_vids)} xe ổn định, không có biến động cần cập nhật.", flush=True)

    config["last_catalog_refresh"] = ts_str
    save_cluster_config(config, CONFIG_FILE)

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

def main():
    run_daily_catalog_refresh()

if __name__ == "__main__":
    main()
