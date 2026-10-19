import sqlite3
import sys
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")

conn = sqlite3.connect("data/telemetry_audit_2026_10_17_18.db")
c = conn.cursor()

print("=" * 80)
print("PHÂN TÍCH HAI DẠNG KHOẢNG TRỄ LỚN (DELTA T > 3 PHÚT) TRÊN TOÀN BỘ HỆ THỐNG & TUYẾN 02")
print("=" * 80)

# 1. Classification across entire system (vehicle_intervals)
c.execute("""
SELECT 
    CASE 
        WHEN distance_m < 30.0 THEN 'DẠNG A: Đứng yên một chỗ (Delta m < 30m)'
        WHEN distance_m < 200.0 THEN 'DẠNG B1: Dịch chuyển rất nhỏ/trong bãi (30m <= Delta m < 200m)'
        WHEN distance_m < 2000.0 THEN 'DẠNG B2: Di chuyển trên phố (200m <= Delta m < 2km)'
        ELSE 'DẠNG B3: Nhảy vọt cự ly lớn (Delta m >= 2km)'
    END AS pattern_type,
    COUNT(*) AS count,
    ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM vehicle_intervals WHERE delta_t_sec > 180), 2) AS pct,
    ROUND(AVG(delta_t_sec) / 60.0, 1) AS avg_delta_t_min,
    ROUND(AVG(distance_m), 1) AS avg_dist_m,
    ROUND(AVG(speed_kmh), 1) AS avg_speed_kmh
FROM vehicle_intervals
WHERE delta_t_sec > 180
GROUP BY pattern_type
ORDER BY count DESC
""")

print(f"{'Dạng khoảng trễ (Delta t > 3 phút)':<48} | {'Số lượng':<8} | {'Tỷ lệ %':<8} | {'Delta t TB':<12} | {'Quãng đường TB':<15} | {'Vận tốc TB'}")
print("-" * 115)
for r in c.fetchall():
    print(f"{r[0]:<48} | {r[1]:<8,} | {r[2]:>6.2f}% | {r[3]:>6.1f} phút   | {r[4]:>9.1f} m     | {r[5]:>5.1f} km/h")

# 2. Specifically for Route 02: Let's inspect the exact examples of Pattern A vs Pattern B
print("\n" + "=" * 80)
print("CHI TIẾT TRÊN TUYẾN 02: VÍ DỤ THỰC TẾ CỦA 2 DẠNG")
print("=" * 80)

# Pattern A examples (delta_m == 0 or small)
print("\n--- [DẠNG A: DELTA M == 0 HOẶC RẤT NHỎ (< 30M) - XE ĐỨNG YÊN / ĐỖ BẾN] ---")
c.execute("""
SELECT vi.plate, ROUND(vi.delta_t_sec/60.0, 1), ROUND(vi.distance_m, 1), vi.prev_time, vi.curr_time,
       p1.current_station_id, COALESCE(s.station_name, 'Không rõ')
FROM vehicle_intervals vi
LEFT JOIN vehicle_unique_pings p1 ON vi.vehicle_id = p1.vehicle_id AND vi.prev_epoch = p1.device_epoch
LEFT JOIN dim_station_crosswalk s ON p1.current_station_id = s.station_id
WHERE vi.route_id IN ('02', '2') AND vi.delta_t_sec > 180 AND vi.distance_m < 30.0
ORDER BY vi.delta_t_sec DESC
LIMIT 5
""")
print(f"{'Biển số':<12} | {'Nghỉ':<10} | {'Dịch chuyển':<12} | {'Thời gian':<20} | {'Trạm / Vị trí':<35}")
print("-" * 95)
for r in c.fetchall():
    print(f"{r[0]:<12} | {r[1]:>5.1f} phút | {r[2]:>5.1f} m      | {r[3][11:19]} -> {r[4][11:19]} | [{r[5]}] {r[6][:30]}")

# Pattern B examples (delta_m large)
print("\n--- [DẠNG B: DELTA M LỚN (> 1000M) - XE DI CHUYỂN NHƯNG MẤT SÓNG HOẶC ĐỔI CA] ---")
c.execute("""
SELECT vi.plate, ROUND(vi.delta_t_sec/60.0, 1), ROUND(vi.distance_m, 1), ROUND(vi.speed_kmh, 1), vi.prev_time, vi.curr_time,
       p1.current_station_id, COALESCE(s.station_name, 'Không rõ')
FROM vehicle_intervals vi
LEFT JOIN vehicle_unique_pings p1 ON vi.vehicle_id = p1.vehicle_id AND vi.prev_epoch = p1.device_epoch
LEFT JOIN dim_station_crosswalk s ON p1.current_station_id = s.station_id
WHERE vi.route_id IN ('02', '2') AND vi.delta_t_sec > 180 AND vi.distance_m >= 1000.0
ORDER BY vi.delta_t_sec DESC
LIMIT 5
""")
print(f"{'Biển số':<12} | {'Khoảng trễ':<12} | {'Quãng đường':<14} | {'Vận tốc TB':<12} | {'Thời gian':<20} | {'Trạm ban đầu'}")
print("-" * 105)
for r in c.fetchall():
    print(f"{r[0]:<12} | {r[1]:>5.1f} phút   | {r[2]:>8.1f} m     | {r[3]:>5.1f} km/h   | {r[4][11:19]} -> {r[5][11:19]} | [{r[6]}] {r[7][:25]}")

conn.close()

