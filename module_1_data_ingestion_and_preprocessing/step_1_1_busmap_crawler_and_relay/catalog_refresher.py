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
import hashlib
import ssl
import urllib.request
import urllib.parse
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
from config.system_config import (
    CATALOG_STALE_HOURS,
    CATALOG_PRUNE_STALE_HOURS,
    CATALOG_MIN_ACTIVE_PER_ROUTE,
)
from module_1_data_ingestion_and_preprocessing import (
    fetch_single_bus_raw, load_cluster_config, save_cluster_config
)

VEHICLES_CATALOG_FILE = "data/metadata/vehicles_catalog.json"
BUSMAP_SALT = ":Bus2019M@p_"
BUSMAP_DEVICE_ID = "3f8b1c4a9d2e5f70"
SSL_UNVERIFIED_CTX = ssl._create_unverified_context()

def _get_live_route_headers():
    """Sinh header kèm chữ ký động epoch & proof MD5 theo chuẩn BusMap Android Client."""
    epoch_ms = str(int(time.time() * 1000))
    raw_token = f"{epoch_ms}{BUSMAP_SALT}"
    proof_hash = hashlib.md5(raw_token.encode('utf-8')).hexdigest()
    return {
        "package-name": "com.t7.busmaphn",
        "client-version": "android|20600",
        "device-id": BUSMAP_DEVICE_ID,
        "language": "vi",
        "User-Agent": "okhttp/4.9.2",
        "epoch": epoch_ms,
        "proof": proof_hash
    }

def fetch_route_buses_live(route_id: int, direction: int = 0):
    """
    Truy vấn trực tiếp toàn bộ xe buýt đang hoạt động trên tuyến bằng API route_bus_gps.
    direction: 0 (Chiều về / B->A) hoặc 1 (Chiều đi / A->B)
    """
    url = f"https://api.busmap.city/v2/public/busmap/route_bus_gps?regionCode=hn&routeId={route_id}&direction={direction}"
    req = urllib.request.Request(url, headers=_get_live_route_headers(), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=8.0, context=SSL_UNVERIFIED_CTX) as resp:
            data = resp.read()
            if not data:
                return []
            return json.loads(data.decode('utf-8'))
    except Exception as e:
        print(f"      [!] Lỗi truy vấn route_bus_gps tuyến {route_id} hướng {direction}: {e}", flush=True)
        return []

def _parse_hours_since_update(raw):
    """Số giờ kể từ lastUpdateTime của xe (None nếu không đọc được)."""
    ts = raw.get("lastUpdateTime")
    if not ts:
        return None
    try:
        dt_upd = datetime.fromisoformat(str(ts))
        if dt_upd.tzinfo is None:
            dt_upd = dt_upd.replace(tzinfo=get_hanoi_time().tzinfo)
        return (get_hanoi_time() - dt_upd).total_seconds() / 3600.0
    except Exception:
        return None

def audit_vehicle(vid):
    """Kiểm tra trạng thái sống và tuyến hiện tại của một xe buýt.
    Trạng thái: OFFLINE | STALE (lastUpdateTime đóng băng > CATALOG_STALE_HOURS)
    | DEPOT (không tuyến / direction<=0 hoặc đứng yên chiều 0) | ACTIVE."""
    raw = fetch_single_bus_raw(vid)
    if not raw:
        return {"id": vid, "status": "OFFLINE", "route_id": None, "plate": ""}
    
    route_id = int(raw.get("RouteId", 0))
    plate = raw.get("VehicleNumber", "")
    speed = float(raw.get("Speed", 0.0))
    direction = int(raw.get("direction", 0))
    age_h = _parse_hours_since_update(raw)
    
    if age_h is not None and age_h > CATALOG_STALE_HOURS:
        status = "STALE"
    elif route_id <= 0 or direction < 0 or (direction == 0 and speed == 0):
        status = "DEPOT"
    else:
        status = "ACTIVE"
        
    return {
        "id": vid,
        "status": status,
        "route_id": route_id,
        "plate": plate,
        "age_h": age_h,
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
    stale_count = sum(1 for r in audit_results.values() if r.get("status") == "STALE")
    offline_count = sum(1 for r in audit_results.values() if r.get("status") == "OFFLINE")

    print(f"[+] Kết quả rà soát: {active_count} xe đang chạy, {depot_count} xe nằm bãi, {stale_count} xe treo (>24h), {offline_count} xe không phản hồi (offline).", flush=True)

    # Kiểm tra các xe đổi tuyến (reassigned)
    reassigned = []
    for v in config["vehicles"]:
        vid = v["id"]
        res = audit_results.get(vid, {})
        actual_route = res.get("route_id")
        if actual_route and actual_route != v.get("routeId"):
            reassigned.append((v, actual_route))

    if reassigned:
        print(f"[!] Phát hiện {len(reassigned)} xe đã bị điều chuyển tuyến khác:", flush=True)
        for old_v, new_r in reassigned:
            print(f"    - Xe {old_v.get('title')} (ID {old_v['id']}): Route ID cũ {old_v.get('routeId')} -> Route ID mới {new_r}", flush=True)

    # Pha 2: Tự động khám phá xe mới bằng route_bus_gps (Kèm chữ ký epoch & proof chuẩn xác)
    print(f"\n[*] [Pha 2/3] Quét trực tiếp route_bus_gps tự động bổ sung xe cho các tuyến thiếu hụt...", flush=True)
    new_discovered_vehicles = []
    configured_vid_set = set(configured_vids)

    for route_no, route_id in configured_routes.items():
        # Chỉ đếm xe ACTIVE thật sự (không tính DEPOT/STALE/OFFLINE)
        active_on_route = sum(1 for r in audit_results.values() if r.get("route_id") == route_id and r.get("status") == "ACTIVE")
        if active_on_route < CATALOG_MIN_ACTIVE_PER_ROUTE:
            print(f"    - Tuyến {route_no} (ID {route_id}) chỉ có {active_on_route} xe ACTIVE, đang quét route_bus_gps 2 chiều...", flush=True)
            for d in (0, 1):
                live_buses = fetch_route_buses_live(route_id, direction=d)
                for b in live_buses:
                    try:
                        f_vid = int(b.get("Id") or b.get("id") or 0)
                        f_route = int(b.get("RouteId") or b.get("routeId") or 0)
                        f_plate = str(b.get("VehicleNumber") or b.get("title") or "")
                        if f_vid > 0 and f_route == route_id and f_vid not in configured_vid_set:
                            new_discovered_vehicles.append({
                                "id": f_vid,
                                "plate": f_plate,
                                "route_id": f_route,
                                "route_no": route_no
                            })
                            configured_vid_set.add(f_vid)
                            print(f"      + [route_bus_gps] Tìm thấy xe mới: {f_plate} (ID: {f_vid}) chiều {d}", flush=True)
                    except Exception:
                        pass
                time.sleep(0.15)

    # Pha 3: Tự động thanh lọc xe chết (Zombies Auto-Prune) & Đồng bộ cấu hình
    pruned_zombies = []
    cleaned_vehicles = []
    for v in config["vehicles"]:
        vid = v["id"]
        res = audit_results.get(vid, {})
        age_h = res.get("age_h")
        st = res.get("status")
        # Xe bị coi là zombie nếu treo không phát tín hiệu > CATALOG_PRUNE_STALE_HOURS (48h) hoặc offline lỗi
        if (st == "STALE" and age_h is not None and age_h >= CATALOG_PRUNE_STALE_HOURS) or (st == "OFFLINE" and res.get("error")):
            pruned_zombies.append(v)
            print(f"    - [Auto-Prune] Đã loại bỏ xe zombie không phát tín hiệu > 48h: {v.get('title')} (ID: {vid}, Route: {v.get('routeId')})", flush=True)
        else:
            cleaned_vehicles.append(v)

    if new_discovered_vehicles:
        for nv in new_discovered_vehicles:
            cleaned_vehicles.append({
                "id": nv["id"],
                "title": nv["plate"],
                "routeId": nv["route_id"]
            })

    config["vehicles"] = cleaned_vehicles
    config["total_vehicles"] = len(cleaned_vehicles)
    print(f"\n[*] [Pha 3/3] Tinh gọn danh bạ: Tổng {config['total_vehicles']} xe (Đã loại {len(pruned_zombies)} xe zombie, bổ sung {len(new_discovered_vehicles)} xe mới).", flush=True)

    config["last_catalog_refresh"] = ts_str
    save_cluster_config(config, CONFIG_FILE)

    # Lưu log báo cáo sức khỏe danh mục
    health_report = {
        "timestamp": ts_str,
        "total_configured": len(cleaned_vehicles),
        "active_rolling": active_count,
        "depot_idle": depot_count,
        "stale_frozen": stale_count,
        "offline": offline_count,
        "reassigned_count": len(reassigned),
        "newly_added_count": len(new_discovered_vehicles),
        "pruned_zombies_count": len(pruned_zombies)
    }
    
    os.makedirs("data/metadata", exist_ok=True)
    with open("data/metadata/daily_catalog_health.json", "w", encoding="utf-8") as f:
        json.dump(health_report, f, ensure_ascii=False, indent=2)

    print(f"[{hn_time.strftime('%H:%M:%S')}] 🎉 HOÀN TẤT RÀ SOÁT DANH BẠ ĐẦU NGÀY!\n", flush=True)

def main():
    run_daily_catalog_refresh()

if __name__ == "__main__":
    main()
