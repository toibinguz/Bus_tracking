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
sys.path.insert(0, BASE_DIR)

from config.system_config import (
    DEFAULT_DB_PATH,
    CANONICAL_START_DATE,
    MIN_CLUSTER_ROUTE_DAYS,
    HANOI_BBOX,
    METERS_PER_DEG_LON_EQUATOR,
    METERS_PER_DEG_LAT,
    MAX_CORRIDOR_CROSS_TRACK_M,
    MAX_GPS_BACKWARD_JITTER_M,
    FRENET_MIN_FORWARD_WINDOW_M,
    FRENET_MAX_SPEED_MPS,
    GPS_DRIFT_MAX_SPEED_KMPH,
    STALE_DELTA_T_MAX_SEC,
    TERMINAL_RESET_ZONE_M,
)

DB_PATH = os.path.join(BASE_DIR, DEFAULT_DB_PATH)


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
    kx = METERS_PER_DEG_LON_EQUATOR * math.cos(math.radians(mean_lat))
    ky = METERS_PER_DEG_LAT

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
    route_len = float(s_cums[-1])

    results = []
    prev_s = None
    prev_epoch = None

    for ping_id, p_lat, p_lon, p_epoch in vehicle_pings:
        px = p_lon * kx
        py = p_lat * ky

        # 1. Forward Sliding Window Guard within active trip (dt <= STALE_DELTA_T_MAX_SEC)
        use_window = False
        dt = None
        if prev_s is not None and prev_epoch is not None:
            dt = p_epoch - prev_epoch
            if dt <= 0:
                continue
            if dt <= STALE_DELTA_T_MAX_SEC:
                max_forward = max(FRENET_MIN_FORWARD_WINDOW_M, dt * FRENET_MAX_SPEED_MPS)
                win_s_min = max(0.0, prev_s - MAX_GPS_BACKWARD_JITTER_M)
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
            if min_d <= MAX_CORRIDOR_CROSS_TRACK_M:
                best_t = t[best_local_seg]
                best_s = round(float(sub_cum_starts[best_local_seg] + best_t * sub_seg_lens[best_local_seg]), 1)
                if round(best_s - prev_s, 1) >= -MAX_GPS_BACKWARD_JITTER_M:
                    results.append((ping_id, best_s, round(min_d, 1)))
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
        best_s = round(float(cum_starts[best_seg] + best_t * seg_lens[best_seg]), 1)

        # Guard against unphysical mid-route backward jumps within an active trip (0 < dt <= STALE_DELTA_T_MAX_SEC)
        if min_d <= MAX_CORRIDOR_CROSS_TRACK_M:
            if prev_s is not None and dt is not None and (0 < dt <= STALE_DELTA_T_MAX_SEC):
                ds = round(best_s - prev_s, 1)
                if ds < -MAX_GPS_BACKWARD_JITTER_M:
                    is_turnaround_reset = (
                        route_len > 1000.0
                        and prev_s >= (route_len - TERMINAL_RESET_ZONE_M)
                        and best_s <= TERMINAL_RESET_ZONE_M
                    )
                    if not is_turnaround_reset:
                        # Reject mid-route backward jump (wrong-way or loop self-intersection snap)
                        continue
            results.append((ping_id, best_s, round(min_d, 1)))
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
    WHERE route_id = ? AND lat > ? AND lon > ? AND device_update_time >= ?
    ORDER BY vehicle_id, device_epoch;
    """
    pings = cur.execute(
        pings_query,
        (route_id, HANOI_BBOX["min_lat"], HANOI_BBOX["min_lon"], CANONICAL_START_DATE),
    ).fetchall()
    conn.close()

    if not pings or (not shapes.get("go") and not shapes.get("re")):
        return (route_id, route_code, 0, [], time.time() - t0)

    # The SQLite reader is deliberately a thin adapter around SPEC-26's single
    # storage-independent projection policy.
    from .projection_boundary import ProjectableEvent, project_route_events

    direction_hints = {0: "go", 1: "re"}
    events = [
        ProjectableEvent(
            event_id=f"legacy:{ping_id}",
            legacy_ping_id=ping_id,
            route_id=route_id,
            route_code=route_code,
            vehicle_id=vehicle_id,
            plate=plate,
            device_update_time=device_update_time,
            device_epoch_s=device_epoch,
            direction_hint=direction_hints.get(raw_direction, "unknown"),
            current_station_id=current_station_id,
            lat=lat,
            lon=lon,
        )
        for (
            ping_id, vehicle_id, plate, device_update_time, device_epoch,
            raw_direction, lat, lon, current_station_id,
        ) in pings
    ]
    projected_events, _ = project_route_events(events, shapes, st_dir)
    records = [
        (
            event.legacy_ping_id,
            event.route_code,
            event.route_id,
            event.vehicle_id,
            event.plate,
            event.device_update_time,
            event.device_epoch_s,
            event.direction,
            event.lat,
            event.lon,
            event.s_bus_m,
            event.cross_track_m,
            event.derived_speed_kmh,
        )
        for event in projected_events
    ]

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

    # Ensure table exists with clean 13-column Silver schema (no dead is_dwell column)
    cur.execute("DROP VIEW IF EXISTS v_bus_to_next_station;")
    cur.execute("DROP VIEW IF EXISTS v_active_fleet_summary;")
    cur.execute("DROP TABLE IF EXISTS route_projected_telemetry;")
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
        derived_speed_kmh REAL
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

    # Find the 48 active cluster routes with persistent telemetry (>= MIN_CLUSTER_ROUTE_DAYS days)
    routes_query = """
    SELECT DISTINCT r.route_id, r.route_code, count(t.ping_id) as pings
    FROM canonical_route_master r
    JOIN vehicle_unique_pings t ON r.route_id = t.route_id
    WHERE r.route_id IN (SELECT DISTINCT route_id FROM canonical_shape_master)
      AND t.device_update_time >= ?
    GROUP BY r.route_id, r.route_code
    HAVING count(DISTINCT t.date_tag) >= ?
    ORDER BY pings DESC;
    """
    active_routes = cur.execute(routes_query, (CANONICAL_START_DATE, MIN_CLUSTER_ROUTE_DAYS)).fetchall()
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
                        lat, lon, s_bus_m, cross_track_m, derived_speed_kmh
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
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

    # Recreate clean operational SQL views in SQLite
    from module_2_big_data_storage_and_lakehouse.step_2_1_sqlite_operational_store.db_manager import (
        OperationalDatabaseManager,
    )
    OperationalDatabaseManager(db_path=db_path)

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
