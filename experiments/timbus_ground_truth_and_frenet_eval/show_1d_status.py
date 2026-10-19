import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8")

conn = sqlite3.connect("data/telemetry_audit_2026_10_17_18.db")
c = conn.cursor()

# Query 1: Station 1D positions
print("=== 1. VỊ TRÍ 1D CỦA CÁC TRẠM (dim_station_crosswalk - Chiều đi) ===")
c.execute("""
SELECT station_order, station_id, station_name, cum_distance_m 
FROM dim_station_crosswalk 
WHERE direction = 'go' 
ORDER BY station_order
""")
stations = c.fetchall()
for r in stations[:6]:
    print(f"  Trạm #{r[0]+1:02d} [{r[1]:<5d}]: {r[2][:40]:<40} | s = {r[3]:>9.2f} m")
print("  ...")
for r in stations[-3:]:
    print(f"  Trạm #{r[0]+1:02d} [{r[1]:<5d}]: {r[2][:40]:<40} | s = {r[3]:>9.2f} m")

# Query 2: Bus 1D projected positions
print("\n=== 2. VỊ TRÍ 1D ÁNH XẠ CỦA XE BUÝT LÊN TIM ĐƯỜNG (route_02_projected_telemetry) ===")
c.execute("""
SELECT ping_id, fleet_code, timestamp, s_bus_m, cross_track_m, derived_speed_kmh, current_station_id
FROM route_02_projected_telemetry 
WHERE direction = 'go' AND derived_speed_kmh > 10.0
LIMIT 5
""")
for r in c.fetchall():
    print(f"  Ping #{r[0]} | Xe {r[1]} lúc {r[2][11:19]}: s_xe = {r[3]:>9.2f} m | d_perp = {r[4]:>5.1f} m | v_dan_xuat = {r[5]:>5.1f} km/h")

# Query 3: Real-time Distance to Downstream Stations
print("\n=== 3. VÍ DỤ GHÉP NỐI: TÍNH KHOẢNG CÁCH CÒN LẠI TỪ XE TỚI TRẠM ĐÍCH ===")
sample_bus = c.execute("""
SELECT ping_id, fleet_code, timestamp, s_bus_m, direction 
FROM route_02_projected_telemetry 
WHERE direction = 'go' AND s_bus_m BETWEEN 5000 AND 6000
LIMIT 1
""").fetchone()

if sample_bus:
    p_id, fleet, ts, s_bus, d_dir = sample_bus
    print(f"  Xe {fleet} tại thời điểm {ts[11:19]} đang ở vị trí s_bus = {s_bus:.1f} m (Km {s_bus/1000:.2f})")
    
    # Next 3 downstream stations
    c.execute("""
    SELECT station_order, station_id, station_name, cum_distance_m, (cum_distance_m - ?) AS dist_remaining
    FROM dim_station_crosswalk
    WHERE direction = ? AND cum_distance_m >= ?
    ORDER BY cum_distance_m ASC
    LIMIT 3
    """, (s_bus, d_dir, s_bus))
    
    print("  -> Các trạm kế tiếp và khoảng cách xe cần chạy tiếp:")
    for st in c.fetchall():
        print(f"     Trạm #{st[0]+1:02d} [{st[1]}]: {st[2][:35]:<35} | s_tram = {st[3]:>9.1f} m | Còn cách = {st[4]:>7.1f} m")

conn.close()

