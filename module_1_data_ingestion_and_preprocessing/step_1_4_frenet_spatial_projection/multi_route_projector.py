"""
High-Speed Multi-Core Parallel Frenet Spatial Projection Pipeline (v3.0 Clean)
- Enforces GTFS Direction Standard: 0 -> go (Outbound), 1 -> re (Inbound)
- Quarantines unassigned depot / off-duty pings (direction = -1 with no valid station)
- Uses the shared causal route HMM, including terminal/direction lifecycle
- Resolves shared station topology (457 terminal/interchange stops)
- Calculates robust derived kinematics (v_derived = delta_s / delta_t) with strict corridor chaining
"""

import os
import sys
import time
import sqlite3
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
    BATCH_HMM_HORIZON_SEC,
    DEFAULT_DB_PATH,
    CANONICAL_START_DATE,
    MIN_CLUSTER_ROUTE_DAYS,
    HANOI_BBOX,
    MAX_CORRIDOR_CROSS_TRACK_M,
)

DB_PATH = os.path.join(BASE_DIR, DEFAULT_DB_PATH)


def project_points_to_shape(vehicle_pings, shape_pts):
    """Apply the same causal HMM used by serving to one ordered vehicle/route run."""
    if not vehicle_pings or len(shape_pts)<2:
        return []
    from .route_matcher import ShapeProjectionModel, RouteHMM
    matcher=RouteHMM(ShapeProjectionModel.build(shape_pts), horizon=BATCH_HMM_HORIZON_SEC)
    output=[]
    previous_epoch=None
    for index,(ping_id,lat,lon,epoch) in enumerate(vehicle_pings):
        if previous_epoch is not None and epoch<=previous_epoch:
            continue
        previous_epoch=epoch
        match=matcher.update(float(epoch),float(lat),float(lon),index)
        if match is not None:
            output.append((ping_id,match.s,match.cross_track))
    return output


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
    WHERE route_id = ? AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ? AND device_update_time >= ?
    ORDER BY vehicle_id, device_epoch;
    """
    pings = cur.execute(
        pings_query,
        (
            route_id,
            HANOI_BBOX["min_lat"],
            HANOI_BBOX["max_lat"],
            HANOI_BBOX["min_lon"],
            HANOI_BBOX["max_lon"],
            CANONICAL_START_DATE,
        ),
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
