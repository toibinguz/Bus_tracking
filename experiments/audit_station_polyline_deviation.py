"""
audit_station_polyline_deviation.py
------------------------------------
Audits the perpendicular deviation (d_perp) between all bus stations and their
corresponding canonical route shape polylines from `data/hanoi_bus_system.db`.

Identifies:
1. Overall system compliance with the 35.0m corridor threshold (d_perp <= 35m vs > 35m).
2. Detailed audit of Route E11 (both 'go' and 're' directions) showing station deviations.
3. Top routes and stations exhibiting extreme spatial displacement from their centerlines.
4. Outputs comprehensive JSON audit report to `experiments/station_polyline_deviation_report.json`.
"""

import os
import sys
import math
import json
import sqlite3
import numpy as np
from typing import Dict, List, Tuple, Any

# Ensure parent directory is in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from config.system_config import (
    DEFAULT_DB_PATH,
    METERS_PER_DEG_LON_EQUATOR,
    METERS_PER_DEG_LAT,
    MAX_CORRIDOR_CROSS_TRACK_M,
)

REPORT_JSON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "station_polyline_deviation_report.json")


def load_canonical_data(db_path: str):
    """
    Loads stations and shapes from SQLite database.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Load shapes grouped by (route_code, direction)
    cur.execute("""
        SELECT route_code, direction, point_order, lat, lon, cum_distance_m
        FROM canonical_shape_master
        ORDER BY route_code, direction, point_order
    """)
    shapes_by_route: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for row in cur.fetchall():
        key = (row["route_code"], row["direction"])
        if key not in shapes_by_route:
            shapes_by_route[key] = []
        shapes_by_route[key].append({
            "point_order": row["point_order"],
            "lat": float(row["lat"]),
            "lon": float(row["lon"]),
            "cum_distance_m": float(row["cum_distance_m"]) if row["cum_distance_m"] is not None else 0.0,
        })

    # Load stations
    cur.execute("""
        SELECT route_code, direction, station_order, station_id, station_name, lat, lon, cum_distance_m, snap_dist_m
        FROM canonical_station_master
        ORDER BY route_code, direction, station_order
    """)
    stations_by_route: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for row in cur.fetchall():
        key = (row["route_code"], row["direction"])
        if key not in stations_by_route:
            stations_by_route[key] = []
        stations_by_route[key].append({
            "station_order": row["station_order"],
            "station_id": row["station_id"],
            "station_name": row["station_name"],
            "lat": float(row["lat"]),
            "lon": float(row["lon"]),
            "cum_distance_m": float(row["cum_distance_m"]) if row["cum_distance_m"] is not None else 0.0,
            "snap_dist_m": float(row["snap_dist_m"]) if row["snap_dist_m"] is not None else 0.0,
        })

    conn.close()
    return shapes_by_route, stations_by_route


def compute_min_perpendicular_distance(
    station_lat: float,
    station_lon: float,
    shape_pts: List[Dict[str, Any]],
    kx: float,
    ky: float,
    x1: np.ndarray,
    y1: np.ndarray,
    dx: np.ndarray,
    dy: np.ndarray,
    safe_lens_sq: np.ndarray,
    cum_starts: np.ndarray,
    seg_lens: np.ndarray,
) -> Tuple[float, float, int]:
    """
    Computes minimum perpendicular distance (d_perp in meters) and along-track s (meters)
    from a station point to all segments of a polyline on a tangent metric plane.
    """
    px = station_lon * kx
    py = station_lat * ky

    p_dx1 = px - x1
    p_dy1 = py - y1

    # Segment parameter t in [0.0, 1.0]
    t = np.clip((p_dx1 * dx + p_dy1 * dy) / safe_lens_sq, 0.0, 1.0)
    proj_x = x1 + t * dx
    proj_y = y1 + t * dy

    dist_sq = (px - proj_x) ** 2 + (py - proj_y) ** 2
    best_seg_idx = int(np.argmin(dist_sq))
    min_d = float(math.sqrt(dist_sq[best_seg_idx]))

    best_t = float(t[best_seg_idx])
    s_along = float(cum_starts[best_seg_idx] + best_t * seg_lens[best_seg_idx])

    return min_d, s_along, best_seg_idx


def audit_system(db_path: str = None):
    if db_path is None:
        db_path = os.path.join(BASE_DIR, DEFAULT_DB_PATH)
    print("=" * 80)
    print("HANOI BUS CANONICAL SPATIAL AUDIT: STATION vs. POLYLINE CENTERLINE")
    print("=" * 80)
    print(f"Target Database: {db_path}")

    shapes_by_route, stations_by_route = load_canonical_data(db_path)
    print(f"Loaded {len(shapes_by_route)} route-direction polylines.")
    total_stations_raw = sum(len(st_list) for st_list in stations_by_route.values())
    print(f"Loaded {total_stations_raw} canonical stations across all routes.\n")

    all_station_audits: List[Dict[str, Any]] = []
    routes_summary: Dict[str, Dict[str, Any]] = {}

    for (route_code, direction), stations in stations_by_route.items():
        shapes = shapes_by_route.get((route_code, direction), [])
        if not shapes or len(shapes) < 2:
            print(f"WARNING: Route {route_code} [{direction}] has insufficient shape points ({len(shapes)}). Skipping.")
            continue

        s_lats = np.array([p["lat"] for p in shapes], dtype=np.float64)
        s_lons = np.array([p["lon"] for p in shapes], dtype=np.float64)
        s_cums = np.array([p["cum_distance_m"] for p in shapes], dtype=np.float64)

        mean_lat = float(np.mean(s_lats))
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

        if route_code not in routes_summary:
            routes_summary[route_code] = {
                "route_code": route_code,
                "total_stations": 0,
                "stations_le_35m": 0,
                "stations_gt_35m": 0,
                "d_perp_values": [],
                "max_d_perp": 0.0,
                "directions": {"go": {"total": 0, "gt_35m": 0}, "re": {"total": 0, "gt_35m": 0}},
            }

        route_stats = routes_summary[route_code]

        for st in stations:
            d_perp, s_along, best_seg = compute_min_perpendicular_distance(
                st["lat"], st["lon"], shapes, kx, ky, x1, y1, dx, dy, safe_lens_sq, cum_starts, seg_lens
            )

            audit_item = {
                "route_code": route_code,
                "direction": direction,
                "station_order": st["station_order"],
                "station_id": st["station_id"],
                "station_name": st["station_name"],
                "lat": st["lat"],
                "lon": st["lon"],
                "d_perp_m": round(d_perp, 2),
                "s_along_m": round(s_along, 1),
                "db_cum_distance_m": round(st["cum_distance_m"], 1),
                "db_snap_dist_m": round(st["snap_dist_m"], 1),
                "exceeds_35m": bool(d_perp > MAX_CORRIDOR_CROSS_TRACK_M),
            }
            all_station_audits.append(audit_item)

            route_stats["total_stations"] += 1
            route_stats["directions"][direction]["total"] += 1
            route_stats["d_perp_values"].append(d_perp)
            if d_perp > route_stats["max_d_perp"]:
                route_stats["max_d_perp"] = d_perp

            if d_perp <= MAX_CORRIDOR_CROSS_TRACK_M:
                route_stats["stations_le_35m"] += 1
            else:
                route_stats["stations_gt_35m"] += 1
                route_stats["directions"][direction]["gt_35m"] += 1

    # System-level metrics
    total_stations = len(all_station_audits)
    le_35m_count = sum(1 for item in all_station_audits if not item["exceeds_35m"])
    gt_35m_count = sum(1 for item in all_station_audits if item["exceeds_35m"])
    pct_le_35m = (le_35m_count / total_stations * 100.0) if total_stations > 0 else 0.0
    pct_gt_35m = (gt_35m_count / total_stations * 100.0) if total_stations > 0 else 0.0

    all_d_perps = [item["d_perp_m"] for item in all_station_audits]
    mean_d_perp = float(np.mean(all_d_perps)) if all_d_perps else 0.0
    median_d_perp = float(np.median(all_d_perps)) if all_d_perps else 0.0
    max_d_perp = float(np.max(all_d_perps)) if all_d_perps else 0.0
    p90_d_perp = float(np.percentile(all_d_perps, 90)) if all_d_perps else 0.0
    p95_d_perp = float(np.percentile(all_d_perps, 95)) if all_d_perps else 0.0
    p99_d_perp = float(np.percentile(all_d_perps, 99)) if all_d_perps else 0.0

    print("=" * 80)
    print("GLOBAL SYSTEM AUDIT RESULTS (Threshold = 35.0 meters)")
    print("=" * 80)
    print(f"Total Stations Audited       : {total_stations:,}")
    print(f"Stations within <= 35.0m     : {le_35m_count:,} ({pct_le_35m:.2f}%)")
    print(f"Stations exceeding > 35.0m   : {gt_35m_count:,} ({pct_gt_35m:.2f}%)")
    print(f"d_perp Distribution (meters) : Mean={mean_d_perp:.2f}m | Median={median_d_perp:.2f}m | P90={p90_d_perp:.2f}m | P95={p95_d_perp:.2f}m | P99={p99_d_perp:.2f}m | Max={max_d_perp:.2f}m")
    print("=" * 80)

    # Route E11 Detailed Focus
    e11_items = [item for item in all_station_audits if item["route_code"] == "E11"]
    e11_go = [item for item in e11_items if item["direction"] == "go"]
    e11_re = [item for item in e11_items if item["direction"] == "re"]

    e11_go_gt = [item for item in e11_go if item["exceeds_35m"]]
    e11_re_gt = [item for item in e11_re if item["exceeds_35m"]]

    print("\n" + "=" * 80)
    print(f"ROUTE E11 AUDIT BREAKDOWN (Total: {len(e11_items)} stations)")
    print("=" * 80)
    print(f"Direction 'go' (Outbound): {len(e11_go)} stations, {len(e11_go_gt)} exceed > 35m ({len(e11_go_gt)/len(e11_go)*100:.1f}%)")
    if e11_go_gt:
        print(f"  {'Ord':>4} | {'Station ID':>10} | {'d_perp (m)':>10} | {'snap_dist (m)':>13} | Station Name")
        print("  " + "-" * 75)
        for item in e11_go_gt:
            print(f"  {item['station_order']:>4} | {item['station_id']:>10} | {item['d_perp_m']:>10.1f} | {item['db_snap_dist_m']:>13.1f} | {item['station_name']}")

    print(f"\nDirection 're' (Inbound): {len(e11_re)} stations, {len(e11_re_gt)} exceed > 35m ({len(e11_re_gt)/len(e11_re)*100:.1f}%)")
    if e11_re_gt:
        print(f"  {'Ord':>4} | {'Station ID':>10} | {'d_perp (m)':>10} | {'snap_dist (m)':>13} | Station Name")
        print("  " + "-" * 75)
        for item in e11_re_gt:
            print(f"  {item['station_order']:>4} | {item['station_id']:>10} | {item['d_perp_m']:>10.1f} | {item['db_snap_dist_m']:>13.1f} | {item['station_name']}")

    # Route-level ranking: Top routes by number and % of stations exceeding 35m
    route_report_list = []
    for r_code, r_data in routes_summary.items():
        vals = r_data["d_perp_values"]
        tot = r_data["total_stations"]
        gt = r_data["stations_gt_35m"]
        route_report_list.append({
            "route_code": r_code,
            "total_stations": tot,
            "stations_le_35m": r_data["stations_le_35m"],
            "stations_gt_35m": gt,
            "pct_gt_35m": round((gt / tot * 100.0) if tot > 0 else 0.0, 2),
            "mean_d_perp_m": round(float(np.mean(vals)), 2) if vals else 0.0,
            "median_d_perp_m": round(float(np.median(vals)), 2) if vals else 0.0,
            "max_d_perp_m": round(r_data["max_d_perp"], 2),
            "go_total": r_data["directions"]["go"]["total"],
            "go_gt_35m": r_data["directions"]["go"]["gt_35m"],
            "re_total": r_data["directions"]["re"]["total"],
            "re_gt_35m": r_data["directions"]["re"]["gt_35m"],
        })

    # Sort routes by stations_gt_35m descending, then max_d_perp_m descending
    top_routes_by_deviation = sorted(route_report_list, key=lambda x: (x["stations_gt_35m"], x["max_d_perp_m"]), reverse=True)

    print("\n" + "=" * 80)
    print("TOP 15 ROUTES WITH MOST STATIONS EXCEEDING 35m")
    print("=" * 80)
    print(f"{'Route':<8} | {'Total St':>8} | {'> 35m Count':>11} | {'> 35m %':>8} | {'Mean d_perp':>11} | {'Max d_perp':>10} | {'Go gt/tot':>10} | {'Re gt/tot':>10}")
    print("-" * 88)
    for r in top_routes_by_deviation[:15]:
        print(f"{r['route_code']:<8} | {r['total_stations']:>8} | {r['stations_gt_35m']:>11} | {r['pct_gt_35m']:>7.1f}% | {r['mean_d_perp_m']:>10.1f}m | {r['max_d_perp_m']:>9.1f}m | {r['go_gt_35m']:>3}/{r['go_total']:<4} | {r['re_gt_35m']:>3}/{r['re_total']:<4}")

    # Top 20 worst deviating stations across the entire system
    top_worst_stations = sorted(all_station_audits, key=lambda x: x["d_perp_m"], reverse=True)[:25]
    print("\n" + "=" * 80)
    print("TOP 25 STATIONS WITH LARGEST PERPENDICULAR DISTANCE TO POLYLINE (SYSTEM-WIDE)")
    print("=" * 80)
    print(f"{'Route':<6} | {'Dir':<3} | {'Ord':>3} | {'St ID':>8} | {'d_perp (m)':>10} | {'snap_dist':>10} | Station Name")
    print("-" * 88)
    for st in top_worst_stations:
        print(f"{st['route_code']:<6} | {st['direction']:<3} | {st['station_order']:>3} | {st['station_id']:>8} | {st['d_perp_m']:>10.1f} | {st['db_snap_dist_m']:>10.1f} | {st['station_name']}")

    # Save to JSON
    json_output = {
        "metadata": {
            "db_path": db_path,
            "threshold_meters": MAX_CORRIDOR_CROSS_TRACK_M,
            "total_routes_audited": len(route_report_list),
            "total_stations_audited": total_stations,
        },
        "system_summary": {
            "total_stations": total_stations,
            "stations_le_35m": le_35m_count,
            "pct_le_35m": round(pct_le_35m, 2),
            "stations_gt_35m": gt_35m_count,
            "pct_gt_35m": round(pct_gt_35m, 2),
            "mean_d_perp_m": round(mean_d_perp, 2),
            "median_d_perp_m": round(median_d_perp, 2),
            "p90_d_perp_m": round(p90_d_perp, 2),
            "p95_d_perp_m": round(p95_d_perp, 2),
            "p99_d_perp_m": round(p99_d_perp, 2),
            "max_d_perp_m": round(max_d_perp, 2),
        },
        "route_e11_focus": {
            "total_stations": len(e11_items),
            "stations_gt_35m": len(e11_go_gt) + len(e11_re_gt),
            "pct_gt_35m": round((len(e11_go_gt) + len(e11_re_gt)) / len(e11_items) * 100.0, 2) if e11_items else 0.0,
            "go_direction": {
                "total_stations": len(e11_go),
                "stations_gt_35m": len(e11_go_gt),
                "deviating_stations": e11_go_gt,
            },
            "re_direction": {
                "total_stations": len(e11_re),
                "stations_gt_35m": len(e11_re_gt),
                "deviating_stations": e11_re_gt,
            },
        },
        "top_deviating_routes": top_routes_by_deviation[:30],
        "all_routes_summary": top_routes_by_deviation,
        "top_worst_stations_systemwide": top_worst_stations,
    }

    with open(REPORT_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(json_output, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 80)
    print(f"Successfully generated detailed report -> {REPORT_JSON_PATH}")
    print("=" * 80)


if __name__ == "__main__":
    audit_system()
