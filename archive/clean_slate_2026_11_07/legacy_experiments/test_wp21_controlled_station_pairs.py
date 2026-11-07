"""
Station-pair-controlled empirical test:
Comparing the SAME station pairs on Route 02:
Speed during active incident vs Speed during normal hours on the exact same road segment.
"""
import sqlite3
import json
import glob
import math
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

def run_controlled_test():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    # 1. Load Route 02 shape vertices
    cur.execute("SELECT direction, point_order, lat, lon, cum_distance_m FROM canonical_shape_master WHERE route_code = '02' ORDER BY direction, point_order")
    route_shapes = {'go': [], 're': []}
    for r in cur.fetchall():
        route_shapes[r[0]].append((r[2], r[3], r[4]))
        
    # 2. Load Route 02 stations
    cur.execute("SELECT direction, station_order, station_name, cum_distance_m FROM canonical_station_master WHERE route_code = '02' ORDER BY direction, station_order")
    route_stations = {'go': [], 're': []}
    for r in cur.fetchall():
        route_stations[r[0]].append((r[1], r[2], r[3]))
        
    # 3. Load 2026-10-15 incidents
    inc_files = sorted(glob.glob("data/temp_hf_sync/raw_data/2026-10-15/incidents/*.jsonl"))
    incidents = {}
    for fpath in inc_files:
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
                        "icon_category": r.get("icon_category"),
                        "magnitude_of_delay": r.get("magnitude_of_delay", 0),
                        "delay_seconds": r.get("delay_seconds") or 0,
                        "coordinates": r.get("coordinates", [])
                    }
                else:
                    if epoch < incidents[inc_id]["first_epoch"]: incidents[inc_id]["first_epoch"] = epoch
                    if epoch > incidents[inc_id]["last_epoch"]: incidents[inc_id]["last_epoch"] = epoch
                    if r.get("delay_seconds"): incidents[inc_id]["delay_seconds"] = max(incidents[inc_id]["delay_seconds"], r["delay_seconds"])
                    
    # Project incidents & map to station pairs
    # List of (direction, from_order, to_order, t_start, t_end, delay_sec, magnitude)
    pair_incidents = []
    
    for inc_id, inc in incidents.items():
        coords = inc["coordinates"]
        if not coords or len(coords) < 2: continue
        inc_lons = [c[0] for c in coords]
        inc_lats = [c[1] for c in coords]
        
        for direction in ['go', 're']:
            shapes = route_shapes[direction]
            r_lats = [s[0] for s in shapes]
            r_lons = [s[1] for s in shapes]
            if (max(inc_lats) < min(r_lats) - 0.002 or min(inc_lats) > max(r_lats) + 0.002 or
                max(inc_lons) < min(r_lons) - 0.002 or min(inc_lons) > max(r_lons) + 0.002):
                continue
                
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
                
            # Direction check
            inc_dx = (coords[-1][0] - coords[0][0]) * 111320.0 * math.cos(math.radians(coords[0][1]))
            inc_dy = (coords[-1][1] - coords[0][1]) * 110540.0
            mid_vec = pt_projections[len(pt_projections)//2][2]
            dot = inc_dx * mid_vec[0] + inc_dy * mid_vec[1]
            if dot <= 0: continue
            
            s_min = min(p[1] for p in pt_projections)
            s_max = max(p[1] for p in pt_projections)
            t_start = inc["first_epoch"] - 300
            t_end = inc["last_epoch"] + 900
            
            stns = route_stations[direction]
            for k in range(len(stns) - 1):
                s_from = stns[k][2]
                s_to = stns[k+1][2]
                if max(s_min, s_from) < min(s_max, s_to):
                    pair_incidents.append({
                        "direction": direction,
                        "from_order": stns[k][0],
                        "to_order": stns[k+1][0],
                        "from_name": stns[k][1],
                        "to_name": stns[k+1][1],
                        "s_from": s_from,
                        "s_to": s_to,
                        "t_start": t_start,
                        "t_end": t_end,
                        "delay_sec": inc["delay_seconds"],
                        "magnitude": inc["magnitude_of_delay"]
                    })
                    
    print(f"Total station-pair incident intervals: {len(pair_incidents)}")
    
    # 4. Check specific station pairs where incidents occurred
    # Group pings by (direction, station_pair)
    # Query pings on 2026-10-15
    cur.execute("""
        SELECT device_epoch, direction, s_bus_m, derived_speed_kmh, is_dwell
        FROM route_projected_telemetry
        WHERE route_code = '02' 
          AND device_update_time LIKE '2026-10-15%'
          AND derived_speed_kmh IS NOT NULL
    """)
    bus_pings = cur.fetchall()
    
    # Analyze pairs with top incident frequency
    # Find stations for each direction
    pair_stats = defaultdict(lambda: {"with_inc_v": [], "without_inc_v": []})
    
    for ping in bus_pings:
        t_epoch, direction, s_m, speed, is_dwell = ping
        stns = route_stations[direction]
        # find station pair
        matched_pair = None
        for k in range(len(stns) - 1):
            if stns[k][2] <= s_m <= stns[k+1][2]:
                matched_pair = (direction, stns[k][0], stns[k+1][0], stns[k][1], stns[k+1][1])
                break
        if not matched_pair:
            continue
            
        # check if active incident on this pair at t_epoch
        has_inc = False
        for inc in pair_incidents:
            if (inc["direction"] == direction and 
                inc["from_order"] == matched_pair[1] and 
                inc["to_order"] == matched_pair[2] and 
                inc["t_start"] <= t_epoch <= inc["t_end"]):
                has_inc = True
                break
                
        pair_key = (matched_pair[0], matched_pair[1], matched_pair[2], matched_pair[3], matched_pair[4])
        if has_inc:
            pair_stats[pair_key]["with_inc_v"].append(speed)
        else:
            pair_stats[pair_key]["without_inc_v"].append(speed)
            
    # Print results for pairs that have BOTH with_inc and without_inc data
    print(f"\n{'Segment (From -> To)':<50} | {'V_normal':<10} | {'V_incident':<10} | {'Speed Change':<12} | {'Samples'}")
    print("-" * 105)
    
    total_normal_v = []
    total_incident_v = []
    
    for (direction, o_from, o_to, n_from, n_to), stat in sorted(pair_stats.items(), key=lambda x: len(x[1]['with_inc_v']), reverse=True):
        n_inc = len(stat["with_inc_v"])
        n_norm = len(stat["without_inc_v"])
        if n_inc >= 10 and n_norm >= 10:
            avg_norm = sum(stat["without_inc_v"]) / n_norm
            avg_inc = sum(stat["with_inc_v"]) / n_inc
            diff_pct = (avg_inc - avg_norm) / avg_norm * 100
            name_str = f"[{direction}] {n_from[:18]} -> {n_to[:18]}"
            print(f"{name_str:<50} | {avg_norm:>8.2f} km/h | {avg_inc:>8.2f} km/h | {diff_pct:>+10.1f}% | {n_inc} inc / {n_norm} norm")
            total_normal_v.extend(stat["without_inc_v"])
            total_incident_v.extend(stat["with_inc_v"])
            
    if total_incident_v and total_normal_v:
        ovr_norm = sum(total_normal_v) / len(total_normal_v)
        ovr_inc = sum(total_incident_v) / len(total_incident_v)
        ovr_diff = (ovr_inc - ovr_norm) / ovr_norm * 100
        print("-" * 105)
        print(f"{'OVERALL SAME-SEGMENT CONTROLLED COMPARISON':<50} | {ovr_norm:>8.2f} km/h | {ovr_inc:>8.2f} km/h | {ovr_diff:>+10.1f}% | {len(total_incident_v)} inc / {len(total_normal_v)} norm")

    conn.close()

if __name__ == "__main__":
    run_controlled_test()

