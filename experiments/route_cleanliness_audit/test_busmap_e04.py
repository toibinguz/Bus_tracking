"""
Check endpoint alignment and projection for both directions of E04
"""
import json
import sqlite3
import os
import math
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi/2.0)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2.0)**2
    return 2.0 * R * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))

def min_dist(lat, lon, poly):
    min_d = 999999.0
    for i in range(len(poly) - 1):
        p1, p2 = poly[i], poly[i+1]
        d1 = haversine_m(lat, lon, p1[0], p1[1])
        d2 = haversine_m(lat, lon, p2[0], p2[1])
        mid_lat, mid_lon = (p1[0]+p2[0])/2, (p1[1]+p2[1])/2
        dmid = haversine_m(lat, lon, mid_lat, mid_lon)
        min_d = min(min_d, d1, d2, dmid)
    return min_d

geojson_path = 'data/ground_truth/busmap_canonical/hanoi_bus_routes.geojson'
if not os.path.exists(geojson_path):
    geojson_path = 'hanoi_bus_data/hanoi_bus_routes.geojson'

with open(geojson_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

bm_shapes = {}
for feat in data['features']:
    props = feat['properties']
    if props.get('RouteNo') == 'E04':
        d = props.get('Direction')
        # [lon, lat] -> [lat, lon]
        bm_shapes[d] = [(pt[1], pt[0]) for pt in feat['geometry']['coordinates']]

conn = sqlite3.connect('data/hanoi_bus_system.db')
c = conn.cursor()

# TimBus endpoints
for d in ['go', 're']:
    c.execute("SELECT lat, lon FROM timbus_shape_master WHERE route_code = 'E04' AND direction = ? ORDER BY point_order", (d,))
    pts = c.fetchall()
    print(f"TimBus E04 {d:<2}: start={pts[0]}, end={pts[-1]}")

for d, poly in bm_shapes.items():
    print(f"BusMap E04 Dir {d}: start={poly[0]}, end={poly[-1]}")

# Test pings for direction 1 (in vehicle_unique_pings, direction = 1) vs direction -1
for ping_dir, dir_label in [(1, 'Pings 1 (go)'), (-1, 'Pings -1 (re)')]:
    c.execute("SELECT lat, lon FROM vehicle_unique_pings WHERE route_id = 101109 AND direction = ?", (ping_dir,))
    pings = c.fetchall()
    sample_pings = pings[::max(1, len(pings)//300)]
    print(f"\n--- Testing {dir_label} ({len(pings)} pings) ---")
    for bm_dir in [0, 1]:
        poly = bm_shapes[bm_dir]
        dists = [min_dist(lat, lon, poly) for lat, lon in sample_pings]
        dists.sort()
        in_30 = sum(1 for d in dists if d <= 30.0) / len(dists) * 100
        med = dists[len(dists)//2]
        print(f"  vs BusMap Dir {bm_dir}: in-lane={in_30:.1f}%, median={med:.1f}m, P90={dists[int(len(dists)*0.9)]:.1f}m")
