"""
Test & Benchmark Monotonic Frenet Projection & Direction Fix
Route 02 and Route 27 empirical validation.
Tests:
1. Direction mapping: 0 -> go, 1 -> re, -1 -> quarantine/depot
2. Monotonicity guard with sliding search window
3. Comparison of backward jumps (< -50m) and off-corridor pings (> 35m) before vs after
"""

import sqlite3
import numpy as np
import time
import math
import sys
from pathlib import Path
from typing import List, Tuple, Dict, Any

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

DB_PATH = "data/hanoi_bus_system.db"


def project_points_monotonic(
    vehicle_pings: List[Tuple[int, float, float, float]],  # (pid, lat, lon, epoch)
    shape_pts: List[Tuple[float, float, float]]            # (pt_order, lat, lon, cum_distance_m)
) -> List[Tuple[int, float, float]]:
    """
    Monotonic forward-constrained orthogonal projection of GPS points onto polyline segments.
    vehicle_pings must be for a SINGLE vehicle and sorted chronologically by epoch.
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
    seg_lens = np.sqrt(seg_lens_sq)
    cum_starts = s_cums[:-1]
    n_segs = len(dx)

    results = []
    prev_s = None
    prev_epoch = None

    for ping_id, p_lat, p_lon, p_epoch in vehicle_pings:
        px = p_lon * kx
        py = p_lat * ky

        # Determine segment search window
        use_window = False
        if prev_s is not None and prev_epoch is not None:
            dt = p_epoch - prev_epoch
            if 0 < dt <= 300.0:
                # Max plausible movement in dt seconds at 80 km/h (22.2 m/s) + 50m buffer
                max_forward = max(1500.0, dt * 25.0)
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
            t = (p_dx1 * sub_dx + p_dy1 * sub_dy) / sub_safe_lens_sq
            t = np.clip(t, 0.0, 1.0)
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

        # Global search fallback
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
        prev_s = best_s
        prev_epoch = p_epoch

    return results


def test_route(route_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Load canonical shapes
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

    # Load unambiguous stations
    cur.execute("""
        SELECT station_id, MIN(direction)
        FROM canonical_station_master
        WHERE route_id = ?
        GROUP BY station_id
        HAVING COUNT(DISTINCT direction) = 1;
    """, (route_id,))
    st_dir = {st_id: d for st_id, d in cur.fetchall()}

    # Load pings
    cur.execute("""
        SELECT ping_id, vehicle_id, plate, device_update_time, device_epoch, direction, lat, lon, current_station_id
        FROM vehicle_unique_pings
        WHERE route_id = ? AND lat > 20.0 AND lon > 105.0
        ORDER BY vehicle_id, device_epoch;
    """, (route_id,))
    pings = cur.fetchall()
    conn.close()

    print(f"\n=======================================================")
    print(f"TESTING ROUTE {route_id} - Total raw pings: {len(pings):,}")
    print(f"=======================================================")

    # Group pings by vehicle and resolved direction
    # Correct GTFS mapping: 0 -> go, 1 -> re
    # -1: check st_dir; if not found or curr_st == 0 -> depot quarantine
    pings_by_veh_dir = {}
    quarantined = 0

    for p in pings:
        pid, vid, plate, t_str, epoch, p_dir, lat, lon, curr_st = p
        d_str = None
        if curr_st and curr_st in st_dir:
            d_str = st_dir[curr_st]
        elif p_dir == 0:
            d_str = "go"
        elif p_dir == 1:
            d_str = "re"
        else:
            # p_dir == -1 and no unambiguous station -> Quarantine!
            quarantined += 1
            continue

        pings_by_veh_dir.setdefault((vid, d_str), []).append((pid, lat, lon, epoch))

    print(f"Quarantined depot/off-duty pings (dir=-1, no station): {quarantined:,} ({quarantined/len(pings)*100:.2f}%)")

    # Run monotonic projection
    t0 = time.time()
    all_results = []
    backward_jumps = 0
    on_corridor_count = 0
    huge_divergence_count = 0

    for (vid, d_str), v_pings in pings_by_veh_dir.items():
        if not shapes.get(d_str):
            continue
        v_pings.sort(key=lambda x: x[3])  # sort by epoch
        proj_res = project_points_monotonic(v_pings, shapes[d_str])

        # Audit continuity
        for i in range(len(proj_res)):
            pid, s, dperp = proj_res[i]
            if dperp <= 35.0:
                on_corridor_count += 1
            if dperp > 1000.0:
                huge_divergence_count += 1

            if i > 0:
                dt = v_pings[i][3] - v_pings[i - 1][3]
                ds = s - proj_res[i - 1][1]
                if dt <= 300.0 and ds < -50.0:
                    backward_jumps += 1

        all_results.extend(proj_res)

    elapsed = time.time() - t0
    total_proj = len(all_results)
    print(f"Projected {total_proj:,} pings in {elapsed:.2f}s ({total_proj/elapsed:,.0f} pings/s)")
    print(f"On-corridor pings (d_perp <= 35m)       : {on_corridor_count:,} ({on_corridor_count/total_proj*100:.2f}%)")
    print(f"Huge divergence pings (d_perp > 1000m)   : {huge_divergence_count:,} ({huge_divergence_count/total_proj*100:.2f}%)")
    print(f"Backward jumps (dt <= 300s, ds < -50m)   : {backward_jumps:,} ({backward_jumps/total_proj*100:.4f}%)")


if __name__ == "__main__":
    test_route(2)   # Route 02
    test_route(27)  # Route 27

