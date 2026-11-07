"""
Test projection pipeline with canonical shape and station-guided direction
"""
import sqlite3
import time

from module_1_data_ingestion_and_preprocessing.step_1_4_frenet_spatial_projection.multi_route_projector import (
    project_points_to_shape
)

conn = sqlite3.connect('data/hanoi_bus_system.db')
cur = conn.cursor()

# Station directions lookup
cur.execute("SELECT route_id, station_id, direction FROM canonical_station_master")
st_dir = {(r_id, st_id): d for r_id, st_id, d in cur.fetchall()}

# Routes with pings
cur.execute("""
    SELECT DISTINCT r.route_id, r.route_code, count(t.ping_id) as pings
    FROM canonical_route_master r
    JOIN vehicle_unique_pings t ON r.route_id = t.route_id
    GROUP BY r.route_id, r.route_code
    ORDER BY pings DESC
    LIMIT 8;
""")
sample_routes = cur.fetchall()

print(f"{'ROUTE':<8} | {'PINGS':<10} | {'IN-LANE (<=30m)':<16} | {'MEDIAN d_perp':<14} | {'ELAPSED'}")
print("-" * 65)

for r_id, r_code, p_cnt in sample_routes:
    t0 = time.time()
    shapes = {"go": [], "re": []}
    for row in cur.execute("""
        SELECT direction, point_order, lat, lon, cum_distance_m 
        FROM canonical_shape_master 
        WHERE route_id = ? 
        ORDER BY direction, point_order
    """, (r_id,)).fetchall():
        shapes[row[0].lower()].append((row[1], row[2], row[3], row[4]))

    cur.execute("""
        SELECT ping_id, vehicle_id, plate, device_update_time, device_epoch, direction, lat, lon, current_station_id
        FROM vehicle_unique_pings
        WHERE route_id = ? AND lat > 20.0 AND lon > 105.0
        ORDER BY vehicle_id, device_epoch;
    """, (r_id,))
    pings = cur.fetchall()

    pings_by_dir = {"go": [], "re": []}
    for p in pings:
        st_id = p[8]
        if st_id and (r_id, st_id) in st_dir:
            d_str = st_dir[(r_id, st_id)]
        else:
            d_str = "re" if p[5] == 1 else "go"
        pings_by_dir[d_str].append((p[0], p[6], p[7], p[4]))

    all_dperps = []
    for d_str in ["go", "re"]:
        if shapes[d_str] and pings_by_dir[d_str]:
            res = project_points_to_shape(pings_by_dir[d_str], shapes[d_str])
            all_dperps.extend([r[2] for r in res])

    all_dperps.sort()
    in_30 = sum(1 for d in all_dperps if d <= 30.0) / len(all_dperps) * 100
    med_d = all_dperps[len(all_dperps)//2]
    elapsed = time.time() - t0

    print(f"{r_code:<8} | {p_cnt:<10,d} | {in_30:>14.1f}% | {med_d:>11.1f}m | {elapsed:.2f}s")

