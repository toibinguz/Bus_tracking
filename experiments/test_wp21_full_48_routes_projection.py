"""
Feasibility & Performance Benchmark:
Projecting 27,195 unique TomTom incidents onto all 48 canonical bus routes.
Evaluates:
- Execution time & memory footprint
- Spatial indexing efficiency (Bounding Box filtering)
- Overlap counts per route
- Directional alignment filter (dot_prod > 0)
"""
import sqlite3
import json
import glob
import math
import time
import sys
from datetime import datetime
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')
DB_PATH = "data/hanoi_bus_system.db"

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def project_point_to_segment(p_lat, p_lon, a_lat, a_lon, b_lat, b_lon, s_a, s_b):
    cos_lat = math.cos(math.radians((a_lat + b_lat) / 2.0))
    dx = (b_lon - a_lon) * 111320.0 * cos_lat
    dy = (b_lat - a_lat) * 110540.0
    seg_len_sq = dx*dx + dy*dy
    if seg_len_sq < 1e-6:
        return haversine(p_lat, p_lon, a_lat, a_lon), s_a, 0.0, (dx, dy)
    px = (p_lon - a_lon) * 111320.0 * cos_lat
    py = (p_lat - a_lat) * 110540.0
    t = (px * dx + py * dy) / seg_len_sq
    t_clamped = max(0.0, min(1.0, t))
    proj_x = t_clamped * dx
    proj_y = t_clamped * dy
    d_perp = math.sqrt((px - proj_x)**2 + (py - proj_y)**2)
    s_proj = s_a + t_clamped * (s_b - s_a)
    return d_perp, s_proj, t, (dx, dy)

def run_benchmark():
    t0 = time.time()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    # Get 48 target routes
    cur.execute("SELECT DISTINCT route_code FROM ml_route_evaluation_summary ORDER BY route_code")
    target_routes = set(r[0] for r in cur.fetchall())
    print(f"Loaded {len(target_routes)} target bus routes.")
    
    # Load canonical shapes for the 48 routes
    cur.execute("""
        SELECT route_code, direction, point_order, lat, lon, cum_distance_m 
        FROM canonical_shape_master 
        WHERE route_code IN ({})
        ORDER BY route_code, direction, point_order
    """.format(','.join(f"'{r}'" for r in target_routes)))
    
    route_shapes = defaultdict(lambda: {'go': [], 're': []})
    for r in cur.fetchall():
        rcode, direction, order, lat, lon, s_m = r
        route_shapes[rcode][direction].append((lat, lon, s_m))
        
    # Precompute Route Bounding Boxes
    route_bboxes = {}
    for rcode, dirs in route_shapes.items():
        for d, pts in dirs.items():
            if pts:
                lats = [p[0] for p in pts]
                lons = [p[1] for p in pts]
                route_bboxes[(rcode, d)] = (min(lats) - 0.001, max(lats) + 0.001, min(lons) - 0.001, max(lons) + 0.001)
                
    print(f"Precomputed bounding boxes for {len(route_bboxes)} route-direction polylines in {time.time()-t0:.2f}s")
    
    # 2. Gather unique incidents across all 22 days
    t1 = time.time()
    files = glob.glob("data/temp_hf_sync/raw_data/*/incidents/*.jsonl")
    incidents = {}
    
    for fpath in files:
        with open(fpath, "r", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                inc_id = r["incident_id"]
                ts = r["timestamp"]
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                epoch = int(dt.timestamp())
                
                if inc_id not in incidents:
                    incidents[inc_id] = {
                        "incident_id": inc_id,
                        "first_epoch": epoch,
                        "last_epoch": epoch,
                        "first_seen": ts,
                        "last_seen": ts,
                        "icon_category": r.get("icon_category"),
                        "magnitude": r.get("magnitude_of_delay", 0),
                        "delay_sec": r.get("delay_seconds") or 0,
                        "length_m": r.get("length_meters", 0),
                        "description": r.get("description", ""),
                        "coordinates": r.get("coordinates", [])
                    }
                else:
                    if epoch < incidents[inc_id]["first_epoch"]:
                        incidents[inc_id]["first_epoch"] = epoch
                        incidents[inc_id]["first_seen"] = ts
                    if epoch > incidents[inc_id]["last_epoch"]:
                        incidents[inc_id]["last_epoch"] = epoch
                        incidents[inc_id]["last_seen"] = ts
                    if r.get("delay_seconds"):
                        incidents[inc_id]["delay_sec"] = max(incidents[inc_id]["delay_sec"], r["delay_seconds"])
                        
    print(f"Loaded and aggregated {len(incidents):,} unique incidents from {len(files)} files in {time.time()-t1:.2f}s")
    
    # 3. Project Incidents using Bounding Box Spatial Indexing
    t2 = time.time()
    total_matches = 0
    aligned_matches = 0
    route_match_counts = Counter()
    
    for inc_id, inc in incidents.items():
        coords = inc["coordinates"]
        if not coords or len(coords) < 2:
            continue
            
        lons = [c[0] for c in coords]
        lats = [c[1] for c in coords]
        inc_bbox = (min(lats), max(lats), min(lons), max(lons))
        
        # Test candidate route-directions that overlap inc_bbox
        for (rcode, direction), r_bbox in route_bboxes.items():
            if (inc_bbox[1] < r_bbox[0] or inc_bbox[0] > r_bbox[1] or
                inc_bbox[3] < r_bbox[2] or inc_bbox[2] > r_bbox[3]):
                continue  # Skip disjoint bounding box
                
            shapes = route_shapes[rcode][direction]
            n_pts = len(coords)
            indices = [0, n_pts//2, n_pts - 1] if n_pts > 4 else range(n_pts)
            test_pts = [coords[i] for i in indices]
            
            pt_projections = []
            for pt in test_pts:
                p_lon, p_lat = pt[0], pt[1]
                min_d = float('inf')
                best_s = 0.0
                best_vec = (0, 0)
                for i in range(len(shapes) - 1):
                    a_lat, a_lon, s_a = shapes[i]
                    b_lat, b_lon, s_b = shapes[i+1]
                    if not (min(a_lat, b_lat)-0.001 <= p_lat <= max(a_lat, b_lat)+0.001 and
                            min(a_lon, b_lon)-0.001 <= p_lon <= max(a_lon, b_lon)+0.001):
                        continue
                    d, s, t, s_vec = project_point_to_segment(p_lat, p_lon, a_lat, a_lon, b_lat, b_lon, s_a, s_b)
                    if d < min_d:
                        min_d = d
                        best_s = s
                        best_vec = s_vec
                pt_projections.append((min_d, best_s, best_vec))
                
            distances = [p[0] for p in pt_projections if p[0] != float('inf')]
            if not distances or sum(distances)/len(distances) > 45.0 or min(distances) > 30.0:
                continue
                
            total_matches += 1
            
            # Direction check
            inc_dx = (coords[-1][0] - coords[0][0]) * 111320.0 * math.cos(math.radians(coords[0][1]))
            inc_dy = (coords[-1][1] - coords[0][1]) * 110540.0
            mid_vec = pt_projections[len(pt_projections)//2][2]
            dot = inc_dx * mid_vec[0] + inc_dy * mid_vec[1]
            if dot > 0:
                aligned_matches += 1
                route_match_counts[rcode] += 1
                
    elapsed = time.time() - t2
    print(f"\nProjection completed in {elapsed:.2f} seconds ({len(incidents)/elapsed:.1f} incidents/sec)!")
    print(f"Total spatial intersections (d_perp <= 45m): {total_matches:,}")
    print(f"Directionally aligned intersections (dot_prod > 0): {aligned_matches:,} ({aligned_matches/total_matches*100:.1f}%)")
    print(f"Routes with at least one matched incident: {len(route_match_counts)} / 48")
    
    print("\nTop 10 routes with most TomTom incidents:")
    for rcode, cnt in route_match_counts.most_common(10):
        print(f"  Route {rcode:>5}: {cnt:>5} aligned incidents")
        
    conn.close()

if __name__ == "__main__":
    from collections import Counter
    run_benchmark()

