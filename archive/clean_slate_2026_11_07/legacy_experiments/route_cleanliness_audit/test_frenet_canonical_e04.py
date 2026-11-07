"""
Test Frenet segment projection on canonical shape for E04
"""
import sqlite3
import math

from module_1_data_ingestion_and_preprocessing.step_1_4_frenet_spatial_projection.multi_route_projector import (
    project_points_to_shape
)

conn = sqlite3.connect('data/hanoi_bus_system.db')
cur = conn.cursor()

# Load canonical shape for E04
shapes = {"go": [], "re": []}
for row in cur.execute("""
    SELECT direction, point_order, lat, lon, cum_distance_m 
    FROM canonical_shape_master 
    WHERE route_code = 'E04' 
    ORDER BY direction, point_order
""").fetchall():
    d = row[0].lower()
    shapes[d].append((row[1], row[2], row[3], row[4]))

print(f"Loaded Canonical E04 shape: go={len(shapes['go'])} pts, re={len(shapes['re'])} pts")

# Fetch E04 pings from vehicle_unique_pings
cur.execute("""
    SELECT ping_id, vehicle_id, plate, device_update_time, device_epoch, direction, lat, lon
    FROM vehicle_unique_pings
    WHERE route_id = 101109 AND lat > 20.0 AND lon > 105.0
    ORDER BY vehicle_id, device_epoch;
""")
pings = cur.fetchall()
print(f"Total E04 pings: {len(pings):,}")

# Filter genuine buses (exclude contracted van 29H93569 and North route 1408909)
clean_pings = [p for p in pings if p[6] < 21.1 and p[2] and p[2].startswith('29F')]
print(f"Genuine E04 VinBus pings: {len(clean_pings):,}")

# Test projection when ping direction 1 -> re, -1 -> go vs 1 -> go, -1 -> re
for mapping_name, (dir_for_1, dir_for_neg1) in [
    ("Mapping A: 1 -> re, -1 -> go", ("re", "go")),
    ("Mapping B: 1 -> go, -1 -> re", ("go", "re"))
]:
    pings_by_dir = {"go": [], "re": []}
    for p in clean_pings:
        d_str = dir_for_1 if p[5] == 1 else dir_for_neg1
        pings_by_dir[d_str].append((p[0], p[6], p[7], p[4]))
    
    all_dperps = []
    for d_str in ["go", "re"]:
        if shapes[d_str] and pings_by_dir[d_str]:
            res = project_points_to_shape(pings_by_dir[d_str], shapes[d_str])
            all_dperps.extend([r[2] for r in res])
            
    all_dperps.sort()
    in_15 = sum(1 for d in all_dperps if d <= 15.0) / len(all_dperps) * 100
    in_30 = sum(1 for d in all_dperps if d <= 30.0) / len(all_dperps) * 100
    med_d = all_dperps[len(all_dperps)//2]
    p90_d = all_dperps[int(len(all_dperps)*0.9)]
    
    print(f"\n{mapping_name}:")
    print(f"  In-lane (<=30m): {in_30:.1f}%, In-lane (<=15m): {in_15:.1f}%")
    print(f"  Median d_perp: {med_d:.1f}m, P90 d_perp: {p90_d:.1f}m")

