"""
Quick verification of station-pair interval union and binary search lookup for Route 02.
"""
import sqlite3
import bisect
import time

DB_PATH = "data/hanoi_bus_system.db"

def test_route_cross_val():
    t0 = time.time()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    # 1. Stations for Route 02
    cur.execute("""
        SELECT direction, station_order, station_name, cum_distance_m 
        FROM canonical_station_master 
        WHERE route_code = '02' 
        ORDER BY direction, station_order
    """)
    route_stations = {'go': [], 're': []}
    for r in cur.fetchall():
        route_stations[r[0]].append((r[1], r[2], r[3]))
        
    # 2. Incidents on Route 02
    cur.execute("""
        SELECT direction, from_station_order, to_station_order, t_start_epoch, t_end_epoch, incident_id
        FROM fact_route_tomtom_incidents
        WHERE route_code = '02'
    """)
    raw_incs = cur.fetchall()
    print(f"Loaded {len(raw_incs)} incident-pair records for Route 02 in {time.time()-t0:.2f}s")
    
    # Build merged disjoint intervals per (direction, from_order, to_order)
    pair_intervals = {}
    pair_incident_ids = {}
    for r in raw_incs:
        key = (r[0], r[1], r[2])
        if key not in pair_intervals:
            pair_intervals[key] = []
            pair_incident_ids[key] = set()
        pair_intervals[key].append((r[3], r[4]))
        pair_incident_ids[key].add(r[5])
        
    # Merge overlapping intervals
    merged_windows = {}
    for key, intervals in pair_intervals.items():
        intervals.sort(key=lambda x: x[0])
        merged = []
        for start, end in intervals:
            if not merged or start > merged[-1][1]:
                merged.append([start, end])
            else:
                merged[-1][1] = max(merged[-1][1], end)
        merged_windows[key] = [(w[0], w[1]) for w in merged]
        
    # 3. Query all pings for Route 02
    t1 = time.time()
    cur.execute("""
        SELECT device_epoch, direction, s_bus_m, derived_speed_kmh, is_dwell
        FROM route_projected_telemetry
        WHERE route_code = '02' AND derived_speed_kmh IS NOT NULL
    """)
    pings = cur.fetchall()
    print(f"Loaded {len(pings):,} pings for Route 02 in {time.time()-t1:.2f}s")
    
    # 4. Station boundaries
    stn_bounds = {}
    for direction in ['go', 're']:
        stns = route_stations[direction]
        stn_bounds[direction] = []
        for k in range(len(stns) - 1):
            stn_bounds[direction].append((stns[k][2], stns[k+1][2], stns[k][0], stns[k+1][0], stns[k][1], stns[k+1][1]))
            
    # 5. Process pings
    t2 = time.time()
    stats = {}
    for b in stn_bounds['go'] + stn_bounds['re']:
        pass
        
    for ping in pings:
        epoch, direction, s_m, speed, is_dwell = ping
        # Find station pair
        bounds = stn_bounds.get(direction, [])
        matched_pair = None
        for s_from, s_to, o_from, o_to, n_from, n_to in bounds:
            if s_from <= s_m <= s_to:
                matched_pair = (direction, o_from, o_to)
                break
        if not matched_pair:
            continue
            
        key = matched_pair
        if key not in stats:
            stats[key] = {"v_inc": [], "v_norm": [], "dwell_inc": 0, "dwell_norm": 0}
            
        # Check if epoch is in any merged window
        windows = merged_windows.get(key, [])
        # Binary search
        has_inc = False
        if windows:
            # find index of first window where end >= epoch
            idx = bisect.bisect_left(windows, (epoch, -1))
            # check idx and idx-1
            for check_i in [idx-1, idx]:
                if 0 <= check_i < len(windows):
                    w_start, w_end = windows[check_i]
                    if w_start <= epoch <= w_end:
                        has_inc = True
                        break
                        
        if has_inc:
            stats[key]["v_inc"].append(speed)
            if is_dwell: stats[key]["dwell_inc"] += 1
        else:
            stats[key]["v_norm"].append(speed)
            if is_dwell: stats[key]["dwell_norm"] += 1
            
    print(f"Aggregation finished in {time.time()-t2:.2f}s!")
    print(f"Total station pairs evaluated: {len(stats)}")
    
    # Sample 3 pairs
    for k, v in list(stats.items())[:3]:
        n_inc = len(v["v_inc"])
        n_norm = len(v["v_norm"])
        avg_inc = sum(v["v_inc"])/n_inc if n_inc else 0
        avg_norm = sum(v["v_norm"])/n_norm if n_norm else 0
        print(f"  Pair {k}: inc_pings={n_inc} (v={avg_inc:.1f}), norm_pings={n_norm} (v={avg_norm:.1f})")

    conn.close()

if __name__ == "__main__":
    test_route_cross_val()

