"""
Route 02 Linear Referencing (Frenet Frame Projection) & Spatial Re-evaluation
Computes:
1. Along-track distance (s) and Cross-track error (d_perp / vi sai tam duong)
2. Derived velocity (v = delta_s / delta_t)
3. Station dwell event detection (delta_s < 15m, delta_t >= 20s - strictly no raw speed == 0)
4. Empirical re-evaluation of station positions vs physical dwell locations
5. Corridor-by-corridor centerline fit analysis
"""

import math
import os
import sqlite3
import sys
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")

DB_PATH = "data/telemetry_audit_2026_10_17_18.db"
EARTH_RADIUS_M = 6371000.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * (math.sin(d_lambda / 2.0) ** 2)
    return EARTH_RADIUS_M * 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def project_point_to_polyline(lat: float, lon: float, polyline_pts: list) -> tuple:
    """
    Project point onto 2D polyline using equirectangular projection approximation for local segment.
    polyline_pts: list of (order, lat, lon, cum_dist_m)
    Returns: (best_cum_dist_m, min_cross_track_m, best_proj_lat, best_proj_lon, segment_idx)
    """
    p_lat_rad = math.radians(lat)
    cos_lat = math.cos(p_lat_rad)

    min_dist_m = float("inf")
    best_s_m = 0.0
    best_lat = lat
    best_lon = lon
    best_seg = 0

    for i in range(len(polyline_pts) - 1):
        p1 = polyline_pts[i]
        p2 = polyline_pts[i + 1]

        # Convert segment endpoints to local meter offsets relative to (lat, lon)
        dx1 = math.radians(p1[2] - lon) * EARTH_RADIUS_M * cos_lat
        dy1 = math.radians(p1[1] - lat) * EARTH_RADIUS_M

        dx2 = math.radians(p2[2] - lon) * EARTH_RADIUS_M * cos_lat
        dy2 = math.radians(p2[1] - lat) * EARTH_RADIUS_M

        seg_dx = dx2 - dx1
        seg_dy = dy2 - dy1
        seg_len_sq = seg_dx * seg_dx + seg_dy * seg_dy

        if seg_len_sq < 1e-6:
            dist = math.hypot(dx1, dy1)
            t = 0.0
        else:
            # Vector projection of (0,0) - (dx1, dy1) onto segment (seg_dx, seg_dy)
            # t = - (dx1*seg_dx + dy1*seg_dy) / seg_len_sq
            t = -(dx1 * seg_dx + dy1 * seg_dy) / seg_len_sq
            t = max(0.0, min(1.0, t))
            proj_x = dx1 + t * seg_dx
            proj_y = dy1 + t * seg_dy
            dist = math.hypot(proj_x, proj_y)

        if dist < min_dist_m:
            min_dist_m = dist
            seg_len = math.sqrt(seg_len_sq)
            best_s_m = p1[3] + t * seg_len
            best_lat = p1[1] + t * (p2[1] - p1[1])
            best_lon = p2[2] + t * (p2[2] - p1[2])
            best_seg = i

    return best_s_m, min_dist_m, best_lat, best_lon, best_seg


def main():
    print("=" * 70)
    print("BAT DAU CHIEU HOA FRENET & TAI DANH GIA VI TRI TUYEN / TRAM (TUYEN 02)")
    print("=" * 70)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # 1. Load Shapes
    shapes = {"go": [], "re": []}
    for row in cur.execute("SELECT direction, point_order, lat, lon, cum_distance_m FROM timbus_shape_master ORDER BY direction, point_order"):
        shapes[row[0]].append((row[1], row[2], row[3], row[4]))
    print(f"[*] Da nap hinh hoc tim duong: Chieu 'go'={len(shapes['go'])} diem, 're'={len(shapes['re'])} diem")

    # 2. Load Stations
    stations = {"go": {}, "re": {}}
    for row in cur.execute("SELECT direction, station_order, station_id, station_name, lat, lon, cum_distance_m FROM timbus_station_master ORDER BY direction, station_order"):
        stations[row[0]][row[2]] = {
            "order": row[1],
            "id": row[2],
            "name": row[3],
            "lat": row[4],
            "lon": row[5],
            "s_m": row[6]
        }
    print(f"[*] Da nap danh ba tram: Chieu 'go'={len(stations['go'])} tram, 're'={len(stations['re'])} tram")

    # Evaluate Stations' own distance to centerline
    print("\n--- [DANH GIA 1: VI SAI CUA BAN THAN TRAM SO VOI TIM DUONG] ---")
    st_offsets = []
    for d_name in ["go", "re"]:
        for st_id, st in stations[d_name].items():
            s_proj, d_perp, _, _, _ = project_point_to_polyline(st["lat"], st["lon"], shapes[d_name])
            st["d_perp"] = d_perp
            st_offsets.append(d_perp)
    st_offsets = np.array(st_offsets)
    print(f"  Tong so tram danh gia: {len(st_offsets)}")
    print(f"  Do lech ngang trung vi (Median Offset): {np.median(st_offsets):.1f} m")
    print(f"  Do lech ngang trung binh (Mean Offset): {np.mean(st_offsets):.1f} m")
    print(f"  Phan tram tram nam sat tim duong (<= 15m - me duong/via he): {np.mean(st_offsets <= 15.0)*100:.1f}%")
    print(f"  Phan tram tram cach tim duong <= 25m: {np.mean(st_offsets <= 25.0)*100:.1f}%")
    print(f"  Do lech lon nhat (Max Offset): {np.max(st_offsets):.1f} m")

    # 3. Load Route 02 Telemetry
    print("\n--- [DANH GIA 2: CHIEU HOA TOAN BO TELEMETRY GPS TUYEN 02] ---")
    query = """
    SELECT ping_id, vehicle_id, route_id, device_update_time, device_epoch, lat, lon, current_station_id, next_station_id
    FROM vehicle_unique_pings
    WHERE route_id IN ('02', '2')
    ORDER BY vehicle_id, device_epoch
    """
    pings = cur.execute(query).fetchall()
    print(f"[*] Tong so ban tin Telemetry doc nhat cua Tuyen 02: {len(pings):,} pings")

    # Create tables for projection results
    cur.execute("DROP TABLE IF EXISTS route_02_projected_telemetry")
    cur.execute("""
    CREATE TABLE route_02_projected_telemetry (
        ping_id INTEGER PRIMARY KEY,
        fleet_code TEXT,
        timestamp TEXT,
        epoch REAL,
        lat REAL,
        lon REAL,
        direction TEXT,
        current_station_id INTEGER,
        s_bus_m REAL,
        cross_track_m REAL,
        delta_s_m REAL,
        delta_t_s REAL,
        derived_speed_kmh REAL
    )
    """)

    projected_rows = []
    cross_tracks_go = []
    cross_tracks_re = []

    # Vehicle-by-vehicle kinematic tracking
    current_fleet = None
    prev_s = 0.0
    prev_epoch = None
    prev_dir = None

    go_station_ids = set(stations["go"].keys())
    re_station_ids = set(stations["re"].keys())

    for row in pings:
        p_id, fleet, r_id, ts, epoch, lat, lon, curr_st, next_st = row

        # Determine direction based on station ID or fallback to closest shape
        direction = "go"
        if curr_st in re_station_ids and curr_st not in go_station_ids:
            direction = "re"
        elif curr_st in go_station_ids and curr_st not in re_station_ids:
            direction = "go"
        else:
            # Fallback: compare distance to both centerlines
            s_go, d_go, _, _, _ = project_point_to_polyline(lat, lon, shapes["go"])
            s_re, d_re, _, _, _ = project_point_to_polyline(lat, lon, shapes["re"])
            direction = "go" if d_go <= d_re else "re"

        s_m, d_perp_m, _, _, _ = project_point_to_polyline(lat, lon, shapes[direction])

        if direction == "go":
            cross_tracks_go.append(d_perp_m)
        else:
            cross_tracks_re.append(d_perp_m)

        # Kinematic velocity calculation (delta_s / delta_t)
        delta_s = 0.0
        delta_t = 0.0
        derived_speed_kmh = 0.0

        if current_fleet == fleet and prev_dir == direction and prev_epoch is not None:
            delta_t = epoch - prev_epoch
            if 0 < delta_t <= 300: # within 5 minutes
                delta_s = s_m - prev_s
                if delta_s >= 0:
                    derived_speed_kmh = (delta_s / delta_t) * 3.6

        current_fleet = fleet
        prev_s = s_m
        prev_epoch = epoch
        prev_dir = direction

        projected_rows.append((
            p_id, fleet, ts, epoch, lat, lon, direction, curr_st,
            round(s_m, 2), round(d_perp_m, 2), round(delta_s, 2), round(delta_t, 1), round(derived_speed_kmh, 2)
        ))

    cur.executemany("""
    INSERT INTO route_02_projected_telemetry VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, projected_rows)
    conn.commit()
    print(f"[*] Da luu {len(projected_rows):,} ban tin chieu hoa vao 'route_02_projected_telemetry'")

    all_d_perp = np.array(cross_tracks_go + cross_tracks_re)
    print("\n--- [DANH GIA 2: THONG KE VI SAI TAM DUONG CUA XE (CROSS-TRACK)] ---")
    print(f"  Do lech ngang trung vi (Median Cross-Track): {np.median(all_d_perp):.1f} m")
    print(f"  Do lech ngang trung binh (Mean Cross-Track): {np.mean(all_d_perp):.1f} m")
    print(f"  Phan vi 90% (90th percentile): {np.percentile(all_d_perp, 90):.1f} m")
    print(f"  Phan vi 95% (95th percentile): {np.percentile(all_d_perp, 95):.1f} m")
    print(f"  Ty le xe bam sat tim duong <= 15m (Chinh xac lan chay): {np.mean(all_d_perp <= 15.0)*100:.1f}%")
    print(f"  Ty le xe bam sat tim duong <= 25m: {np.mean(all_d_perp <= 25.0)*100:.1f}%")
    print(f"  Ty le nhieu vang GPS bat thuong (> 50m): {np.mean(all_d_perp > 50.0)*100:.2f}%")

    # 4. Station Dwell Events & Spatial Re-evaluation
    print("\n--- [DANH GIA 3: PHAT HIEN DWELL TIME VA DOI SOAT VI TRI TRAM THUC TE] ---")
    # Rule 6 AGENTS.md: delta_s < 15m in delta_t >= 20s
    cur.execute("""
    SELECT fleet_code, direction, current_station_id, epoch, s_bus_m, lat, lon
    FROM route_02_projected_telemetry
    ORDER BY fleet_code, epoch
    """)
    rows = cur.fetchall()

    dwell_events = []
    dwell_group = []
    
    for r in rows:
        if not dwell_group:
            dwell_group.append(r)
            continue
        
        prev = dwell_group[-1]
        dt_sec = r[3] - prev[3]
        ds_m = abs(r[4] - prev[4])

        # Same fleet, same direction, within interval
        if r[0] == prev[0] and r[1] == prev[1] and 0 < dt_sec <= 90 and ds_m < 15.0:
            dwell_group.append(r)
        else:
            # Check if accumulated dwell duration >= 20s
            if len(dwell_group) >= 2:
                total_duration = dwell_group[-1][3] - dwell_group[0][3]
                if total_duration >= 20.0:
                    med_lat = float(np.median([g[5] for g in dwell_group]))
                    med_lon = float(np.median([g[6] for g in dwell_group]))
                    med_s = float(np.median([g[4] for g in dwell_group]))
                    dwell_st_id = dwell_group[0][2]
                    direction = dwell_group[0][1]
                    dwell_events.append({
                        "fleet": dwell_group[0][0],
                        "direction": direction,
                        "station_id": dwell_st_id,
                        "duration_s": total_duration,
                        "dwell_lat": med_lat,
                        "dwell_lon": med_lon,
                        "dwell_s": med_s
                    })
            dwell_group = [r]

    print(f"[*] Da phat hien {len(dwell_events)} su kien xe dung do (Dwell Events >= 20s, delta_s < 15m)")

    # Compare dwell position with station catalog position
    station_evaluations = []
    for d in dwell_events:
        st_id = d["station_id"]
        dir_name = d["direction"]
        if st_id in stations[dir_name]:
            st = stations[dir_name][st_id]
            dist_to_station = haversine_m(d["dwell_lat"], d["dwell_lon"], st["lat"], st["lon"])
            along_track_err = d["dwell_s"] - st["s_m"]
            station_evaluations.append({
                "station_id": st_id,
                "station_name": st["name"],
                "direction": dir_name,
                "dist_m": dist_to_station,
                "along_err_m": along_track_err
            })

    if station_evaluations:
        dists = [e["dist_m"] for e in station_evaluations]
        along_errs = [e["along_err_m"] for e in station_evaluations]
        print(f"  So su kien dung do khop dung voi ma tram hien tai: {len(station_evaluations)}")
        print(f"  Sai so khong gian trung vi giua diem dung xe va vi tri tram TimBus: {np.median(dists):.1f} m")
        print(f"  Sai so khong gian trung binh: {np.mean(dists):.1f} m")
        print(f"  Phan vi 90% sai so: {np.percentile(dists, 90):.1f} m")
        print(f"  Do lech doc tuyen (Along-track bias): Trung vi = {np.median(along_errs):+.1f} m, Mean = {np.mean(along_errs):+.1f} m")

    # 5. Corridor-by-Corridor Centerline Discrepancy Analysis (1km bins)
    print("\n--- [DANH GIA 4: PHAN TICH SAI SO TIM DUONG THEO TUNG PHAN DOAN 1KM] ---")
    cur.execute("""
    SELECT CAST(s_bus_m / 1000 AS INTEGER) AS km_bin,
           COUNT(*) AS pings,
           ROUND(AVG(cross_track_m), 1) AS avg_d_perp,
           ROUND(MAX(cross_track_m), 1) AS max_d_perp
    FROM route_02_projected_telemetry
    WHERE direction = 'go'
    GROUP BY km_bin
    ORDER BY km_bin
    """)
    corridor_stats = cur.fetchall()
    print(f"  {'Phan doan (km)':<18} | {'So pings':<10} | {'Do lech TB (m)':<15} | {'Do lech Max (m)':<15}")
    print("  " + "-" * 62)
    for row in corridor_stats:
        print(f"  Km {row[0]:02d} -> Km {row[0]+1:02d}    | {row[1]:<10} | {row[2]:<15} | {row[3]:<15}")

    conn.close()
    print("\n[SUCCESS] Hoan tat chieu hoa va tai danh gia toan dien Tuyen 02!")


if __name__ == "__main__":
    from datetime import datetime
    main()
