"""
Audits the newly projected Canonical Telemetry across all 48 routes.
Compares in-lane adherence, median cross-track error, and station alignment.
"""

import json
import sqlite3
import math
import sys
import io
from pathlib import Path

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

DB_PATH = Path("data/hanoi_bus_system.db")
OUTPUT_JSON = Path("experiments/route_cleanliness_audit/canonical_audit_report.json")


def audit_operational_telemetry(conn: sqlite3.Connection, route_id: int, route_code: str):
    cur = conn.cursor()

    rows = cur.execute("""
        SELECT vehicle_id, direction, s_bus_m, cross_track_m, derived_speed_kmh, is_dwell
        FROM route_projected_telemetry
        WHERE route_id = ?
    """, (route_id,)).fetchall()

    if not rows:
        return None

    # Max s per direction
    max_s = {"go": 0.0, "re": 0.0}
    for r in rows:
        d = r[1]
        if d in max_s and r[2] > max_s[d]:
            max_s[d] = r[2]

    # Find depot-parked vehicles (minimal daily movement)
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

    total_pings = len(rows)
    depot_pings = 0
    terminal_dwell = 0
    operational_pings = []

    for r in rows:
        veh, d, s, d_perp, speed, is_dwell = r
        if veh in depot_vehicles:
            depot_pings += 1
            continue

        route_len = max_s.get(d, 10000.0)
        is_near_term = (s < 300.0) or (s > (route_len - 300.0))
        if is_near_term and (speed is not None and speed < 5.0 or is_dwell == 1):
            terminal_dwell += 1
            continue

        operational_pings.append((d, s, d_perp, speed))

    op_cnt = len(operational_pings)
    if op_cnt == 0:
        return {
            "route_code": route_code,
            "route_id": route_id,
            "total_pings": total_pings,
            "operational_pings": 0,
            "in_lane_30m_pct": 0.0,
            "in_lane_15m_pct": 0.0,
            "median_d_perp": 999.0,
            "p90_d_perp": 999.0
        }

    dperps = sorted([p[2] for p in operational_pings])
    med_d = dperps[len(dperps) // 2]
    p90_d = dperps[int(len(dperps) * 0.9)]
    in_30 = sum(1 for d in dperps if d <= 30.0) / op_cnt * 100
    in_15 = sum(1 for d in dperps if d <= 15.0) / op_cnt * 100

    return {
        "route_code": route_code,
        "route_id": route_id,
        "total_pings": total_pings,
        "depot_pings": depot_pings,
        "terminal_dwell": terminal_dwell,
        "operational_pings": op_cnt,
        "in_lane_30m_pct": round(in_30, 1),
        "in_lane_15m_pct": round(in_15, 1),
        "median_d_perp": round(med_d, 1),
        "p90_d_perp": round(p90_d, 1)
    }


def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        SELECT DISTINCT r.route_id, r.route_code
        FROM canonical_route_master r
        JOIN route_projected_telemetry t ON r.route_id = t.route_id
        ORDER BY r.route_code;
    """)
    routes = cur.fetchall()

    print(f"Auditing {len(routes)} Projected Routes against Canonical Master...\n")
    results = []

    for r_id, r_code in routes:
        res = audit_operational_telemetry(conn, r_id, r_code)
        if res:
            results.append(res)

    conn.close()

    # Sort by in_lane_30m_pct descending
    results.sort(key=lambda x: -x["in_lane_30m_pct"])

    # Print summary table
    print("=" * 95)
    print(f"{'ROUTE':<8} | {'ID':<6} | {'TOTAL PINGS':<12} | {'OP PINGS':<10} | {'IN-LANE <=30m':<14} | {'<=15m':<10} | {'MEDIAN d_perp':<12} | {'P90 d_perp'}")
    print("=" * 95)

    gold_cnt = 0
    silver_cnt = 0
    flagged_cnt = 0

    for r in results:
        pct = r["in_lane_30m_pct"]
        if pct >= 88.0 and r["median_d_perp"] <= 10.0:
            tier = "GOLD"
            gold_cnt += 1
        elif pct >= 75.0 and r["median_d_perp"] <= 18.0:
            tier = "SILVER"
            silver_cnt += 1
        else:
            tier = "FLAGGED"
            flagged_cnt += 1

        print(f"{r['route_code']:<8} | {r['route_id']:<6} | {r['total_pings']:<12,d} | {r['operational_pings']:<10,d} | {r['in_lane_30m_pct']:>13.1f}% | {r['in_lane_15m_pct']:>8.1f}% | {r['median_d_perp']:>10.1f}m | {r['p90_d_perp']:>9.1f}m")

    print("=" * 95)
    print(f"SUMMARY: GOLD = {gold_cnt} routes | SILVER = {silver_cnt} routes | FLAGGED = {flagged_cnt} routes")
    print("=" * 95)

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"Saved audit report to {OUTPUT_JSON}")


if __name__ == "__main__":
    main()

