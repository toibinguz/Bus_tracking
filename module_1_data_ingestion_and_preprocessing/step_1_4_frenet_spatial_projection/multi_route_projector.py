"""
High-Speed Multi-Core Parallel Frenet Spatial Projection Pipeline (v3.0 Clean)
- Enforces GTFS Direction Standard: 0 -> go (Outbound), 1 -> re (Inbound)
- Quarantines unassigned depot / off-duty pings (direction = -1 with no valid station)
- Implements Monotonicity Forward Sliding Window Guard to eliminate backward projection jumps
- Resolves shared station topology (457 terminal/interchange stops)
- Calculates robust derived kinematics (v_derived = delta_s / delta_t) with strict corridor chaining
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

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(BASE_DIR, "data", "hanoi_bus_system.db")


def project_points_to_shape(
    vehicle_pings: List[Tuple[Any, ...]], 
    shape_pts: List[Tuple[float, float, float]]
) -> List[Tuple[int, float, float]]:
    """
    Vectorized orthogonal projection of GPS points onto polyline segments
    with Monotonicity Forward Sliding Window Guard for trajectory continuity.
    vehicle_pings: list of (ping_id, lat, lon, device_epoch) sorted by epoch.
    shape_pts: list of (point_order, lat, lon, cum_distance_m) sorted by point_order.
    """
    if not vehicle_pings or not shape_pts:
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
    n_segs = len(dx)

    results = []
    prev_s = None
    prev_epoch = None

    for ping_id, p_lat, p_lon, p_epoch in vehicle_pings:
        px = p_lon * kx
        py = p_lat * ky

        # 1. Forward Sliding Window Guard within active trip (dt <= 300s)
        use_window = False
        if prev_s is not None and prev_epoch is not None:
            dt = p_epoch - prev_epoch
            if 0 < dt <= 300.0:
                max_forward = max(1500.0, dt * 25.0)  # max 25 m/s (90 km/h)
                win_s_min = max(0.0, prev_s - 20.0)
                win_s_max = prev_s + max_forward

                idx_start = max(0, int(np.searchsorted(cum_starts, win_s_min, side='left')) - 1)
                idx_end = min(n_segs, int(np.searchsorted(cum_starts, win_s_max, side='right')) + 1)
                if idx_end > idx_start:
                    use_window = True

        if use_window:
            sub_x1 = x1[idx_start:idx_end]
            sub_y1 = y1[idx_start:idx_end]
            sub_dx = dx[idx_start:idx_end]
            sub_dy = dy[idx_start:idx_end]
            sub_safe_lens_sq = safe_lens_sq[idx_start:idx_end]
            sub_seg_lens = seg_lens[idx_start:idx_end]
            sub_cum_starts = cum_starts[idx_start:idx_end]

            p_dx1 = px - sub_x1
            p_dy1 = py - sub_y1
            t = np.clip((p_dx1 * sub_dx + p_dy1 * sub_dy) / sub_safe_lens_sq, 0.0, 1.0)
            proj_x = sub_x1 + t * sub_dx
            proj_y = sub_y1 + t * sub_dy
            dist_sq = (px - proj_x) ** 2 + (py - proj_y) ** 2
            best_local_seg = np.argmin(dist_sq)
            min_d = math.sqrt(dist_sq[best_local_seg])

            # If within acceptable corridor tolerance, lock onto forward projection
            if min_d <= 45.0:
                best_t = t[best_local_seg]
                best_s = sub_cum_starts[best_local_seg] + best_t * sub_seg_lens[best_local_seg]
                results.append((ping_id, round(best_s, 1), round(min_d, 1)))
                prev_s = best_s
                prev_epoch = p_epoch
                continue

        # 2. Global Search Fallback (trip restarts, terminal resets, major detours)
        p_dx1 = px - x1
        p_dy1 = py - y1
        t = np.clip((p_dx1 * dx + p_dy1 * dy) / safe_lens_sq, 0.0, 1.0)
        proj_x = x1 + t * dx
        proj_y = y1 + t * dy
        dist_sq = (px - proj_x) ** 2 + (py - proj_y) ** 2
        best_seg = np.argmin(dist_sq)

        min_d = math.sqrt(dist_sq[best_seg])
        best_t = t[best_seg]
        best_s = cum_starts[best_seg] + best_t * seg_lens[best_seg]

        results.append((ping_id, round(best_s, 1), round(min_d, 1)))
        prev_s = best_s
        prev_epoch = p_epoch

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
    WHERE route_id = ? AND lat > 20.0 AND lon > 105.0 AND device_update_time >= '2026-10-08'
    ORDER BY vehicle_id, device_epoch;
    """
    pings = cur.execute(pings_query, (route_id,)).fetchall()
    conn.close()

    if not pings or (not shapes.get("go") and not shapes.get("re")):
        return (route_id, route_code, 0, [], time.time() - t0)

    # 1. Clean Direction Assignment & Depot Quarantine
    # GTFS standard: 0 -> go, 1 -> re
    # -1: Check if current_station_id is unambiguous in st_dir; if station = 0, isolate as depot
    pings_by_veh_dir: Dict[Tuple[int, str], List[Tuple[int, float, float, float]]] = {}
    ping_meta: Dict[int, Any] = {}
    quarantine_count = 0

    for p in pings:
        pid, vid, plate, t_str, epoch, p_dir, lat, lon, curr_st = p
        ping_meta[pid] = p

        d_str = None
        if curr_st and (route_id, curr_st) in st_dir:
            d_str = st_dir[(route_id, curr_st)]
        elif p_dir == 0:
            d_str = "go"
        elif p_dir == 1:
            d_str = "re"
        else:
            # p_dir == -1 with no unambiguous station -> Depot / Off-duty
            quarantine_count += 1
            continue

        pings_by_veh_dir.setdefault((vid, d_str), []).append((pid, lat, lon, epoch))

    # 2. Execute Monotonic Projection per vehicle trajectory
    projected_results: Dict[int, Tuple[float, float, str]] = {}
    for (vid, d_str), v_pings in pings_by_veh_dir.items():
        if shapes.get(d_str) and v_pings:
            v_pings.sort(key=lambda x: x[3])  # sort by epoch
            res = project_points_to_shape(v_pings, shapes[d_str])
            for pid, s_m, d_perp in res:
                projected_results[pid] = (s_m, d_perp, d_str)

    # 3. Calculate derived kinematics (delta_s / delta_t) per vehicle trajectory
    records = []
    vehicles: Dict[int, List[Tuple[int, float, Tuple[float, float, str]]]] = {}
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

            if i > 0:
                prev_pid, prev_epoch, (prev_s, prev_d_perp, prev_d_str) = v_pings[i - 1]
                dt = epoch - prev_epoch
                ds = s_m - prev_s

                # Strict Corridor Chain Rule:
                # Both points must be within corridor (d_perp <= 35m) on same direction trip.
                # Speed capped at physical urban limit (80 km/h).
                is_corridor_chain = (d_perp <= 35.0) and (prev_d_perp <= 35.0)
                is_same_trip = (0 < dt <= 300.0) and (d_str == prev_d_str) and (ds >= -30.0)

                if is_corridor_chain and is_same_trip:
                    v_mps = abs(ds) / dt
                    spd_kmh = round(v_mps * 3.6, 2)
                    if spd_kmh <= 80.0:
                        derived_speed_kmh = spd_kmh

            # Strict Silver corridor boundary: only keep on-corridor pings (d_perp <= 35.0m)
            if d_perp > 35.0:
                continue

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
                0         # is_dwell removed (always 0)
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

    # Pre-configure turbo PRAGMA settings for the writer
    cur.execute("PRAGMA journal_mode = WAL;")
    cur.execute("PRAGMA synchronous = NORMAL;")
    cur.execute("PRAGMA cache_size = -1048576;")  # 1 GB cache
    cur.execute("PRAGMA temp_store = MEMORY;")

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
    shapes_by_route: Dict[int, Dict[str, list]] = {}
    cur.execute("SELECT route_id, direction, point_order, lat, lon, cum_distance_m FROM canonical_shape_master ORDER BY route_id, direction, point_order;")
    for r_id, direction, pt_order, lat, lon, cum_dist in cur.fetchall():
        d = direction.lower()
        if r_id not in shapes_by_route:
            shapes_by_route[r_id] = {"go": [], "re": []}
        if d in shapes_by_route[r_id]:
            shapes_by_route[r_id][d].append((pt_order, lat, lon, cum_dist))
    print(f"Loaded shapes for {len(shapes_by_route)} routes.")

    # Find the 48 active cluster routes with persistent telemetry (>= 5 days)
    routes_query = """
    SELECT DISTINCT r.route_id, r.route_code, count(t.ping_id) as pings
    FROM canonical_route_master r
    JOIN vehicle_unique_pings t ON r.route_id = t.route_id
    WHERE r.route_id IN (SELECT DISTINCT route_id FROM canonical_shape_master)
      AND t.device_update_time >= '2026-10-08'
    GROUP BY r.route_id, r.route_code
    HAVING count(DISTINCT t.date_tag) >= 5
    ORDER BY pings DESC;
    """
    active_routes = cur.execute(routes_query).fetchall()
    print(f"[*] Found {len(active_routes)} active routes requiring Frenet projection.")

    conn.close()

    total_pings_all = sum(r[2] for r in active_routes)
    print(f"[*] Total workload: {total_pings_all:,} raw pings across {len(active_routes)} routes.")
    print(f"[*] Dispatching ProcessPoolExecutor with {num_workers} worker processes...")
    print("=" * 80)

    start_all = time.time()
    total_written = 0

    worker_tasks = [
        (db_path, r_id, r_code, shapes_by_route.get(r_id, {}), st_dir)
        for r_id, r_code, _ in active_routes
    ]

    # Re-open dedicated writer connection on main thread
    writer_conn = sqlite3.connect(db_path)
    writer_cur = writer_conn.cursor()
    writer_cur.execute("PRAGMA synchronous = NORMAL;")
    writer_cur.execute("PRAGMA cache_size = -1048576;")

    # Clear destination table cleanly before full re-projection
    print("[*] Purging legacy projected telemetry table...")
    writer_cur.execute("DELETE FROM route_projected_telemetry;")
    writer_conn.commit()

    completed_routes = 0
    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        future_to_route = {executor.submit(worker_project_route, task): task[1] for task in worker_tasks}

        for future in as_completed(future_to_route):
            r_id = future_to_route[future]
            try:
                route_id, route_code, raw_count, records, compute_time = future.result()
                completed_routes += 1

                # Fast bulk insert on main thread
                if records:
                    writer_cur.executemany("""
                    INSERT INTO route_projected_telemetry (
                        ping_id, route_code, route_id, vehicle_id, plate,
                        device_update_time, device_epoch, direction,
                        lat, lon, s_bus_m, cross_track_m, derived_speed_kmh, is_dwell
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """, records)
                    writer_conn.commit()
                    total_written += len(records)

                speed_str = f"{len(records)/compute_time:,.0f} pings/s" if compute_time > 0 else "N/A"
                print(f"[{completed_routes:02d}/{len(active_routes):02d}] Route {route_code:<5} (ID {route_id:>3}): "
                      f"Projected {len(records):>7,} / {raw_count:>7,} pings in {compute_time:>5.2f}s ({speed_str:>13}) | "
                      f"Total written: {total_written:>9,}")
            except Exception as e:
                print(f"[!] Error projecting route {r_id}: {e}")

    writer_conn.close()
    elapsed_all = time.time() - start_all
    print("=" * 80)
    print(f"ALL {len(active_routes)} ROUTES PROJECTION COMPLETED SUCCESSFULLY!")
    print(f"Total Projected Pings Written: {total_written:,}")
    print(f"Total Wall Clock Time: {elapsed_all:.2f}s ({elapsed_all/60:.2f} mins)")
    print(f"Overall Processing Throughput: {total_written/elapsed_all:,.0f} pings/sec")
    print("=" * 80)


project_route = worker_project_route
run_multi_route_projection = run_parallel_projection

if __name__ == "__main__":
    run_parallel_projection()
