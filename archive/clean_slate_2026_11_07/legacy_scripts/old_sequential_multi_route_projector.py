"""
Module 1: Production Multi-Route Frenet Projection Engine (Canonical Clean v3.0).
Linear references raw GPS pings (vehicle_unique_pings) onto Canonical BusMap Master Polylines
(canonical_shape_master) to produce 1D progress coordinate (s_bus_m), orthogonal cross-track
error (cross_track_m), and derived kinematics (v_derived = delta_s / delta_t).

Canonical Data Sources:
- canonical_shape_master: Master line strings with cum_distance_m
- canonical_route_master: Route catalog and metadata
- canonical_station_master: Station sequence with direction tags
- vehicle_unique_pings: Cleaned, deduplicated raw telemetry

Output Table:
- route_projected_telemetry
"""

import sqlite3
import numpy as np
import time
import math
import sys
from pathlib import Path
from typing import List, Tuple, Dict, Optional, Any

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, ".")

from config.system_config import get_database_path, DEFAULT_DB_PATH


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

            if min_d <= 45.0:
                best_t = t[best_local_seg]
                best_s = sub_cum_starts[best_local_seg] + best_t * sub_seg_lens[best_local_seg]
                results.append((ping_id, round(best_s, 1), round(min_d, 1)))
                prev_s = best_s
                prev_epoch = p_epoch
                continue

        # 2. Global Search Fallback
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


def init_projected_telemetry_table(conn: sqlite3.Connection):
    """Ensure destination table exists with high-speed indexes."""
    cur = conn.cursor()
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


def project_route(route_id: int, route_code: str, conn: sqlite3.Connection, st_dir: Dict[Tuple[int, int], str]) -> int:
    """Project all telemetry pings for a route onto canonical shape master polylines."""
    cur = conn.cursor()

    # Load canonical shapes for both directions
    shapes = {"go": [], "re": []}
    for row in cur.execute("""
        SELECT direction, point_order, lat, lon, cum_distance_m 
        FROM canonical_shape_master 
        WHERE route_id = ? 
        ORDER BY direction, point_order
    """, (route_id,)).fetchall():
        d = row[0].lower()
        if d in shapes:
            shapes[d].append((row[1], row[2], row[3], row[4]))

    if not shapes["go"] and not shapes["re"]:
        return 0

    # Fetch unique pings for this route
    pings_query = """
    SELECT ping_id, vehicle_id, plate, device_update_time, device_epoch, direction, lat, lon, current_station_id
    FROM vehicle_unique_pings
    WHERE route_id = ? AND lat > 20.0 AND lon > 105.0
    ORDER BY vehicle_id, device_epoch;
    """
    pings = cur.execute(pings_query, (route_id,)).fetchall()
    if not pings:
        return 0

    pings_by_veh_dir: Dict[Tuple[int, str], List[Tuple[int, float, float, float]]] = {}
    ping_meta: Dict[int, Any] = {}

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
            continue

        pings_by_veh_dir.setdefault((vid, d_str), []).append((pid, lat, lon, epoch))

    projected_results: Dict[int, Tuple[float, float, str]] = {}
    for (vid, d_str), v_pings in pings_by_veh_dir.items():
        if shapes.get(d_str) and v_pings:
            v_pings.sort(key=lambda x: x[3])
            res = project_points_to_shape(v_pings, shapes[d_str])
            for pid, s_m, d_perp in res:
                projected_results[pid] = (s_m, d_perp, d_str)

    # Derived kinematics
    records = []
    vehicles: Dict[int, List[Tuple[int, float, Tuple[float, float, str]]]] = {}
    for p in pings:
        pid = p[0]
        if pid in projected_results:
            vid = p[1]
            vehicles.setdefault(vid, []).append((pid, p[4], projected_results[pid]))

    for vid, v_pings in vehicles.items():
        v_pings.sort(key=lambda x: x[1])
        for i in range(len(v_pings)):
            pid, epoch, (s_m, d_perp, d_str) = v_pings[i]
            meta = ping_meta[pid]

            derived_speed_kmh = None

            if i > 0:
                prev_pid, prev_epoch, (prev_s, prev_d_perp, prev_d_str) = v_pings[i - 1]
                dt = epoch - prev_epoch
                ds = s_m - prev_s

                is_corridor_chain = (d_perp <= 35.0) and (prev_d_perp <= 35.0)
                is_same_trip = (0 < dt <= 300.0) and (d_str == prev_d_str) and (ds >= -30.0)

                if is_corridor_chain and is_same_trip:
                    v_mps = abs(ds) / dt
                    spd_kmh = round(v_mps * 3.6, 2)
                    if spd_kmh <= 80.0:
                        derived_speed_kmh = spd_kmh

            records.append((
                pid,
                route_code,
                route_id,
                meta[1],
                meta[2],
                meta[3],
                meta[4],
                d_str,
                meta[6],
                meta[7],
                s_m,
                d_perp,
                derived_speed_kmh,
                0
            ))

    cur.execute("DELETE FROM route_projected_telemetry WHERE route_id = ?", (route_id,))
    cur.executemany("""
    INSERT INTO route_projected_telemetry (
        ping_id, route_code, route_id, vehicle_id, plate,
        device_update_time, device_epoch, direction,
        lat, lon, s_bus_m, cross_track_m, derived_speed_kmh, is_dwell
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """, records)
    conn.commit()

    return len(records)


def run_multi_route_projection(db_path: Optional[str] = None, limit: Optional[int] = None):
    """Run projection for all available routes using Canonical Master."""
    if sys.stdout.encoding != 'utf-8':
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except Exception:
            pass

    conn = sqlite3.connect(db_path or get_database_path())
    init_projected_telemetry_table(conn)

    cur = conn.cursor()

    # Preload station directions lookup (unambiguous)
    print("Pre-loading canonical station directions lookup...")
    cur.execute("""
        SELECT route_id, station_id, MIN(direction)
        FROM canonical_station_master
        GROUP BY route_id, station_id
        HAVING COUNT(DISTINCT direction) = 1;
    """)
    st_dir = {(r_id, st_id): d for r_id, st_id, d in cur.fetchall()}
    print(f"Loaded {len(st_dir):,} canonical station direction markers.")

    # Find all active routes with telemetry
    routes_query = """
    SELECT DISTINCT r.route_id, r.route_code, count(t.ping_id) as pings
    FROM canonical_route_master r
    JOIN vehicle_unique_pings t ON r.route_id = t.route_id
    WHERE r.route_id IN (SELECT DISTINCT route_id FROM canonical_shape_master)
    GROUP BY r.route_id, r.route_code
    ORDER BY pings DESC;
    """
    routes = cur.execute(routes_query).fetchall()
    if limit:
        routes = routes[:limit]

    print(f"Found {len(routes)} active routes requiring Frenet projection.")

    total_projected = 0
    t0 = time.time()
    for idx, (route_id, route_code, raw_count) in enumerate(routes, 1):
        t_route = time.time()
        cnt = project_route(route_id, route_code, conn, st_dir)
        total_projected += cnt
        dt_route = time.time() - t_route
        rate = cnt / dt_route if dt_route > 0 else 0
        print(f"[{idx:02d}/{len(routes):02d}] Route {route_code:<5} (ID {route_id:>3}): Projected {cnt:>7,} / {raw_count:>7,} pings in {dt_route:5.1f}s ({rate:,.0f} pings/s)")

    conn.close()
    elapsed = time.time() - t0
    print("=" * 70)
    print(f"Done! Projected {total_projected:,} pings across {len(routes)} routes in {elapsed:.1f}s.")


if __name__ == "__main__":
    run_multi_route_projection()
