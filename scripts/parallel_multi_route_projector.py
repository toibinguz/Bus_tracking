"""
High-Speed Multi-Core Parallel Frenet Spatial Projection Pipeline
Utilizes ProcessPoolExecutor across available CPU cores to project all active routes simultaneously.
Writer runs on the main thread to ensure SQLite ACID integrity and avoid lock contention.
"""

import os
import sys
import time
import math
import sqlite3
import numpy as np
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional
from concurrent.futures import ProcessPoolExecutor, as_completed

# Ensure UTF-8 output
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "hanoi_bus_system.db")


def project_points_to_shape(pings: List[Tuple[Any, ...]], shape_pts: List[Tuple[float, float, float]]) -> List[Tuple[int, float, float]]:
    """Vectorized orthogonal projection of GPS points onto polyline segments."""
    if not pings or not shape_pts:
        return []

    s_lats = np.array([p[1] for p in shape_pts], dtype=np.float64)
    s_lons = np.array([p[2] for p in shape_pts], dtype=np.float64)
    s_cums = np.array([p[3] for p in shape_pts], dtype=np.float64)

    if len(s_lats) < 2:
        return []

    mean_lat = np.mean(s_lats)
    kx = 111320.0 * math.cos(math.radians(mean_lat))
    ky = 110540.0

    x1 = s_lons[:-1] * kx
    y1 = s_lats[:-1] * ky
    x2 = s_lons[1:] * kx
    y2 = s_lats[1:] * ky

    dx = x2 - x1
    dy = y2 - y1
    seg_lens_sq = dx * dx + dy * dy
    safe_lens_sq = np.maximum(seg_lens_sq, 1e-6)
    cum_starts = s_cums[:-1]
    seg_lens = np.sqrt(seg_lens_sq)

    results = []
    for ping_id, p_lat, p_lon, p_epoch in pings:
        px = p_lon * kx
        py = p_lat * ky

        p_dx1 = px - x1
        p_dy1 = py - y1

        t = (p_dx1 * dx + p_dy1 * dy) / safe_lens_sq
        t = np.clip(t, 0.0, 1.0)

        proj_x = x1 + t * dx
        proj_y = y1 + t * dy

        dist_sq = (px - proj_x) ** 2 + (py - proj_y) ** 2
        best_seg = np.argmin(dist_sq)

        min_d = math.sqrt(dist_sq[best_seg])
        best_t = t[best_seg]
        best_s = cum_starts[best_seg] + best_t * seg_lens[best_seg]

        results.append((ping_id, round(best_s, 1), round(min_d, 1)))

    return results


def worker_project_route(args: Tuple[str, int, str, Dict[str, list], Dict[Tuple[int, int], str]]) -> Tuple[int, str, int, list, float]:
    """Worker task executing spatial projection for a single route in its own CPU process."""
    db_path, route_id, route_code, shapes, st_dir = args
    t0 = time.time()

    # Open isolated read-only connection
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    cur = conn.cursor()

    pings_query = """
    SELECT ping_id, vehicle_id, plate, device_update_time, device_epoch, direction, lat, lon, current_station_id
    FROM vehicle_unique_pings
    WHERE route_id = ? AND lat > 20.0 AND lon > 105.0
    ORDER BY vehicle_id, device_epoch;
    """
    pings = cur.execute(pings_query, (route_id,)).fetchall()
    conn.close()

    if not pings or (not shapes.get("go") and not shapes.get("re")):
        return (route_id, route_code, 0, [], time.time() - t0)

    # 1. Assign initial direction using Station-Guidance
    pings_by_dir = {"go": [], "re": []}
    ping_meta = {}
    for p in pings:
        pid, vid, plate, t_str, epoch, p_dir, lat, lon, curr_st = p
        if curr_st and (route_id, curr_st) in st_dir:
            d_str = st_dir[(route_id, curr_st)]
        else:
            d_str = "go" if p_dir in (0, -1) else "re"

        pings_by_dir[d_str].append((pid, lat, lon, epoch))
        ping_meta[pid] = p

    # 2. Execute primary projection
    projected_results = {}
    for d_str in ["go", "re"]:
        if shapes.get(d_str) and pings_by_dir[d_str]:
            res = project_points_to_shape(pings_by_dir[d_str], shapes[d_str])
            for pid, s_m, d_perp in res:
                projected_results[pid] = (s_m, d_perp, d_str)

    # 3. Self-Healing Direction Guard: Strictly restricted to Terminal Turnaround Zones (s <= 500m or s >= L - 300m)
    # Prevents mid-corridor cross-talk / direction flickering between parallel opposing lanes
    needs_retry = []
    for pid, (s_m, d_perp, d_str) in projected_results.items():
        if d_perp > 45.0:
            opp_dir = "re" if d_str == "go" else "go"
            if shapes.get(opp_dir):
                shape_len = shapes[d_str][-1][3] if shapes.get(d_str) else 0.0
                is_near_terminal = (s_m <= 500.0) or (s_m >= shape_len - 300.0)
                if is_near_terminal:
                    p = ping_meta[pid]
                    needs_retry.append((opp_dir, (pid, p[6], p[7], p[4])))

    if needs_retry:
        retry_by_dir = {"go": [], "re": []}
        for opp_dir, ping_item in needs_retry:
            retry_by_dir[opp_dir].append(ping_item)

        for opp_dir in ["go", "re"]:
            if shapes.get(opp_dir) and retry_by_dir[opp_dir]:
                retry_res = project_points_to_shape(retry_by_dir[opp_dir], shapes[opp_dir])
                for pid, new_s, new_dperp in retry_res:
                    orig_s, orig_dperp, orig_d = projected_results[pid]
                    if new_dperp < 25.0 and (orig_dperp - new_dperp) > 20.0:
                        projected_results[pid] = (new_s, new_dperp, opp_dir)

    # 4. Calculate derived kinematics (delta_s / delta_t) per vehicle trajectory
    records = []
    vehicles = {}
    for p in pings:
        pid = p[0]
        if pid in projected_results:
            vid = p[1]
            vehicles.setdefault(vid, []).append((pid, p[4], projected_results[pid]))

    for vid, v_pings in vehicles.items():
        v_pings.sort(key=lambda x: x[1])  # sort by epoch
        for i in range(len(v_pings)):
            pid, epoch, (s_m, d_perp, d_str) = v_pings[i]
            meta = ping_meta[pid]

            derived_speed_kmh = None
            is_dwell = 0

            if i > 0:
                prev_pid, prev_epoch, (prev_s, prev_d_perp, prev_d_str) = v_pings[i - 1]
                dt = epoch - prev_epoch
                ds = abs(s_m - prev_s)

                # Strict 2-Point Consecutive Corridor Chain Rule:
                # Both previous ping and current ping must be valid on-corridor (d_perp <= 35m).
                # Eliminates boundary leakage from depot/garage and off-route deadheading.
                # If v > 80.0 km/h or jump occurs, strictly drop to None (NO ARTIFICIAL CLAMPING).
                is_corridor_chain = (d_perp <= 35.0) and (prev_d_perp <= 35.0)
                is_same_trip = (0 < dt <= 300) and (d_str == prev_d_str) and (s_m >= prev_s - 50.0)

                if is_corridor_chain and is_same_trip:
                    v_mps = ds / dt
                    spd_kmh = round(v_mps * 3.6, 2)
                    if spd_kmh <= 80.0:
                        derived_speed_kmh = spd_kmh
                    else:
                        derived_speed_kmh = None

                # Kinematic Dwell Condition: ds < 15m for dt >= 20s (strictly within corridor)
                if (d_perp <= 35.0) and (ds < 15.0) and (dt >= 20.0):
                    is_dwell = 1

            records.append((
                pid,
                route_code,
                route_id,
                meta[1],  # vehicle_id
                meta[2],  # plate
                meta[3],  # device_update_time
                meta[4],  # device_epoch
                d_str,
                meta[6],  # lat
                meta[7],  # lon
                s_m,
                d_perp,
                derived_speed_kmh,
                is_dwell
            ))

    compute_time = time.time() - t0
    return (route_id, route_code, len(pings), records, compute_time)


def run_parallel_projection(db_path: str = DB_PATH, num_workers: Optional[int] = None):
    """Run parallel projection for all routes using ProcessPoolExecutor."""
    if num_workers is None:
        num_workers = 6
    num_workers = min(num_workers, 6)  # Strict cap: at most 6 workers

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # High performance PRAGMA
    cur.execute("PRAGMA journal_mode = WAL;")
    cur.execute("PRAGMA synchronous = OFF;")
    cur.execute("PRAGMA cache_size = -524288;")  # 512 MB cache

    # Ensure table exists
    cur.execute("""
    CREATE TABLE IF NOT EXISTS route_projected_telemetry (
        ping_id INTEGER PRIMARY KEY,
        route_code TEXT NOT NULL,
        route_id INTEGER NOT NULL,
        vehicle_id INTEGER NOT NULL,
        plate TEXT,
        device_update_time TEXT NOT NULL,
        device_epoch REAL NOT NULL,
        direction TEXT NOT NULL,
        lat REAL NOT NULL,
        lon REAL NOT NULL,
        s_bus_m REAL NOT NULL,
        cross_track_m REAL NOT NULL,
        derived_speed_kmh REAL,
        is_dwell INTEGER DEFAULT 0
    );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rpt_route_code ON route_projected_telemetry (route_code);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rpt_route_id ON route_projected_telemetry (route_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rpt_vehicle_epoch ON route_projected_telemetry (vehicle_id, device_epoch);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rpt_route_dir_s ON route_projected_telemetry (route_code, direction, s_bus_m);")
    conn.commit()

    # Preload unambiguous single-direction station lookup (excludes shared terminal/transfer stops)
    print(f"[*] Pre-loading canonical station directions lookup...")
    cur.execute("""
        SELECT route_id, station_id, MIN(direction)
        FROM canonical_station_master
        GROUP BY route_id, station_id
        HAVING COUNT(DISTINCT direction) = 1;
    """)
    st_dir = {(r_id, st_id): d for r_id, st_id, d in cur.fetchall()}
    print(f"Loaded {len(st_dir):,} unambiguous canonical station direction markers.")

    # Preload all shapes grouped by route_id
    print("[*] Pre-loading canonical shape polylines...")
    shapes_by_route = {}
    cur.execute("SELECT route_id, direction, point_order, lat, lon, cum_distance_m FROM canonical_shape_master ORDER BY route_id, direction, point_order;")
    for r_id, direction, pt_order, lat, lon, cum_dist in cur.fetchall():
        d = direction.lower()
        if r_id not in shapes_by_route:
            shapes_by_route[r_id] = {"go": [], "re": []}
        if d in shapes_by_route[r_id]:
            shapes_by_route[r_id][d].append((pt_order, lat, lon, cum_dist))
    print(f"Loaded shapes for {len(shapes_by_route)} routes.")

    # Find active routes with telemetry
    routes_query = """
    SELECT DISTINCT r.route_id, r.route_code, count(t.ping_id) as pings
    FROM canonical_route_master r
    JOIN vehicle_unique_pings t ON r.route_id = t.route_id
    WHERE r.route_id IN (SELECT DISTINCT route_id FROM canonical_shape_master)
    GROUP BY r.route_id, r.route_code
    ORDER BY pings DESC;
    """
    routes = cur.execute(routes_query).fetchall()
    total_pings_all = sum(r[2] for r in routes)

    print("=" * 80)
    print(f"🚀 MULTI-CORE PARALLEL FRENET PROJECTION ({len(routes)} ROUTES, {total_pings_all:,} PINGS)")
    print(f"⚡ Utilizing {num_workers} Parallel Worker Processes across {os.cpu_count()} CPU Cores")
    print("=" * 80)

    # Prepare worker tasks
    tasks = []
    for r_id, rc, p_cnt in routes:
        route_shapes = shapes_by_route.get(r_id, {"go": [], "re": []})
        tasks.append((db_path, r_id, rc, route_shapes, st_dir))

    total_projected = 0
    completed_routes = 0
    t_start = time.time()

    insert_sql = """
    INSERT OR REPLACE INTO route_projected_telemetry (
        ping_id, route_code, route_id, vehicle_id, plate,
        device_update_time, device_epoch, direction,
        lat, lon, s_bus_m, cross_track_m, derived_speed_kmh, is_dwell
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """

    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        # Submit all tasks
        futures = {executor.submit(worker_project_route, task): task[1] for task in tasks}

        for future in as_completed(futures):
            route_id, route_code, p_count, records, comp_time = future.result()
            completed_routes += 1

            # Writer commits to DB
            if records:
                cur.execute("DELETE FROM route_projected_telemetry WHERE route_id = ?", (route_id,))
                cur.executemany(insert_sql, records)
                conn.commit()
                total_projected += len(records)

            print(f"[{completed_routes:02d}/{len(routes)}] Route {route_code:<6} (ID {route_id:<6}): {len(records):,} / {p_count:,} pings projected in {comp_time:.2f}s | Progress: {total_projected:,} pings", flush=True)

    elapsed = time.time() - t_start
    cur.execute("PRAGMA synchronous = NORMAL;")
    conn.close()

    print("=" * 80)
    print("🎉 PARALLEL FRENET PROJECTION COMPLETED SUCCESSFULLY")
    print(f"- Total Routes: {len(routes)}")
    print(f"- Total Pings Linear Referenced: {total_projected:,}")
    print(f"- Total Wall Time: {elapsed:.2f}s ({elapsed/60:.2f} mins)")
    print(f"- Throughput: {total_projected / elapsed:,.0f} pings/second across {num_workers} cores")
    print(f"- Target Table: route_projected_telemetry in {db_path}")
    print("=" * 80)


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else DB_PATH
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else None
    run_parallel_projection(db, workers)
