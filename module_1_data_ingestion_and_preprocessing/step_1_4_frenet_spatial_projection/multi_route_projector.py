"""
Module 1: Data Ingestion & Preprocessing
Subcomponent: step_1_4_frenet_spatial_projection
File: multi_route_projector.py

Vectorized multi-route linear referencing and centerline projection pipeline.
Projects raw GPS pings of any bus route onto the official TimBus centerline polyline (timbus_shape_master)
and stores along-track distance (s), cross-track error (d_perp), and derived speed (v = delta_s / delta_t).
"""

import sys

from config.system_config import get_database_path, DEFAULT_DB_PATH
import os
import math
import sqlite3
import time
import numpy as np
from typing import Dict, List, Tuple, Optional

# Ensure project root in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))
sys.path.insert(0, os.path.abspath("."))

EARTH_RADIUS_M = 6371000.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * (math.sin(d_lambda / 2.0) ** 2)
    return EARTH_RADIUS_M * 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def project_points_to_shape(pings: list, shape_pts: list) -> list:
    """
    Project a list of pings onto a polyline.
    shape_pts: list of (point_order, lat, lon, cum_distance_m)
    pings: list of (ping_id, lat, lon, device_epoch)
    Returns: list of (ping_id, best_s_m, min_cross_track_m)
    """
    if not shape_pts or not pings:
        return []

    # Pre-extract polyline coordinates
    s_lats = np.array([p[1] for p in shape_pts])
    s_lons = np.array([p[2] for p in shape_pts])
    s_cums = np.array([p[3] for p in shape_pts])

    results = []
    mid_lat = np.mean(s_lats)
    cos_lat = math.cos(math.radians(mid_lat))
    kx = EARTH_RADIUS_M * cos_lat * (math.pi / 180.0)
    ky = EARTH_RADIUS_M * (math.pi / 180.0)

    # Segment endpoints in local projection
    x1 = s_lons[:-1] * kx
    y1 = s_lats[:-1] * ky
    x2 = s_lons[1:] * kx
    y2 = s_lats[1:] * ky

    dx = x2 - x1
    dy = y2 - y1
    seg_lens_sq = dx * dx + dy * dy
    seg_lens = np.sqrt(np.maximum(seg_lens_sq, 1e-12))
    safe_lens_sq = np.maximum(seg_lens_sq, 1e-6)
    cum_starts = s_cums[:-1]

    for ping_id, p_lat, p_lon, p_epoch in pings:
        px = p_lon * kx
        py = p_lat * ky

        # Vector from segment start to point
        p_dx1 = px - x1
        p_dy1 = py - y1

        # Project point onto each segment: t = (p_dx1 * dx + p_dy1 * dy) / safe_lens_sq
        t = (p_dx1 * dx + p_dy1 * dy) / safe_lens_sq
        t = np.nan_to_num(t, nan=0.0)
        t_clamped = np.clip(t, 0.0, 1.0)

        proj_x = x1 + t_clamped * dx
        proj_y = y1 + t_clamped * dy

        dist_sq = (px - proj_x) ** 2 + (py - proj_y) ** 2
        best_idx = np.argmin(dist_sq)

        min_dist_m = float(np.sqrt(dist_sq[best_idx]))
        best_s_m = float(cum_starts[best_idx] + t_clamped[best_idx] * seg_lens[best_idx])
        if math.isnan(best_s_m):
            best_s_m = float(cum_starts[best_idx])
        if math.isnan(min_dist_m):
            min_dist_m = 999.0

        results.append((ping_id, round(best_s_m, 2), round(min_dist_m, 2)))

    return results


def init_projected_telemetry_table(conn: sqlite3.Connection):
    """Ensure multi-route projected telemetry table and indices exist."""
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
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rpt_vehicle_epoch ON route_projected_telemetry (vehicle_id, device_epoch);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rpt_route_dir_s ON route_projected_telemetry (route_code, direction, s_bus_m);")
    conn.commit()


def project_route(route_code: str, conn: sqlite3.Connection) -> int:
    """Project all pings for a specific route onto TimBus official centerline."""
    cur = conn.cursor()

    # Find busmap_route_id
    r_info = cur.execute("SELECT busmap_route_id FROM dim_route_crosswalk WHERE route_code = ?", (route_code,)).fetchone()
    if not r_info or r_info[0] is None:
        return 0
    busmap_route_id = r_info[0]

    # Load shape points for both directions
    shapes = {"go": [], "re": []}
    for row in cur.execute("""
        SELECT direction, point_order, lat, lon, cum_distance_m 
        FROM timbus_shape_master 
        WHERE route_code = ? 
        ORDER BY direction, point_order
    """, (route_code,)).fetchall():
        d = row[0].lower()
        if d in shapes:
            shapes[d].append((row[1], row[2], row[3], row[4]))

    if not shapes["go"] and not shapes["re"]:
        return 0

    # Fetch unique pings for this route
    pings_query = """
    SELECT ping_id, vehicle_id, plate, device_update_time, device_epoch, direction, lat, lon
    FROM vehicle_unique_pings
    WHERE route_id = ? AND direction IN (0, 1) AND lat > 20.0 AND lon > 105.0
    ORDER BY vehicle_id, device_epoch;
    """
    pings = cur.execute(pings_query, (busmap_route_id,)).fetchall()
    if not pings:
        return 0

    # Separate pings by direction: 1 -> "go", 0 -> "re"
    pings_by_dir = {"go": [], "re": []}
    ping_meta = {}
    for p in pings:
        d_str = "go" if p[5] == 1 else "re"
        pings_by_dir[d_str].append((p[0], p[6], p[7], p[4]))
        ping_meta[p[0]] = p

    # Execute projection
    projected_results = {}
    for d_str in ["go", "re"]:
        if shapes[d_str] and pings_by_dir[d_str]:
            res = project_points_to_shape(pings_by_dir[d_str], shapes[d_str])
            for pid, s_m, d_perp in res:
                projected_results[pid] = (s_m, d_perp, d_str)

    # Calculate derived kinematics (delta_s / delta_t) per vehicle trajectory
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

                if 0 < dt <= 300 and d_str == prev_d_str:
                    v_mps = ds / dt
                    derived_speed_kmh = round(v_mps * 3.6, 2)
                    # Kinematic Dwell Condition: ds < 15m for dt >= 20s
                    if ds < 15.0 and dt >= 20.0:
                        is_dwell = 1

            records.append((
                pid,
                route_code,
                busmap_route_id,
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

    # Upsert into route_projected_telemetry
    cur.execute("DELETE FROM route_projected_telemetry WHERE route_code = ?", (route_code,))
    cur.executemany("""
    INSERT OR REPLACE INTO route_projected_telemetry (
        ping_id, route_code, route_id, vehicle_id, plate,
        device_update_time, device_epoch, direction,
        lat, lon, s_bus_m, cross_track_m, derived_speed_kmh, is_dwell
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """, records)
    conn.commit()

    return len(records)


def run_multi_route_projection(db_path: Optional[str] = None, limit: Optional[int] = None):
    """Run projection for all available routes."""
    if sys.stdout.encoding != 'utf-8':
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except Exception:
            pass

    conn = sqlite3.connect(db_path)
    init_projected_telemetry_table(conn)

    cur = conn.cursor()
    # Find all routes that have both shape and telemetry
    routes_query = """
    SELECT DISTINCT c.route_code, count(t.ping_id) as pings
    FROM dim_route_crosswalk c
    JOIN vehicle_unique_pings t ON c.busmap_route_id = t.route_id
    WHERE c.route_code IN (SELECT DISTINCT route_code FROM timbus_shape_master)
    GROUP BY c.route_code
    ORDER BY pings DESC;
    """
    routes = cur.execute(routes_query).fetchall()

    if limit:
        routes = routes[:limit]

    print("=" * 80)
    print(f"MULTI-ROUTE FRENET PROJECTION PIPELINE ({len(routes)} ROUTES)")
    print("=" * 80)

    total_projected = 0
    t0 = time.time()

    for idx, (rc, p_count) in enumerate(routes, start=1):
        print(f"[{idx:02d}/{len(routes)}] Projecting Route {rc:<6} ({p_count:,} pings)...", end=" ", flush=True)
        count = project_route(rc, conn)
        total_projected += count
        print(f"OK ({count:,} projected)")

    elapsed = time.time() - t0
    conn.close()

    print("=" * 80)
    print("MULTI-ROUTE PROJECTION SUMMARY:")
    print(f"- Total Routes Projected: {len(routes)}")
    print(f"- Total Pings Linear Referenced: {total_projected:,}")
    print(f"- Elapsed Time: {elapsed:.2f}s ({elapsed/len(routes):.2f}s per route)")
    print(f"- Target Table: route_projected_telemetry in {db_path}")
    print("=" * 80)


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else get_database_path()
    run_multi_route_projection(db)
