import sqlite3
import sys
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")

conn = sqlite3.connect("data/telemetry_audit_2026_10_17_18.db")
c = conn.cursor()

# Check top stations where buses dwell
query = """
SELECT t.current_station_id, s.station_name, s.cum_distance_m,
       COUNT(*) as pings_count,
       ROUND(AVG(t.s_bus_m), 1) as avg_bus_s,
       ROUND(AVG(t.s_bus_m - s.cum_distance_m), 1) as avg_offset_m
FROM route_02_projected_telemetry t
JOIN timbus_station_master s 
  ON t.current_station_id = s.station_id AND t.direction = s.direction
WHERE t.direction = 'go' AND t.delta_s_m < 15.0 AND t.delta_t_s >= 20.0
GROUP BY t.current_station_id
HAVING pings_count >= 10
ORDER BY pings_count DESC
LIMIT 10
"""

print(f"{'Station ID':<10} | {'Station Name':<35} | {'s_tram (m)':<10} | {'s_xe_TB (m)':<12} | {'Offset (m)':<10} | {'Dwell Pings'}")
print("-" * 95)
for r in c.execute(query):
    print(f"{r[0]:<10} | {r[1][:35]:<35} | {r[2]:<10} | {r[3]:<12} | {r[4]:<10} | {r[5]}")

conn.close()

