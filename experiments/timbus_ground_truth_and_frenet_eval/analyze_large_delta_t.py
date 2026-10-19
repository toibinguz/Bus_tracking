import sqlite3
import sys
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")

conn = sqlite3.connect("data/telemetry_audit_2026_10_17_18.db")
c = conn.cursor()

print("=" * 70)
print("PHÂN TÍCH THỰC NGHIỆM ĐỘ LỆCH THỜI GIAN (DELTA TIME) TRÊN TOÀN BỘ DỮ LIỆU")
print("=" * 70)

# 1. Total intervals distribution
c.execute("""
SELECT 
    CASE 
        WHEN delta_t_sec <= 45 THEN '1. Nhịp chuẩn phần cứng (<= 45s)'
        WHEN delta_t_sec <= 90 THEN '2. Nhịp 1-2 chu kỳ crawl (46s - 90s)'
        WHEN delta_t_sec <= 180 THEN '3. Trễ nhẹ mạng/mất 1-2 nhịp (91s - 180s)'
        WHEN delta_t_sec <= 600 THEN '4. Nghỉ ngắn/chờ đèn/tắc nghẽn (3 - 10 phút)'
        WHEN delta_t_sec <= 1800 THEN '5. Nghỉ ca đầu bến (10 - 30 phút)'
        WHEN delta_t_sec <= 7200 THEN '6. Chờ ca/bảo dưỡng (30 phút - 2 giờ)'
        ELSE '7. Nghỉ đêm/ngoài giờ (> 2 giờ)'
    END AS gap_category,
    COUNT(*) AS count,
    ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM vehicle_intervals), 2) AS pct
FROM vehicle_intervals
GROUP BY gap_category
ORDER BY gap_category
""")

print(f"{'Nhóm khoảng thời gian (Delta t)':<45} | {'Số lượng':<10} | {'Tỷ lệ %'}")
print("-" * 70)
for r in c.fetchall():
    print(f"{r[0]:<45} | {r[1]:<10,} | {r[2]:>6.2f}%")

# 2. Specifically for Route 02
print("\n" + "=" * 70)
print("PHÂN TÍCH RIÊNG TRÊN TUYẾN 02:")
print("=" * 70)
c.execute("""
SELECT 
    CASE 
        WHEN delta_t_sec <= 45 THEN '1. Nhịp chuẩn phần cứng (<= 45s)'
        WHEN delta_t_sec <= 90 THEN '2. Nhịp 1-2 chu kỳ crawl (46s - 90s)'
        WHEN delta_t_sec <= 180 THEN '3. Trễ nhẹ mạng (91s - 180s)'
        WHEN delta_t_sec <= 600 THEN '4. Dừng đỗ/nghỉ ngắn (3 - 10 phút)'
        WHEN delta_t_sec <= 1800 THEN '5. Nghỉ ca đầu bến (10 - 30 phút)'
        WHEN delta_t_sec <= 7200 THEN '6. Chờ ca tiếp theo (30 phút - 2 giờ)'
        ELSE '7. Nghỉ đêm/ngoài giờ (> 2 giờ)'
    END AS gap_category,
    COUNT(*) AS count,
    ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM vehicle_intervals WHERE route_id IN ('02', '2')), 2) AS pct
FROM vehicle_intervals
WHERE route_id IN ('02', '2')
GROUP BY gap_category
ORDER BY gap_category
""")
for r in c.fetchall():
    print(f"{r[0]:<45} | {r[1]:<10,} | {r[2]:>6.2f}%")

# 3. Where do large gaps (> 10 minutes) physically happen?
print("\n" + "=" * 70)
print("VỊ TRÍ ĐỊA LÝ XẢY RA CÁC KHOẢNG NGHỈ LỚN (> 10 PHÚT) TRÊN TUYẾN 02:")
print("=" * 70)
c.execute("""
SELECT 
    vi.prev_station_id,
    COALESCE(s.station_name, 'Không rõ / Trong bến') AS station_name,
    COUNT(*) as gap_count,
    ROUND(AVG(vi.delta_t_sec) / 60.0, 1) as avg_gap_minutes
FROM vehicle_intervals vi
LEFT JOIN dim_station_crosswalk s ON vi.prev_station_id = s.station_id
WHERE vi.route_id IN ('02', '2') AND vi.delta_t_sec > 600
GROUP BY vi.prev_station_id
ORDER BY gap_count DESC
LIMIT 8
""")
print(f"{'Station ID':<12} | {'Tên vị trí':<45} | {'Số lần':<8} | {'Nghỉ TB (phút)'}")
print("-" * 80)
for r in c.fetchall():
    print(f"{str(r[0]):<12} | {r[1][:45]:<45} | {r[2]:<8} | {r[3]:>6.1f} phút")

conn.close()
