import sqlite3
import sys

sys.stdout.reconfigure(encoding='utf-8')

conn = sqlite3.connect('data/telemetry_audit_2026_10_17_18.db')
c = conn.cursor()

print("=== 1. AUDIT LOG (pipeline_data_lineage_audit) ===")
for row in c.execute("SELECT audit_id, pipeline_name, source_system, entity_id, records_count, checksum_sha256, execution_status, execution_timestamp FROM pipeline_data_lineage_audit"):
    print(row)

print("\n=== 2. ROUTE MASTER (timbus_route_master) ===")
for row in c.execute("SELECT fleet_id, route_code, route_name, bus_count, first_station, last_station FROM timbus_route_master"):
    print(row)

print("\n=== 3. SAMPLE STATIONS (timbus_station_master - Go direction) ===")
for row in c.execute("SELECT direction, station_order, station_id, station_name, lat, lon, cum_distance_m FROM timbus_station_master WHERE direction='go' AND station_order IN (0, 1, 2, 38, 39) ORDER BY station_order"):
    print(row)

print("\n=== 4. SHAPE MASTER STATS (timbus_shape_master) ===")
for row in c.execute("SELECT direction, COUNT(*), MIN(cum_distance_m), MAX(cum_distance_m) FROM timbus_shape_master GROUP BY direction"):
    print(f"Direction {row[0]}: {row[1]} points, Total Length: {row[3]:.1f} meters (~{row[3]/1000:.2f} km)")

