"""
Create v_segment_dispersion_matrix view in SQLite.
Provides direct access to segment travel times, median P50, decile spread (P90 - P10),
relative dispersion %, standard deviation, and commercial speed.
"""

import sqlite3
import sys

# Ensure UTF-8 output
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

conn = sqlite3.connect('data/hanoi_bus_system.db')
cur = conn.cursor()

view_sql = """
CREATE VIEW IF NOT EXISTS v_segment_dispersion_matrix AS
SELECT 
    route_code,
    direction,
    from_station_order,
    to_station_order,
    from_station_order || ' -> ' || to_station_order AS segment_id,
    from_station_name,
    to_station_name,
    segment_distance_m,
    day_type,
    time_window,
    sample_count,
    median_transit_sec AS p50_transit_sec,
    p10_transit_sec,
    p90_transit_sec,
    ROUND(p90_transit_sec - p10_transit_sec, 2) AS spread_decile_sec,
    ROUND((p90_transit_sec - p10_transit_sec) * 100.0 / NULLIF(median_transit_sec, 0), 1) AS relative_dispersion_pct,
    std_transit_sec,
    mean_transit_sec,
    commercial_speed_kmh,
    is_interpolated
FROM agg_segment_travel_times;
"""

cur.execute("DROP VIEW IF EXISTS v_segment_dispersion_matrix;")
cur.execute(view_sql)
conn.commit()

print("✅ Created view v_segment_dispersion_matrix successfully.")

# Quick test
cur.execute("SELECT segment_id, time_window, sample_count, p50_transit_sec, spread_decile_sec, relative_dispersion_pct, commercial_speed_kmh FROM v_segment_dispersion_matrix WHERE route_code = '02' AND direction = 'go' AND day_type = 'WEEKDAY' AND from_station_order = 20;")
for row in cur.fetchall():
    print(" ", row)

conn.close()
