"""
Definitive Kinematic Audit: Isolating Active Running from Stationary Layovers & Night Parking.
Complies with AGENTS.md Constitution (Rule 1: Empirical Verification, Rule 5: Derived Kinematics).
"""

import sys
import json
import sqlite3
from pathlib import Path
from collections import defaultdict

DB_PATH = Path("data/hanoi_bus_system.db")
OUTPUT_JSON = Path("experiments/route_cleanliness_audit/canonical_kinematic_audit_report.json")

def classify_vehicle_pings(pings):
    """
    pings: list of (epoch, update_time, s, cross_track, speed, is_dwell) sorted by epoch.
    Returns: (running_pings, layover_pings, night_pings)
    """
    n = len(pings)
    running = []
    layover = []
    night = []

    for i in range(n):
        epoch, t_str, s, d_perp, speed, is_dwell = pings[i]
        t_hm = t_str[11:16] if len(t_str) >= 16 else "12:00"

        # Check Night Window (21:45 to 05:15)
        is_night_time = (t_hm >= "21:45" or t_hm < "05:15")

        # Rolling 3.5 minute window (+/- 105s -> 210s total)
        # Find all pings in [epoch - 105, epoch + 105]
        w_s = []
        for j in range(max(0, i - 8), min(n, i + 9)):
            if abs(pings[j][0] - epoch) <= 105:
                w_s.append(pings[j][2])

        s_span = (max(w_s) - min(w_s)) if w_s else 0.0

        # Classification logic:
        if is_night_time:
            # At night, if not actively moving fast along route, it's night dwell/parked
            if s_span < 40.0 or (speed is not None and speed < 8.0):
                night.append((s, d_perp, speed))
                continue
            else:
                running.append((s, d_perp, speed))
                continue

        # Daytime:
        # If the vehicle stayed in a < 25m radius for the entire ~3.5 min window with >= 3 pings,
        # it is prolonged intermediate layover, depot parking, or deadhead wait.
        if len(w_s) >= 3 and s_span < 25.0 and (speed is None or speed < 5.0):
            layover.append((s, d_perp, speed))
        else:
            running.append((s, d_perp, speed))

    return running, layover, night


def audit_route(conn, route_id, route_code):
    cur = conn.cursor()
    rows = cur.execute("""
        SELECT vehicle_id, device_epoch, device_update_time, s_bus_m, cross_track_m, derived_speed_kmh, is_dwell
        FROM route_projected_telemetry
        WHERE route_id = ?
        ORDER BY vehicle_id, device_epoch;
    """, (route_id,)).fetchall()

    if not rows:
        return None

    veh_pings = defaultdict(list)
    for r in rows:
        veh_pings[r[0]].append(r[1:])

    all_running = []
    all_layover = []
    all_night = []

    for vid, p_list in veh_pings.items():
        r, l, n = classify_vehicle_pings(p_list)
        all_running.extend(r)
        all_layover.extend(l)
        all_night.extend(n)

    total_pings = len(rows)
    run_cnt = len(all_running)
    lay_cnt = len(all_layover)
    night_cnt = len(all_night)

    def compute_metrics(pings_list):
        if not pings_list:
            return {"count": 0, "in_30_pct": 0.0, "in_15_pct": 0.0, "median_d": 999.0, "p90_d": 999.0}
        d_sorted = sorted([p[1] for p in pings_list])
        cnt = len(d_sorted)
        in_30 = sum(1 for d in d_sorted if d <= 30.0) / cnt * 100.0
        in_15 = sum(1 for d in d_sorted if d <= 15.0) / cnt * 100.0
        med = d_sorted[cnt // 2]
        p90 = d_sorted[int(cnt * 0.9)]
        return {
            "count": cnt,
            "in_30_pct": round(in_30, 1),
            "in_15_pct": round(in_15, 1),
            "median_d": round(med, 1),
            "p90_d": round(p90, 1)
        }

    run_stats = compute_metrics(all_running)
    lay_stats = compute_metrics(all_layover)
    night_stats = compute_metrics(all_night)
    overall_stats = compute_metrics([(r[3], r[4], r[5]) for r in rows])

    # Quality Tier based on RUNNING pings:
    # GOLD: >= 88.0% in-lane <=30m and median <= 10.0m
    # SILVER: >= 75.0% in-lane <=30m and median <= 18.0m
    # BRONZE / FLAGGED: rest
    if run_stats["in_30_pct"] >= 88.0 and run_stats["median_d"] <= 10.0:
        tier = "GOLD"
    elif run_stats["in_30_pct"] >= 75.0 and run_stats["median_d"] <= 18.0:
        tier = "SILVER"
    else:
        tier = "BRONZE"

    return {
        "route_code": route_code,
        "route_id": route_id,
        "tier": tier,
        "total_pings": total_pings,
        "running": run_stats,
        "layover": lay_stats,
        "night": night_stats,
        "overall": overall_stats
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

    print(f"Auditing Kinematic Running States for {len(routes)} Routes...\n")
    results = []

    for r_id, r_code in routes:
        res = audit_route(conn, r_id, r_code)
        if res:
            results.append(res)

    conn.close()

    # Sort by running in_30_pct desc
    results.sort(key=lambda x: -x["running"]["in_30_pct"])

    print("=" * 115)
    print(f"{'TIER':<6} | {'ROUTE':<8} | {'TOTAL':<8} | {'RUNNING':<8} | {'RUN <=30m':<10} | {'RUN <=15m':<10} | {'MED d_perp':<10} | {'P90 d_perp':<10} | {'LAYOVER MED':<11} | {'NIGHT MED'}")
    print("=" * 115)

    gold_cnt = 0
    silver_cnt = 0
    bronze_cnt = 0

    total_fleet_pings = 0
    total_fleet_running = 0
    total_fleet_layover = 0
    total_fleet_night = 0

    for r in results:
        tier = r["tier"]
        if tier == "GOLD":
            gold_cnt += 1
        elif tier == "SILVER":
            silver_cnt += 1
        else:
            bronze_cnt += 1

        total_fleet_pings += r["total_pings"]
        total_fleet_running += r["running"]["count"]
        total_fleet_layover += r["layover"]["count"]
        total_fleet_night += r["night"]["count"]

        run = r["running"]
        lay = r["layover"]
        nit = r["night"]

        print(f"{tier:<6} | {r['route_code']:<8} | {r['total_pings']:<8,d} | {run['count']:<8,d} | {run['in_30_pct']:>8.1f}% | {run['in_15_pct']:>8.1f}% | {run['median_d']:>8.1f}m | {run['p90_d']:>8.1f}m | {lay['median_d']:>9.1f}m | {nit['median_d']:>9.1f}m")

    print("=" * 115)
    print(f"FLEET TOTAL: {total_fleet_pings:,d} pings")
    print(f"  - Active Running: {total_fleet_running:,d} ({total_fleet_running/total_fleet_pings*100:.1f}%)")
    print(f"  - Day Layover:    {total_fleet_layover:,d} ({total_fleet_layover/total_fleet_pings*100:.1f}%)")
    print(f"  - Night Park:     {total_fleet_night:,d} ({total_fleet_night/total_fleet_pings*100:.1f}%)")
    print(f"TIER SUMMARY: GOLD = {gold_cnt} routes | SILVER = {silver_cnt} routes | BRONZE = {bronze_cnt} routes")
    print("=" * 115)

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"Saved definitive kinematic report to {OUTPUT_JSON}")


if __name__ == "__main__":
    main()

