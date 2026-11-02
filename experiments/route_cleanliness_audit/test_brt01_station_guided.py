"""
Test station-guided projection on BRT01
"""
import sqlite3
from module_1_data_ingestion_and_preprocessing.step_1_4_frenet_spatial_projection.multi_route_projector import (
    project_points_to_shape
)

conn = sqlite3.connect('data/hanoi_bus_system.db')
cur = conn.cursor()

# Station directions
cur.execute("SELECT route_id, station_id, direction FROM canonical_station_master WHERE route_code = 'BRT01'")
st_dir = {st_id: d for r_id, st_id, d in cur.fetchall()}

# Shape
shapes = {"go": [], "re": []}
for row in cur.execute("SELECT direction, point_order, lat, lon, cum_distance_m FROM canonical_shape_master WHERE route_code = 'BRT01' ORDER BY direction, point_order").fetchall():
    shapes[row[0].lower()].append((row[1], row[2], row[3], row[4]))

# Pings
cur.execute("""
    SELECT ping_id, vehicle_id, plate, device_update_time, device_epoch, direction, lat, lon, current_station_id
    FROM vehicle_unique_pings
    WHERE route_id = 918 AND lat > 20.0 AND lon > 105.0
    ORDER BY vehicle_id, device_epoch;
""")
pings = cur.fetchall()

pings_by_dir = {"go": [], "re": []}
for p in pings:
    st_id = p[8]
    if st_id and st_id in st_dir:
        d_str = st_dir[st_id]
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
in_15 = sum(1 for d in all_dperps if d <= 15.0) / len(all_dperps) * 100
med_d = all_dperps[len(all_dperps)//2]
p90_d = all_dperps[int(len(all_dperps)*0.9)]

print(f"BRT01 Station-Guided Projection ({len(pings):,} pings):")
print(f"  In-lane (<=30m): {in_30:.1f}%, In-lane (<=15m): {in_15:.1f}%")
print(f"  Median d_perp: {med_d:.1f}m, P90 d_perp: {p90_d:.1f}m")

