"""
Experiment: Live Probe of Hardware GPS Ping Interval on Active Hanoi Buses.
Sample size: 10 - 20 active buses on Route 02 & Route 32.
Measures empirical distribution of delta_t between consecutive hardware GPS updates.
"""

import math
import os
import sys
import time
from datetime import datetime
from collections import defaultdict
import numpy as np

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, BASE_DIR)

from module_1_data_ingestion_and_preprocessing.step_1_1_busmap_crawler_and_relay.catalog_refresher import (
    fetch_route_buses_live,
)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Computes great-circle distance between two points in meters."""
    R = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2.0) ** 2
    return 2.0 * R * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def parse_iso_time(ts_str: str) -> datetime:
    """Parses ISO timestamp string from BusMap API (e.g., '2026-11-08T09:50:22+07:00')."""
    # Truncate timezone offset if necessary
    if "+" in ts_str:
        ts_clean = ts_str.split("+")[0]
    elif ts_str.endswith("Z"):
        ts_clean = ts_str[:-1]
    else:
        ts_clean = ts_str
    return datetime.fromisoformat(ts_clean)


def run_live_probe(duration_sec: int = 75, poll_interval_sec: float = 2.0):
    print("=" * 80)
    print("THỰC NGHIỆM ĐO ĐẠC KHOẢNG TIN THỰC CỦA GPS PHẦN CỨNG TRÊN XE BUÝT HÀ NỘI")
    print(f"[*] Phạm vi: Tuyến 02 (ID=2) và Tuyến 32 (ID=32) (~15-20 xe)")
    print(f"[*] Tần suất thăm dò: {poll_interval_sec}s/lần | Tổng thời gian đo: {duration_sec}s")
    print("=" * 80)

    # State tracking: vid -> last seen record dict
    prev_states = {}
    
    # Transition events: list of dicts
    update_events = []

    start_time = time.time()
    cycle = 0

    while (time.time() - start_time) < duration_sec:
        cycle += 1
        t_cycle_start = time.time()
        
        # 1. Fetch live snapshot from 2 routes
        raw_buses = []
        try:
            r2 = fetch_route_buses_live(route_id=2, direction=0) or []
            r32 = fetch_route_buses_live(route_id=32, direction=0) or []
            raw_buses = r2 + r32
        except Exception as e:
            print(f"[!] Lỗi kết nối ở chu kỳ {cycle}: {e}")

        now_wall = time.time()
        new_updates_in_cycle = 0

        for b in raw_buses:
            vid = str(b.get("Id", ""))
            plate = str(b.get("VehicleNumber", vid))
            ts_str = b.get("lastUpdateTime", "")
            if not vid or not ts_str:
                continue

            lat = float(b.get("Lat", 0.0))
            lng = float(b.get("Lng", 0.0))
            raw_spd = float(b.get("Speed", 0.0))

            dt_obj = parse_iso_time(ts_str)

            if vid in prev_states:
                old = prev_states[vid]
                if dt_obj > old["dt"]:
                    # Timestamp has advanced! Hardware transmitted a new ping
                    dt_sec = (dt_obj - old["dt"]).total_seconds()
                    ds_m = haversine_m(old["lat"], old["lon"], lat, lng)
                    derived_spd = (ds_m / dt_sec * 3.6) if dt_sec > 0 else 0.0
                    wall_elapsed = now_wall - old["wall_time"]

                    update_events.append({
                        "vehicle_id": vid,
                        "plate": plate,
                        "prev_dt": old["dt"].strftime("%H:%M:%S"),
                        "curr_dt": dt_obj.strftime("%H:%M:%S"),
                        "dt_sec": dt_sec,
                        "wall_elapsed_sec": round(wall_elapsed, 1),
                        "ds_m": round(ds_m, 1),
                        "raw_spd": round(raw_spd, 1),
                        "derived_spd": round(derived_spd, 1),
                        "is_moving": (raw_spd > 3.0 or derived_spd > 3.0),
                    })

                    new_updates_in_cycle += 1
                    print(
                        f"  [+] Xe {plate:<10} | Δt = {dt_sec:>4.0f}s (thực tế={wall_elapsed:>4.1f}s) | "
                        f"Δs = {ds_m:>5.1f}m | V_cảm biến = {raw_spd:>4.1f} km/h | V_dẫn xuất = {derived_spd:>4.1f} km/h"
                    )

            # Update state
            prev_states[vid] = {
                "plate": plate,
                "dt": dt_obj,
                "lat": lat,
                "lon": lng,
                "spd": raw_spd,
                "wall_time": now_wall,
            }

        elapsed = time.time() - t_cycle_start
        sleep_dur = max(0.1, poll_interval_sec - elapsed)
        time.sleep(sleep_dur)

    print("\n" + "=" * 80)
    print("KẾT QUẢ PHÂN TÍCH THỐNG KÊ ĐỊNH LƯỢNG (EMPIRICAL STATISTICAL SUMMARY)")
    print("=" * 80)

    total_tracked_vehicles = len(prev_states)
    total_events = len(update_events)

    print(f"[*] Tổng số xe theo dõi: {total_tracked_vehicles} xe")
    print(f"[*] Tổng số bước nhảy thời gian (GPS Update Events): {total_events} sự kiện")

    if total_events == 0:
        print("[!] Không thu được sự kiện cập nhật nào trong khoảng thời gian đo.")
        return

    dt_all = np.array([e["dt_sec"] for e in update_events], dtype=np.float64)
    dt_moving = np.array([e["dt_sec"] for e in update_events if e["is_moving"]], dtype=np.float64)
    dt_stopped = np.array([e["dt_sec"] for e in update_events if not e["is_moving"]], dtype=np.float64)

    def print_dist(name: str, arr: np.ndarray):
        if len(arr) == 0:
            print(f"[*] {name}: Không có mẫu.")
            return
        vals, counts = np.unique(arr, return_counts=True)
        mode_val = vals[np.argmax(counts)]
        mode_pct = 100.0 * np.max(counts) / len(arr)

        print(f"\n--- Phân phối khoảng tin: {name} (N = {len(arr)} sự kiện) ---")
        print(f"  • Trung bình (Mean)   : {np.mean(arr):.2f} giây")
        print(f"  • Trung vị (Median P50): {np.median(arr):.2f} giây")
        print(f"  • Giá trị phổ biến (Mode): {mode_val:.0f} giây ({mode_pct:.1f}% số mẫu)")
        print(f"  • Phân vị P10 - P90   : [{np.percentile(arr, 10):.1f}s, {np.percentile(arr, 90):.1f}s]")
        print(f"  • Min - Max           : [{np.min(arr):.1f}s, {np.max(arr):.1f}s]")
        print(f"  • Độ lệch chuẩn (Std) : {np.std(arr):.2f} giây")

    print_dist("TOÀN BỘ CÁC XE", dt_all)
    print_dist("KHI XE ĐANG CHẠY (V > 3 km/h)", dt_moving)
    print_dist("KHI XE DỪNG ĐỖ / CHỜ ĐÈN (V <= 3 km/h)", dt_stopped)

    # Histogram buckets
    b_under10 = np.sum(dt_all < 10)
    b_10_15 = np.sum((dt_all >= 10) & (dt_all <= 15))
    b_16_20 = np.sum((dt_all > 15) & (dt_all <= 20))
    b_21_30 = np.sum((dt_all > 20) & (dt_all <= 30))
    b_over30 = np.sum(dt_all > 30)

    print("\n--- BẢNG PHÂN BỐ TẦN SUẤT KHOẢNG TIN GPS PHẦN CỨNG ---")
    print(f"  [< 10s]     : {b_under10:>3} ({100.0*b_under10/total_events:.1f}%)")
    print(f"  [10s - 15s] : {b_10_15:>3} ({100.0*b_10_15/total_events:.1f}%)")
    print(f"  [16s - 20s] : {b_16_20:>3} ({100.0*b_16_20/total_events:.1f}%)")
    print(f"  [21s - 30s] : {b_21_30:>3} ({100.0*b_21_30/total_events:.1f}%)")
    print(f"  [> 30s]     : {b_over30:>3} ({100.0*b_over30/total_events:.1f}%)")
    print("=" * 80)


if __name__ == "__main__":
    duration = 70
    if len(sys.argv) > 1:
        try:
            duration = int(sys.argv[1])
        except ValueError:
            pass
    run_live_probe(duration_sec=duration, poll_interval_sec=2.0)
