"""
Purge deprecated pilot routes from the active database.
Keeps strictly the 48 canonical active routes of the Hanoi Bus Tracking System.
"""

import sqlite3
import json
import sys

# Ensure UTF-8 output
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

conn = sqlite3.connect('data/hanoi_bus_system.db')
cur = conn.cursor()

# Deprecated pilot route IDs (only 5 days pilot: 08/10 to 12/10)
deprecated_route_ids = [3, 25, 31, 41, 835, 30000184]
deprecated_route_codes = ['03A', '25', '31', '41', '35B', 'E07TC']

print("=" * 70)
print("🧹 PURGING DEPRECATED PILOT ROUTES FROM DATABASE")
print(f"Target routes to remove: {deprecated_route_codes} (IDs: {deprecated_route_ids})")
print("=" * 70)

placeholders = ','.join('?' for _ in deprecated_route_ids)

# 1. Purge from route_projected_telemetry
cur.execute(f"DELETE FROM route_projected_telemetry WHERE route_id IN ({placeholders})", deprecated_route_ids)
deleted_proj = cur.rowcount
print(f"🗑️ Deleted {deleted_proj:,} pings from route_projected_telemetry")

# 2. Purge from agg_segment_travel_times
placeholders_code = ','.join('?' for _ in deprecated_route_codes)
cur.execute(f"DELETE FROM agg_segment_travel_times WHERE route_code IN ({placeholders_code})", deprecated_route_codes)
deleted_agg = cur.rowcount
print(f"🗑️ Deleted {deleted_agg:,} cells from agg_segment_travel_times")

# 3. Purge from vehicle_unique_pings
cur.execute(f"DELETE FROM vehicle_unique_pings WHERE route_id IN ({placeholders})", deprecated_route_ids)
deleted_vup = cur.rowcount
print(f"🗑️ Deleted {deleted_vup:,} pings from vehicle_unique_pings")

conn.commit()

# Verification
cur.execute("SELECT COUNT(DISTINCT route_id) FROM route_projected_telemetry")
proj_routes_cnt = cur.fetchone()[0]

cur.execute("SELECT COUNT(DISTINCT route_code) FROM route_projected_telemetry")
proj_codes_cnt = cur.fetchone()[0]

cur.execute("SELECT COUNT(*) FROM route_projected_telemetry")
total_proj_pings = cur.fetchone()[0]

print("=" * 70)
print(f"✅ CLEANUP VERIFICATION:")
print(f"Active Canonical Routes in route_projected_telemetry: {proj_routes_cnt} routes ({proj_codes_cnt} route codes)")
print(f"Total Projected Pings remaining: {total_proj_pings:,} pings")
print("=" * 70)

conn.close()

