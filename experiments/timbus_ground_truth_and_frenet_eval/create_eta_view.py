import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8")

conn = sqlite3.connect("data/telemetry_audit_2026_10_17_18.db")
c = conn.cursor()

# Create a clean feature view for real-time ETA
c.execute("""
CREATE VIEW IF NOT EXISTS v_route_02_bus_to_next_station AS
SELECT 
    t.ping_id,
    t.fleet_code,
    t.timestamp,
    t.epoch,
    t.direction,
    t.lat AS bus_lat,
    t.lon AS bus_lon,
    t.s_bus_m,
    t.cross_track_m,
    t.derived_speed_kmh,
    s.station_order AS next_station_order,
    s.station_id AS next_station_id,
    s.station_name AS next_station_name,
    s.cum_distance_m AS next_station_s,
    ROUND(s.cum_distance_m - t.s_bus_m, 2) AS distance_remaining_m
FROM route_02_projected_telemetry t
JOIN dim_station_crosswalk s
  ON t.direction = s.direction 
 AND s.cum_distance_m = (
     SELECT MIN(s2.cum_distance_m)
     FROM dim_station_crosswalk s2
     WHERE s2.direction = t.direction 
       AND s2.cum_distance_m >= t.s_bus_m
 );
""")

conn.commit()
print("View 'v_route_02_bus_to_next_station' created successfully!")

# Sample from view
print("\n--- SAMPLE TỪ VIEW 'v_route_02_bus_to_next_station' ---")
c.execute("""
SELECT fleet_code, timestamp, s_bus_m, derived_speed_kmh, next_station_name, distance_remaining_m
FROM v_route_02_bus_to_next_station
WHERE derived_speed_kmh > 15.0
LIMIT 5
""")
for r in c.fetchall():
    print(f"Xe {r[0]} | {r[1][11:19]} | s = {r[2]:>8.1f}m | v = {r[3]:>4.1f} km/h | Trạm tới: {r[4][:30]:<30} | Còn cách: {r[5]:>7.1f}m")

conn.close()

