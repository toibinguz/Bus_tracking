"""
Test Mapping A (-1 -> go, 1 -> re) across major routes on canonical shape
"""
import sqlite3

from module_1_data_ingestion_and_preprocessing.step_1_4_frenet_spatial_projection.multi_route_projector import (
    project_points_to_shape
)

conn = sqlite3.connect('data/hanoi_bus_system.db')
cur = conn.cursor()

test_routes = ['02', '22A', '34', 'BRT01', '26', 'E05', '19', '11']

for rc in test_routes:
    shapes = {"go": [], "re": []}
    for row in cur.execute("""
        SELECT direction, point_order, lat, lon, cum_distance_m 
        FROM canonical_shape_master 
        WHERE route_code = ? 
        ORDER BY direction, point_order
    """, (rc,)).fetchall():
        d = row[0].lower()
        shapes[d].append((row[1], row[2], row[3], row[4]))
        
    cur.execute("""
        SELECT p.ping_id, p.vehicle_id, p.plate, p.device_update_time, p.device_epoch, p.direction, p.lat, p.lon
        FROM vehicle_unique_pings p
        JOIN canonical_route_master r ON p.route_id = r.route_id
        WHERE r.route_code = ? AND p.lat > 20.0 AND p.lon > 105.0
        ORDER BY p.vehicle_id, p.device_epoch;
    """, (rc,))
    pings = cur.fetchall()
    
    # Mapping A: -1 -> go, 1 -> re
    pings_by_dir = {"go": [], "re": []}
    for p in pings:
        d_str = "go" if p[5] == -1 else "re"
        pings_by_dir[d_str].append((p[0], p[6], p[7], p[4]))
        
    all_dperps = []
    for d_str in ["go", "re"]:
        if shapes[d_str] and pings_by_dir[d_str]:
            res = project_points_to_shape(pings_by_dir[d_str], shapes[d_str])
            all_dperps.extend([r[2] for r in res])
            
    if not all_dperps:
        continue
        
    all_dperps.sort()
    in_30 = sum(1 for d in all_dperps if d <= 30.0) / len(all_dperps) * 100
    in_15 = sum(1 for d in all_dperps if d <= 15.0) / len(all_dperps) * 100
    med_d = all_dperps[len(all_dperps)//2]
    
    print(f"Route {rc:<6} ({len(pings):>6,} pings): in-lane (<=30m) = {in_30:>5.1f}%, (<=15m) = {in_15:>5.1f}%, median d_perp = {med_d:>4.1f}m")

