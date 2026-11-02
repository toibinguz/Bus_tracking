"""
Cross-validation of TomTom Incidents vs Bus Kinematics on Route 02 (2026-10-15).
Compares:
1. Bus derived speed and dwell time on segments WITH incident vs WITHOUT incident.
2. Bus travel time ratio (actual_time / baseline_median).
"""
import sqlite3
import json
import glob
import math
import sys
from datetime import datetime, timezone, timedelta

# Ensure UTF-8 output
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
        d = haversine(p_lat, p_lon, a_lat, a_lon)
        return d, s_a, 0.0, (dx, dy)
    
    px = (p_lon - a_lon) * 111320.0 * cos_lat
    py = (p_lat - a_lat) * 110540.0
    
    t = (px * dx + py * dy) / seg_len_sq
    t_clamped = max(0.0, min(1.0, t))
    
    proj_x = t_clamped * dx
    proj_y = t_clamped * dy
    d_perp = math.sqrt((px - proj_x)**2 + (py - proj_y)**2)
    s_proj = s_a + t_clamped * (s_b - s_a)
    return d_perp, s_proj, t, (dx, dy)

def run_cross_val():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    # 1. Load Route 02 shape vertices
    cur.execute("""
        SELECT direction, point_order, lat, lon, cum_distance_m 
        FROM canonical_shape_master 
        WHERE route_code = '02' 
        ORDER BY direction, point_order
    """)
    route_shapes = {'go': [], 're': []}
    for r in cur.fetchall():
        route_shapes[r[0]].append((r[2], r[3], r[4]))
        
    # 2. Load Route 02 stations
    cur.execute("""
        SELECT direction, station_order, station_name, cum_distance_m 
        FROM canonical_station_master 
        WHERE route_code = '02' 
        ORDER BY direction, station_order
    """)
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
                # Convert ISO timestamp to epoch seconds
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
                        "magnitude_of_delay": r.get("magnitude_of_delay", 0),
                        "delay_seconds": r.get("delay_seconds") or 0,
                        "length_meters": r.get("length_meters", 0),
                        "coordinates": r.get("coordinates", [])
                    }
                else:
                    if epoch < incidents[inc_id]["first_epoch"]:
                        incidents[inc_id]["first_epoch"] = epoch
                    if epoch > incidents[inc_id]["last_epoch"]:
                        incidents[inc_id]["last_epoch"] = epoch
                        incidents[inc_id]["last_seen"] = ts
                    if r.get("delay_seconds"):
                        incidents[inc_id]["delay_seconds"] = max(incidents[inc_id]["delay_seconds"], r["delay_seconds"])
                        
    # Project incidents
    active_route_incidents = []
    for inc_id, inc in incidents.items():
        coords = inc["coordinates"]
        if not coords or len(coords) < 2:
            continue
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
            if dot <= 0:  # Opposite direction, skip!
                continue
                
            s_min = min(p[1] for p in pt_projections)
            s_max = max(p[1] for p in pt_projections)
            
            # Pad valid window by 15 min buffer (900s)
            t_start = inc["first_epoch"] - 300
            t_end = inc["last_epoch"] + 900
            
            active_route_incidents.append({
                "direction": direction,
                "s_min": s_min,
                "s_max": s_max,
                "t_start": t_start,
                "t_end": t_end,
                "delay_sec": inc["delay_seconds"],
                "magnitude": inc["magnitude_of_delay"],
                "category": inc["icon_category"]
            })
            
    print(f"Total directional active incident periods on Route 02 (2026-10-15): {len(active_route_incidents)}")
    
    # 4. Query Bus Pings on Route 02 for 2026-10-15
    print("Querying bus pings on Route 02 for 2026-10-15...")
    cur.execute("""
        SELECT device_epoch, direction, s_bus_m, derived_speed_kmh, is_dwell
        FROM route_projected_telemetry
        WHERE route_code = '02' 
          AND device_update_time LIKE '2026-10-15%'
          AND derived_speed_kmh IS NOT NULL
    """)
    bus_pings = cur.fetchall()
    print(f"Total bus pings on 2026-10-15: {len(bus_pings):,}")
    
    # Classify each ping as WITH INCIDENT vs WITHOUT INCIDENT
    with_inc_speeds = []
    without_inc_speeds = []
    with_inc_dwell = 0
    without_inc_dwell = 0
    
    for ping in bus_pings:
        t_epoch, direction, s_m, speed, is_dwell = ping
        # Check if any active incident covers this ping
        has_inc = False
        for inc in active_route_incidents:
            if inc["direction"] == direction and inc["t_start"] <= t_epoch <= inc["t_end"]:
                if inc["s_min"] - 50.0 <= s_m <= inc["s_max"] + 50.0:
                    has_inc = True
                    break
                    
        if has_inc:
            with_inc_speeds.append(speed)
            if is_dwell:
                with_inc_dwell += 1
        else:
            without_inc_speeds.append(speed)
            if is_dwell:
                without_inc_dwell += 1
                
    n_with = len(with_inc_speeds)
    n_without = len(without_inc_speeds)
    print(f"\nPings with active TomTom Incident: {n_with:,} ({n_with/(n_with+n_without)*100:.2f}%)")
    print(f"Pings without active TomTom Incident: {n_without:,} ({n_without/(n_with+n_without)*100:.2f}%)")
    
    if n_with > 0:
        avg_v_with = sum(with_inc_speeds) / n_with
        dwell_pct_with = (with_inc_dwell / n_with) * 100
        print(f"--- RESULTS WITH INCIDENT ---")
        print(f"Average derived speed: {avg_v_with:.2f} km/h")
        print(f"Dwell percentage: {dwell_pct_with:.2f}%")
        
    if n_without > 0:
        avg_v_without = sum(without_inc_speeds) / n_without
        dwell_pct_without = (without_inc_dwell / n_without) * 100
        print(f"--- RESULTS WITHOUT INCIDENT ---")
        print(f"Average derived speed: {avg_v_without:.2f} km/h")
        print(f"Dwell percentage: {dwell_pct_without:.2f}%")
        
    if n_with > 0 and n_without > 0:
        speed_drop = (avg_v_without - avg_v_with) / avg_v_without * 100
        print(f"\n>>> EMPIRICAL FINDING: TomTom Incident causes a {speed_drop:.1f}% reduction in bus speed! <<<")
        print(f">>> Dwell rate jumps from {dwell_pct_without:.1f}% to {dwell_pct_with:.1f}%! <<<")

    conn.close()

if __name__ == "__main__":
    run_cross_val()

