import sqlite3
import sys
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")

conn = sqlite3.connect("data/telemetry_audit_2026_10_17_18.db")
c = conn.cursor()

print("=" * 70)
print("PHÂN TÍCH BẢN CHẤT CÁC KHOẢNG NGHỈ LỚN (DELTA T > 3 PHÚT) TRÊN TUYẾN 02:")
print("=" * 70)

query = """
SELECT 
    vi.interval_id,
    vi.plate,
    vi.prev_time,
    vi.curr_time,
    ROUND(vi.delta_t_sec / 60.0, 1) as delta_t_min,
    ROUND(vi.distance_m, 1) as dist_m,
    ROUND(vi.speed_kmh, 1) as speed_kmh,
    p1.current_station_id as st_id,
    COALESCE(s.station_name, 'Không rõ / Trong bến') as station_name
FROM vehicle_intervals vi
LEFT JOIN vehicle_unique_pings p1 
  ON vi.vehicle_id = p1.vehicle_id AND vi.prev_epoch = p1.device_epoch
LEFT JOIN dim_station_crosswalk s 
  ON p1.current_station_id = s.station_id
WHERE vi.route_id IN ('02', '2') AND vi.delta_t_sec > 180
ORDER BY vi.delta_t_sec DESC
LIMIT 15
"""

print(f"{'Biển số':<12} | {'Khoảng nghỉ':<12} | {'Dịch chuyển':<12} | {'Trạm / Vị trí':<45}")
print("-" * 85)
for r in c.execute(query):
    print(f"{r[1]:<12} | {r[4]:>5.1f} phút   | {r[5]:>7.1f} m   | [{str(r[7]):<4}] {r[8][:38]}")

# Check distance moved during gaps: Is vehicle stationary (parking) or moving?
c.execute("""
SELECT 
    CASE 
        WHEN distance_m < 50.0 THEN 'Xe đứng yên một chỗ / Đỗ bến (< 50m)'
        WHEN distance_m < 300.0 THEN 'Xe nhích chậm trong bãi đỗ (50 - 300m)'
        ELSE 'Xe di chuyển trên đường (> 300m - mất sóng/mất gói tin)'
    END AS movement_type,
    COUNT(*) AS count,
    ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM vehicle_intervals WHERE route_id IN ('02', '2') AND delta_t_sec > 180), 1) as pct,
    ROUND(AVG(delta_t_sec) / 60.0, 1) as avg_min
FROM vehicle_intervals
WHERE route_id IN ('02', '2') AND delta_t_sec > 180
GROUP BY movement_type
""")
print("\n" + "=" * 70)
print("BẢN CHẤT CỦA CÁC KHOẢNG TRỄ > 3 PHÚT (XE ĐANG LÀM GÌ?):")
print("=" * 70)
for r in c.fetchall():
    print(f"  * {r[0]:<45}: {r[1]:>4} lần ({r[2]}%) | Nghỉ TB: {r[3]} phút")

conn.close()
