import sys
import os
import time
from datetime import datetime
import numpy as np

sys.path.insert(0, os.path.abspath("."))
from module_1_data_ingestion_and_preprocessing.step_1_1_busmap_crawler_and_relay.catalog_refresher import (
    fetch_route_buses_live,
)


def parse_iso(ts_str):
    if "+" in ts_str:
        ts_clean = ts_str.split("+")[0]
    elif ts_str.endswith("Z"):
        ts_clean = ts_str[:-1]
    else:
        ts_clean = ts_str
    return datetime.fromisoformat(ts_clean)


def main():
    print("=" * 80)
    print("THỰC NGHIỆM ĐO CHU KỲ PHÁT GPS PHẦN CỨNG XE BUÝT HÀ NỘI (CỬA SỔ 150 GIÂY)")
    print("Theo dõi 15-20 xe trên Tuyến 02 & Tuyến 32 | Lấy mẫu mỗi 5 giây")
    print("=" * 80, flush=True)

    prev_pings = {}
    transitions = []

    start_time = time.time()
    max_duration = 150  # 2.5 minutes
    poll_idx = 0

    while time.time() - start_time < max_duration:
        poll_idx += 1
        now_dt = datetime.now()
        now_str = now_dt.strftime("%H:%M:%S")

        try:
            r2 = fetch_route_buses_live(2, 0) or []
            r32 = fetch_route_buses_live(32, 0) or []
            buses = r2 + r32
        except Exception as e:
            print(f"[{now_str}] Lỗi kết nối: {e}", flush=True)
            buses = []

        n_new = 0
        for b in buses:
            vid = str(b.get("Id", ""))
            plate = str(b.get("VehicleNumber", vid))
            ts_str = b.get("lastUpdateTime", "")
            if not vid or not ts_str:
                continue

            dt_obj = parse_iso(ts_str)

            if vid in prev_pings:
                old_dt, old_lat, old_lng, old_spd = prev_pings[vid]
                if dt_obj > old_dt:
                    hw_delta_sec = (dt_obj - old_dt).total_seconds()
                    server_lag_sec = (now_dt - dt_obj).total_seconds()

                    transitions.append({
                        "vid": vid,
                        "plate": plate,
                        "old_ts": old_dt.strftime("%H:%M:%S"),
                        "new_ts": dt_obj.strftime("%H:%M:%S"),
                        "hw_delta_sec": hw_delta_sec,
                        "server_lag_sec": round(server_lag_sec, 1),
                        "lat": b.get("Lat"),
                        "lng": b.get("Lng"),
                        "speed": b.get("Speed"),
                    })
                    n_new += 1
                    print(
                        f"[{now_str}] 🎯 XE {plate:<10} NHẢY BẢN TIN: "
                        f"{old_dt.strftime('%H:%M:%S')} -> {dt_obj.strftime('%H:%M:%S')} | "
                        f"Δt PHẦN CỨNG = {hw_delta_sec:.0f}s | Độ trễ Server = {server_lag_sec:.1f}s | V = {b.get('Speed')} km/h",
                        flush=True,
                    )

            prev_pings[vid] = (dt_obj, b.get("Lat"), b.get("Lng"), b.get("Speed"))

        time.sleep(5)

    print("\n" + "=" * 80)
    print("TỔNG HỢP KẾT QUẢ THỰC NGHIỆM ĐO ĐẠC PHẦN CỨNG GPS")
    print("=" * 80)
    print(f"[*] Tổng số xe theo dõi: {len(prev_pings)}")
    print(f"[*] Tổng số lần ghi nhận phần cứng nhảy bản tin mới: {len(transitions)}")

    if transitions:
        hw_deltas = [t["hw_delta_sec"] for t in transitions]
        server_lags = [t["server_lag_sec"] for t in transitions]

        vals, counts = np.unique(hw_deltas, return_counts=True)
        mode_val = vals[np.argmax(counts)]

        print(f"\n--- THỐNG KÊ KHOẢNG TIN PHẦN CỨNG GPS (Δt) ---")
        print(f"  • Trung bình (Mean)    : {np.mean(hw_deltas):.1f} giây")
        print(f"  • Trung vị (Median P50) : {np.median(hw_deltas):.1f} giây")
        print(f"  • Giá trị phổ biến nhất (Mode): {mode_val:.0f} giây ({np.max(counts)}/{len(transitions)} lần)")
        print(f"  • Min - Max            : [{np.min(hw_deltas):.0f}s, {np.max(hw_deltas):.0f}s]")
        print(f"  • Phân vị [P10, P90]   : [{np.percentile(hw_deltas, 10):.1f}s, {np.percentile(hw_deltas, 90):.1f}s]")

        print(f"\n--- ĐỘ TRỄ TRUYỀN DẪN VỀ MÁY CHỦ (SERVER PROPAGATION LAG) ---")
        print(f"  • Trung vị độ trễ (P50): {np.median(server_lags):.1f} giây")
        print(f"  • Khoảng trễ phổ biến  : [{np.percentile(server_lags, 10):.1f}s - {np.percentile(server_lags, 90):.1f}s]")
    else:
        print("[!] Không có bản tin nào nhảy trong khoảng thời gian đo.")


if __name__ == "__main__":
    main()
