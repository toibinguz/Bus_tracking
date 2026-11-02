"""
Empirical test of TomTom incident projection onto Bus Route 02.
Measures:
1. Coordinate projection accuracy and distance threshold (d_perp <= 50m)
2. Direction alignment (cos_theta > 0)
3. Station pair mapping: [s_min, s_max] -> (station_k, station_k+1)
4. Cross-correlation: Bus speed / travel time during incident vs baseline.
"""
import sqlite3
import json
import glob
import math
from datetime import datetime

DB_PATH = "data/hanoi_bus_system.db"

# Haversine distance between two points in meters
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

# Project point P(lat, lon) onto segment A-B, returning (d_perp, s_proj, t_param)
def project_point_to_segment(p_lat, p_lon, a_lat, a_lon, b_lat, b_lon, s_a, s_b):
    # Local equirectangular approximation for high speed
    # lat_mid = (a_lat + b_lat)/2
    cos_lat = math.cos(math.radians((a_lat + b_lat) / 2.0))
    # Vector AB in meters
    dx = (b_lon - a_lon) * 111320.0 * cos_lat
    dy = (b_lat - a_lat) * 110540.0
    seg_len_sq = dx*dx + dy*dy
    if seg_len_sq < 1e-6:
        d = haversine(p_lat, p_lon, a_lat, a_lon)
        return d, s_a, 0.0, (dx, dy)
    
    # Vector AP
    px = (p_lon - a_lon) * 111320.0 * cos_lat
    py = (p_lat - a_lat) * 110540.0
    
    # Projection parameter t
    t = (px * dx + py * dy) / seg_len_sq
    t_clamped = max(0.0, min(1.0, t))
    
    # Projected point coords
    proj_x = t_clamped * dx
    proj_y = t_clamped * dy
    d_perp = math.sqrt((px - proj_x)**2 + (py - proj_y)**2)
    s_proj = s_a + t_clamped * (s_b - s_a)
    
    return d_perp, s_proj, t, (dx, dy)

def run_test():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    # 1. Load Route 02 shape vertices
    cur.execute("""
        SELECT direction, point_order, lat, lon, cum_distance_m 
        FROM canonical_shape_master 
        WHERE route_code = '02' 
        ORDER BY direction, point_order
    """)
    shape_rows = cur.fetchall()
    
    route_shapes = {'go': [], 're': []}
    for r in shape_rows:
        direction, order, lat, lon, s_m = r
        route_shapes[direction].append((lat, lon, s_m))
        
    print(f"Loaded Route 02 shape: go={len(route_shapes['go'])} pts, re={len(route_shapes['re'])} pts")
    
    # 2. Load Route 02 stations
    cur.execute("""
        SELECT direction, station_order, station_name, cum_distance_m 
        FROM canonical_station_master 
        WHERE route_code = '02' 
        ORDER BY direction, station_order
    """)
    station_rows = cur.fetchall()
    route_stations = {'go': [], 're': []}
    for r in station_rows:
        direction, order, name, s_m = r
        route_stations[direction].append((order, name, s_m))
    print(f"Loaded Route 02 stations: go={len(route_stations['go'])} stns, re={len(route_stations['re'])} stns")
    
    # 3. Test on one day of incidents: 2026-10-15
    inc_files = sorted(glob.glob("data/temp_hf_sync/raw_data/2026-10-15/incidents/*.jsonl"))
    print(f"Testing on 2026-10-15 ({len(inc_files)} batch files)...")
    
    # Gather unique incidents for 2026-10-15
    incidents = {}
    for fpath in inc_files:
        with open(fpath, "r", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                inc_id = r["incident_id"]
                ts = r["timestamp"]
                if inc_id not in incidents:
                    incidents[inc_id] = {
                        "incident_id": inc_id,
                        "first_seen": ts,
                        "last_seen": ts,
                        "count": 1,
                        "icon_category": r.get("icon_category"),
                        "magnitude_of_delay": r.get("magnitude_of_delay"),
                        "delay_seconds": r.get("delay_seconds"),
                        "length_meters": r.get("length_meters"),
                        "description": r.get("description"),
                        "coordinates": r.get("coordinates", [])
                    }
                else:
                    incidents[inc_id]["last_seen"] = ts
                    incidents[inc_id]["count"] += 1
                    if r.get("delay_seconds") is not None:
                        incidents[inc_id]["delay_seconds"] = r.get("delay_seconds")
                        
    print(f"Total unique incidents on 2026-10-15: {len(incidents)}")
    
    # 4. Project incidents onto Route 02 (both 'go' and 're')
    matched_incidents = []
    
    for inc_id, inc in incidents.items():
        coords = inc["coordinates"]
        if not coords or len(coords) < 2:
            continue
            
        # Incident bounding box
        inc_lons = [c[0] for c in coords]
        inc_lats = [c[1] for c in coords]
        inc_min_lon, inc_max_lon = min(inc_lons), max(inc_lons)
        inc_min_lat, inc_max_lat = min(inc_lats), max(inc_lats)
        
        for direction in ['go', 're']:
            shapes = route_shapes[direction]
            # Check route bounding box overlap first (with 100m margin ~ 0.001 deg)
            r_lats = [s[0] for s in shapes]
            r_lons = [s[1] for s in shapes]
            if (inc_max_lat < min(r_lats) - 0.002 or inc_min_lat > max(r_lats) + 0.002 or
                inc_max_lon < min(r_lons) - 0.002 or inc_min_lon > max(r_lons) + 0.002):
                continue
                
            # Sample points along incident: start, middle, end + any intermediate
            # If length <= 4, test all. Else test start, mid, end, plus 1/4 and 3/4
            test_pts = []
            n_pts = len(coords)
            if n_pts <= 5:
                test_pts = coords
            else:
                indices = [0, n_pts//4, n_pts//2, (3*n_pts)//4, n_pts - 1]
                test_pts = [coords[i] for i in indices]
                
            # Find projection of each point onto route shape
            pt_projections = []
            for pt in test_pts:
                p_lon, p_lat = pt[0], pt[1]
                min_d = float('inf')
                best_s = 0.0
                best_seg_vec = (0, 0)
                
                for i in range(len(shapes) - 1):
                    a_lat, a_lon, s_a = shapes[i]
                    b_lat, b_lon, s_b = shapes[i+1]
                    
                    # Quick bounding box check for segment
                    seg_min_lat = min(a_lat, b_lat) - 0.001
                    seg_max_lat = max(a_lat, b_lat) + 0.001
                    seg_min_lon = min(a_lon, b_lon) - 0.001
                    seg_max_lon = max(a_lon, b_lon) + 0.001
                    if not (seg_min_lat <= p_lat <= seg_max_lat and seg_min_lon <= p_lon <= seg_max_lon):
                        continue
                        
                    d, s, t, seg_vec = project_point_to_segment(p_lat, p_lon, a_lat, a_lon, b_lat, b_lon, s_a, s_b)
                    if d < min_d:
                        min_d = d
                        best_s = s
                        best_seg_vec = seg_vec
                        
                pt_projections.append((min_d, best_s, best_seg_vec))
                
            # Check if incident is close to route: average d_perp <= 50m and min_d <= 35m
            distances = [p[0] for p in pt_projections if p[0] != float('inf')]
            if not distances:
                continue
            avg_d = sum(distances) / len(distances)
            min_d = min(distances)
            
            if avg_d <= 50.0 and min_d <= 35.0:
                s_values = [p[1] for p in pt_projections]
                s_min_inc = min(s_values)
                s_max_inc = max(s_values)
                overlap_m = s_max_inc - s_min_inc
                
                # Check vector direction alignment
                # Incident vector from start point to end point
                inc_dx = (coords[-1][0] - coords[0][0]) * 111320.0 * math.cos(math.radians(coords[0][1]))
                inc_dy = (coords[-1][1] - coords[0][1]) * 110540.0
                
                # Shape direction vector near the middle point
                mid_vec = pt_projections[len(pt_projections)//2][2]
                dot_prod = inc_dx * mid_vec[0] + inc_dy * mid_vec[1]
                
                # Map to station pairs
                stns = route_stations[direction]
                covered_station_pairs = []
                for k in range(len(stns) - 1):
                    s_from = stns[k][2]
                    s_to = stns[k+1][2]
                    # Check overlap between [s_min_inc, s_max_inc] and [s_from, s_to]
                    if max(s_min_inc, s_from) < min(s_max_inc, s_to):
                        covered_station_pairs.append((stns[k][0], stns[k][1], stns[k+1][0], stns[k+1][1]))
                        
                matched_incidents.append({
                    "incident_id": inc_id,
                    "direction": direction,
                    "avg_d_perp": round(avg_d, 1),
                    "s_min": round(s_min_inc, 1),
                    "s_max": round(s_max_inc, 1),
                    "overlap_m": round(overlap_m, 1),
                    "dot_prod": round(dot_prod, 1),
                    "is_same_direction": dot_prod > 0,
                    "first_seen": inc["first_seen"],
                    "last_seen": inc["last_seen"],
                    "category": inc["icon_category"],
                    "delay_sec": inc["delay_seconds"],
                    "magnitude": inc["magnitude_of_delay"],
                    "desc": inc["description"],
                    "num_pairs": len(covered_station_pairs),
                    "pairs": covered_station_pairs
                })
                
    print(f"\nTotal matched incident segments on Route 02: {len(matched_incidents)}")
    same_dir_count = sum(1 for m in matched_incidents if m["is_same_direction"])
    opp_dir_count = len(matched_incidents) - same_dir_count
    print(f"Same direction (aligned): {same_dir_count}, Opposite direction: {opp_dir_count}")
    
    print("\nSample 5 matched incidents on Route 02:")
    for m in matched_incidents[:5]:
        print(f"  - [{m['direction']}] {m['incident_id'][:25]}... | d_perp={m['avg_d_perp']}m | s=[{m['s_min']}-{m['s_max']}]m | overlap={m['overlap_m']}m | aligned={m['is_same_direction']} | delay={m['delay_sec']}s | pairs={m['num_pairs']}")
        if m['pairs']:
            print(f"    Pairs: {m['pairs'][0][1]} -> {m['pairs'][0][3]}")

if __name__ == "__main__":
    run_test()

