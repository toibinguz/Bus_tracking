"""
Upgrade v_bus_to_next_station view to use canonical_station_master.
Provides complete coverage across all 48 routes (13,301 canonical stations).
"""

import sqlite3
import sys
import os

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "hanoi_bus_system.db")

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# Ensure high-speed index on canonical_station_master
cur.execute("CREATE INDEX IF NOT EXISTS idx_cstat_route_dir_s ON canonical_station_master (route_code, direction, cum_distance_m);")

view_sql = """
CREATE VIEW IF NOT EXISTS v_bus_to_next_station AS
SELECT 
    t.ping_id,
    t.route_code,
    t.route_id,
    t.vehicle_id,
    t.plate,
    t.device_update_time,
    t.device_epoch,
    t.direction,
    t.lat AS bus_lat,
    t.lon AS bus_lon,
    t.s_bus_m,
    t.cross_track_m,
    t.derived_speed_kmh,
    t.is_dwell,
    s.station_order AS next_station_order,
    s.station_id AS next_station_id,
    s.station_name AS next_station_name,
    s.cum_distance_m AS next_station_s,
    ROUND(s.cum_distance_m - t.s_bus_m, 2) AS distance_remaining_m
FROM route_projected_telemetry t
JOIN canonical_station_master s
  ON t.route_code = s.route_code
 AND t.direction = s.direction 
 AND s.cum_distance_m = (
     SELECT MIN(s2.cum_distance_m)
     FROM canonical_station_master s2
     WHERE s2.route_code = t.route_code
       AND s2.direction = t.direction 
       AND s2.cum_distance_m >= t.s_bus_m
 );
"""

cur.execute("DROP VIEW IF EXISTS v_bus_to_next_station;")
cur.execute(view_sql)
conn.commit()
print("✅ Successfully upgraded v_bus_to_next_station to join canonical_station_master.")

# Verification
cur.execute("SELECT COUNT(*) FROM v_bus_to_next_station WHERE route_code = '02' LIMIT 5;")
print(f"Sample count for Route 02: {cur.fetchone()[0]:,}")

conn.close()

