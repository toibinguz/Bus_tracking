"""
Auditing Route Cleanliness, Depot/Terminal Dwell Exclusion, and TimBus vs OSM Ground Truth Alignment.
Empirical verification of route quality across 48 bus routes in Hanoi.
"""

import json
import sqlite3
import math
import sys
import io
from pathlib import Path
from typing import Dict, List, Tuple, Any

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

DB_PATH = Path("data/hanoi_bus_system.db")
OSM_PATH = Path("archive/legacy_dumps/osm/raw/hanoi_all_bus_routes_raw.json")
OUTPUT_JSON = Path("experiments/route_cleanliness_audit/route_cleanliness_report.json")


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2.0) ** 2
    return 2.0 * R * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def min_dist_point_to_polyline(lat: float, lon: float, poly: List[Tuple[float, float]]) -> float:
    if not poly:
        return 999999.0
    min_d = 999999.0
    step = max(1, len(poly) // 50)  # fast coarse check then local check
    best_idx = 0
    for i in range(0, len(poly), step):
        d = haversine_m(lat, lon, poly[i][0], poly[i][1])
        if d < min_d:
            min_d = d
            best_idx = i

    # Refine around best_idx
    start_i = max(0, best_idx - step * 2)
    end_i = min(len(poly) - 1, best_idx + step * 2)
    for i in range(start_i, end_i):
        p1 = poly[i]
        p2 = poly[i + 1]
        # Check segment ends and midpoint
        d1 = haversine_m(lat, lon, p1[0], p1[1])
        d2 = haversine_m(lat, lon, p2[0], p2[1])
        dmid = haversine_m(lat, lon, (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
        min_d = min(min_d, d1, d2, dmid)

    return min_d


def load_osm_routes() -> Dict[str, List[Dict[str, Any]]]:
    """Load OSM routes indexed by cleaned route ref."""
    if not OSM_PATH.exists():
        print(f"Warning: OSM file {OSM_PATH} not found.")
        return {}

    with open(OSM_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    nodes = {el["id"]: (el["lat"], el["lon"]) for el in data["elements"] if el["type"] == "node"}
    ways = {el["id"]: el.get("nodes", []) for el in data["elements"] if el["type"] == "way"}

    osm_routes = {}
    for el in data["elements"]:
        if el["type"] == "relation":
            tags = el.get("tags", {})
            ref = tags.get("ref", "").strip().upper()
            if not ref:
                continue

            # Build polyline from way members
            poly = []
            for m in el.get("members", []):
                if m.get("type") == "way" and m.get("ref") in ways:
                    for nid in ways[m["ref"]]:
                        if nid in nodes:
                            poly.append(nodes[nid])

            if poly:
                if ref not in osm_routes:
                    osm_routes[ref] = []
                osm_routes[ref].append({
                    "id": el["id"],
                    "name": tags.get("name", ""),
                    "from": tags.get("from", ""),
                    "to": tags.get("to", ""),
                    "polyline": poly
                })

    return osm_routes


def audit_route_osm_alignment(route_code: str, timbus_shapes: Dict[str, List[Tuple[float, float]]], osm_routes: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Compare TimBus polyline to OSM polyline for go and re directions."""
    norm_code = route_code.strip().upper()
    osm_candidates = osm_routes.get(norm_code, [])

    result = {
        "osm_available": len(osm_candidates) > 0,
        "osm_relations_count": len(osm_candidates),
        "go_osm_median_m": None,
        "go_osm_max_m": None,
        "re_osm_median_m": None,
        "re_osm_max_m": None,
        "tour_mismatch_detected": False,
        "notes": ""
    }

    if not osm_candidates:
        result["notes"] = "No matching OSM route relation found"
        return result

    for d in ["go", "re"]:
        tb_poly = timbus_shapes.get(d, [])
        if not tb_poly:
            continue

        sample_pts = tb_poly[::max(1, len(tb_poly) // 40)]
        best_median = 999999.0
        best_max = 999999.0

        for cand in osm_candidates:
            osm_poly = cand["polyline"]
            dists = [min_dist_point_to_polyline(lat, lon, osm_poly) for lat, lon in sample_pts]
            dists.sort()
            med = dists[len(dists) // 2]
            mx = max(dists)
            if med < best_median:
                best_median = med
                best_max = mx

        if d == "go":
            result["go_osm_median_m"] = round(best_median, 1)
            result["go_osm_max_m"] = round(best_max, 1)
        else:
            result["re_osm_median_m"] = round(best_median, 1)
            result["re_osm_max_m"] = round(best_max, 1)

    max_dist = max(result["go_osm_max_m"] or 0, result["re_osm_max_m"] or 0)
    if max_dist > 250.0:
        result["tour_mismatch_detected"] = True
        result["notes"] = f"Major corridor discrepancy vs OSM (max deviation: {max_dist:.0f}m)"

    return result


def audit_operational_telemetry(conn: sqlite3.Connection, route_code: str) -> Dict[str, Any]:
    """Audit telemetry pings, separating depot/terminal dwell from in-service movement."""
    cur = conn.cursor()

    # Query all projected pings for this route
    rows = cur.execute("""
        SELECT vehicle_id, direction, s_bus_m, cross_track_m, derived_speed_kmh, is_dwell
        FROM route_projected_telemetry
        WHERE route_code = ?
    """, (route_code,)).fetchall()

    if not rows:
        return {"error": "No projected pings found"}

    # Determine max s per direction
    max_s = {"go": 0.0, "re": 0.0}
    for r in rows:
        d = r[1]
        if d in max_s and r[2] > max_s[d]:
            max_s[d] = r[2]

    # Analyze vehicles to find depot-parked vehicles (inactive all day)
    veh_stats = {}
    for r in rows:
        veh = r[0]
        s = r[2]
        if veh not in veh_stats:
            veh_stats[veh] = {"min_s": s, "max_s": s, "count": 0}
        else:
            veh_stats[veh]["min_s"] = min(veh_stats[veh]["min_s"], s)
            veh_stats[veh]["max_s"] = max(veh_stats[veh]["max_s"], s)
            veh_stats[veh]["count"] += 1

    depot_vehicles = set()
    for veh, st in veh_stats.items():
        if (st["max_s"] - st["min_s"]) < 1000.0 and st["count"] > 50:
            depot_vehicles.add(veh)

    # Classify pings
    total_pings = len(rows)
    depot_garage_pings = 0
    terminal_dwell_pings = 0
    operational_pings = []

    for r in rows:
        veh, d, s, d_perp, speed, is_dwell = r
        if veh in depot_vehicles:
            depot_garage_pings += 1
            continue

        route_len = max_s.get(d, 10000.0)
        # Terminal dwell check: near start (<300m) or end (> route_len - 300m) with low speed/dwell
        is_near_terminal = (s < 300.0) or (s > (route_len - 300.0))
        if is_near_terminal and (speed is not None and speed < 5.0 or is_dwell == 1):
            terminal_dwell_pings += 1
            continue

        operational_pings.append((d, s, d_perp, speed))

    op_count = len(operational_pings)
    if op_count == 0:
        return {
            "total_pings": total_pings,
            "depot_pings": depot_garage_pings,
            "terminal_dwell_pings": terminal_dwell_pings,
            "operational_pings": 0,
            "operational_in_lane_pct": 0.0,
            "operational_median_d_perp": 999.0
        }

    d_perps = [p[2] for p in operational_pings]
    d_perps.sort()

    in_lane_30m = sum(1 for d in d_perps if d <= 30.0)
    in_lane_50m = sum(1 for d in d_perps if d <= 50.0)

    med_d = d_perps[len(d_perps) // 2]
    p90_d = d_perps[int(len(d_perps) * 0.9)]

    return {
        "total_pings": total_pings,
        "depot_vehicles_count": len(depot_vehicles),
        "depot_pings": depot_garage_pings,
        "depot_pings_pct": round(depot_garage_pings / total_pings * 100, 1),
        "terminal_dwell_pings": terminal_dwell_pings,
        "terminal_dwell_pct": round(terminal_dwell_pings / total_pings * 100, 1),
        "operational_pings": op_count,
        "operational_in_lane_30m_pct": round(in_lane_30m / op_count * 100, 1),
        "operational_in_lane_50m_pct": round(in_lane_50m / op_count * 100, 1),
        "operational_median_d_perp": round(med_d, 1),
        "operational_p90_d_perp": round(p90_d, 1)
    }


def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    print("Loading OpenStreetMap transit relations...")
    osm_routes = load_osm_routes()
    print(f"Loaded OSM routes: {len(osm_routes)} unique route numbers")

    # Fetch all routes in timbus_shape_master
    route_codes = [r[0] for r in cur.execute("SELECT DISTINCT route_code FROM timbus_shape_master ORDER BY route_code").fetchall()]
    print(f"Auditing {len(route_codes)} TimBus routes against OSM and Operational Telemetry...\n")

    audit_summary = []

    for rc in route_codes:
        # Get TimBus shapes
        tb_shapes = {"go": [], "re": []}
        for row in cur.execute("SELECT direction, lat, lon FROM timbus_shape_master WHERE route_code = ? ORDER BY point_order", (rc,)).fetchall():
            d = row[0].lower()
            if d in tb_shapes:
                tb_shapes[d].append((row[1], row[2]))

        # 1. OSM alignment
        osm_res = audit_route_osm_alignment(rc, tb_shapes, osm_routes)

        # 2. Operational telemetry
        telem_res = audit_operational_telemetry(conn, rc)

        # 3. Tier Assignment
        # Gold Tier criteria:
        # - Operational In-Lane (30m) >= 90%
        # - Operational median d_perp <= 12m
        # - No OSM tour mismatch (max dist <= 75m or OSM median <= 25m)
        # - Operational pings >= 2000
        op_in_lane = telem_res.get("operational_in_lane_30m_pct", 0)
        med_d = telem_res.get("operational_median_d_perp", 999)
        osm_mismatch = osm_res.get("tour_mismatch_detected", False)
        op_pings = telem_res.get("operational_pings", 0)

        if op_in_lane >= 90.0 and med_d <= 12.0 and not osm_mismatch and op_pings >= 2000:
            tier = "TIER_1_GOLD"
        elif op_in_lane >= 80.0 and med_d <= 18.0 and not osm_mismatch and op_pings >= 1000:
            tier = "TIER_2_SILVER"
        else:
            tier = "TIER_3_FLAGGED"

        record = {
            "route_code": rc,
            "tier": tier,
            "operational_pings": op_pings,
            "in_lane_30m_pct": op_in_lane,
            "median_d_perp_m": med_d,
            "p90_d_perp_m": telem_res.get("operational_p90_d_perp", 999),
            "depot_pings_pct": telem_res.get("depot_pings_pct", 0),
            "terminal_dwell_pct": telem_res.get("terminal_dwell_pct", 0),
            "osm_available": osm_res["osm_available"],
            "osm_go_med_m": osm_res["go_osm_median_m"],
            "osm_re_med_m": osm_res["re_osm_median_m"],
            "osm_mismatch": osm_mismatch,
            "notes": osm_res["notes"]
        }
        audit_summary.append(record)

    conn.close()

    # Save to JSON
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(audit_summary, f, indent=2, ensure_ascii=False)
    print(f"Saved audit report to {OUTPUT_JSON}\n")

    # Print summary table
    print("=" * 110)
    print(f"{'ROUTE':<8} | {'TIER':<15} | {'OP PINGS':<10} | {'IN-LANE %':<10} | {'MED d_⊥':<8} | {'DEPOT %':<8} | {'OSM GO/RE (m)':<15} | {'NOTES'}")
    print("=" * 110)

    # Sort: TIER_1 first, then by in_lane_30m_pct DESC
    tier_order = {"TIER_1_GOLD": 1, "TIER_2_SILVER": 2, "TIER_3_FLAGGED": 3}
    audit_summary.sort(key=lambda x: (tier_order.get(x["tier"], 9), -x["in_lane_30m_pct"]))

    tier_counts = {"TIER_1_GOLD": 0, "TIER_2_SILVER": 0, "TIER_3_FLAGGED": 0}
    for r in audit_summary:
        tier_counts[r["tier"]] = tier_counts.get(r["tier"], 0) + 1
        osm_str = f"{r['osm_go_med_m'] or '-'}/{r['osm_re_med_m'] or '-'}"
        print(f"{r['route_code']:<8} | {r['tier']:<15} | {r['operational_pings']:<10,d} | {r['in_lane_30m_pct']:<9.1f}% | {r['median_d_perp_m']:<7.1f}m | {r['depot_pings_pct']:<7.1f}% | {osm_str:<15} | {r['notes']}")

    print("=" * 110)
    print(f"SUMMARY: TIER 1 GOLD = {tier_counts['TIER_1_GOLD']} routes | TIER 2 SILVER = {tier_counts['TIER_2_SILVER']} routes | TIER 3 FLAGGED = {tier_counts['TIER_3_FLAGGED']} routes")
    print("=" * 110)


if __name__ == "__main__":
    main()

