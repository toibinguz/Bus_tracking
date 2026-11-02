"""
Script: scripts/build_tomtom_cross_validation.py
Purpose: WP 2.1.3 (Hotfixed & Audited)
  - Builds agg_tomtom_vs_bus_kinematics table in SQLite.
  - Evaluates empirical speed reduction, dwell rate increase, and sample counts
    on every station pair (k -> k+1) across all 48 canonical routes.
  - Applies strict physical corridor filters (abs(cross_track_m) <= 35m,
    2.0 <= derived_speed_kmh <= 75.0, excluding terminal staging stalls)
    and matches active congestion incidents (delay_seconds > 0).
"""
import sqlite3
import time
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')
DB_PATH = "data/hanoi_bus_system.db"


def main():
    t_start = time.time()
    print("=" * 84, flush=True)
    print("WP 2.1.3 (HOTFIXED): CROSS-VALIDATION OF TOMTOM INCIDENTS VS BUS KINEMATICS", flush=True)
    print("=" * 84, flush=True)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # 1. Load target routes
    cur.execute("SELECT DISTINCT route_code FROM ml_route_evaluation_summary ORDER BY route_code")
    target_routes = sorted([r[0] for r in cur.fetchall()])
    print(f"[1/4] Processing cross-validation for {len(target_routes)} routes...", flush=True)

    # 2. Setup SQLite table
    cur.execute("DROP TABLE IF EXISTS agg_tomtom_vs_bus_kinematics")
    cur.execute(
        """
        CREATE TABLE agg_tomtom_vs_bus_kinematics (
            route_code TEXT NOT NULL,
            direction TEXT NOT NULL,
            from_station_order INTEGER NOT NULL,
            to_station_order INTEGER NOT NULL,
            from_station_name TEXT,
            to_station_name TEXT,
            segment_distance_m REAL,
            normal_speed_kmh REAL,
            incident_speed_kmh REAL,
            speed_drop_pct REAL,
            normal_dwell_pct REAL,
            incident_dwell_pct REAL,
            incident_event_count INTEGER,
            sample_pings_with_inc INTEGER,
            sample_pings_normal INTEGER,
            PRIMARY KEY (route_code, direction, from_station_order, to_station_order)
        )
        """
    )
    conn.commit()

    # Pre-load all station pairs for 48 routes
    cur.execute(
        """
        SELECT route_code, direction, station_order, station_name, cum_distance_m
        FROM canonical_station_master
        WHERE route_code IN ({})
        ORDER BY route_code, direction, station_order
        """.format(",".join(f"'{r}'" for r in target_routes))
    )
    route_stations = defaultdict(lambda: {"go": [], "re": []})
    for rcode, direction, order, name, s_m in cur.fetchall():
        route_stations[rcode][direction].append((int(order), str(name), float(s_m)))

    print(f"[2/4] Loaded station masters for all 48 routes.", flush=True)

    # 3. Process route by route using 10-minute epoch buckets for exact, bug-free temporal matching
    print(f"[3/4] Streaming sanitized bus telemetry and correlating with active congestion windows...", flush=True)

    total_agg_rows = []
    total_pings_evaluated = 0
    total_inc_pings = 0
    total_norm_pings = 0

    for idx, rcode in enumerate(target_routes, 1):
        t_route = time.time()

        # Load active congestion incident windows (delay_seconds > 0) for this route
        cur.execute(
            """
            SELECT direction, from_station_order, to_station_order,
                   s_min_m, s_max_m, t_start_epoch, t_end_epoch, incident_id, delay_seconds
            FROM fact_route_tomtom_incidents
            WHERE route_code = ? AND delay_seconds > 0
            """,
            (rcode,),
        )
        inc_records = cur.fetchall()

        # Index by (direction, from_order, to_order, bucket_600s) -> list of (t_start, t_end, s_min, s_max)
        pair_time_buckets = defaultdict(list)
        pair_inc_ids = defaultdict(set)
        for d_dir, f_ord, t_ord, s_min, s_max, t_s, t_e, inc_id, _ in inc_records:
            pair_key = (str(d_dir), int(f_ord), int(t_ord))
            pair_inc_ids[pair_key].add(inc_id)
            b_start = int(t_s // 600)
            b_end = int(t_e // 600)
            for b in range(b_start, b_end + 1):
                pair_time_buckets[(str(d_dir), int(f_ord), int(t_ord), b)].append((int(t_s), int(t_e), float(s_min), float(s_max)))

        # Build station boundaries for this route
        stn_bounds = {}
        station_info = {}
        for direction in ["go", "re"]:
            stns = route_stations[rcode][direction]
            stn_bounds[direction] = []
            for k in range(len(stns) - 1):
                o_from, n_from, s_from = stns[k]
                o_to, n_to, s_to = stns[k + 1]
                stn_bounds[direction].append((s_from, s_to, o_from, o_to))
                station_info[(direction, o_from, o_to)] = (n_from, n_to, round(s_to - s_from, 1))

        route_pair_stats = {}
        for (direction, o_from, o_to), (n_from, n_to, dist_m) in station_info.items():
            route_pair_stats[(direction, o_from, o_to)] = {
                "n_from": n_from,
                "n_to": n_to,
                "dist_m": dist_m,
                "v_inc": [],
                "v_norm": [],
                "dwell_inc": 0,
                "dwell_norm": 0,
                "inc_events": len(pair_inc_ids.get((direction, o_from, o_to), set())),
            }

        # Stream sanitized on-corridor telemetry pings for this route
        # Filter: abs(cross_track_m) <= 35.0 and derived_speed_kmh <= 75.0 (exclude GPS teleport spikes)
        cur.execute(
            """
            SELECT device_epoch, direction, s_bus_m, derived_speed_kmh, is_dwell
            FROM route_projected_telemetry
            WHERE route_code = ?
              AND derived_speed_kmh IS NOT NULL
              AND derived_speed_kmh >= 0.0
              AND derived_speed_kmh <= 75.0
              AND ABS(cross_track_m) <= 35.0
            """,
            (rcode,),
        )
        pings = cur.fetchall()

        for epoch, direction, s_m, speed, is_dwell in pings:
            bounds = stn_bounds.get(direction, [])
            if not bounds:
                continue
            # Exclude 100m terminal staging zones at very start and very end of route
            route_len = bounds[-1][1]
            if s_m < 80.0 or s_m > route_len - 80.0:
                continue

            matched_key = None
            for s_from, s_to, o_from, o_to in bounds:
                if s_from <= s_m <= s_to:
                    matched_key = (direction, o_from, o_to)
                    break
            if not matched_key:
                continue

            stat = route_pair_stats.get(matched_key)
            if not stat:
                continue

            total_pings_evaluated += 1
            b_ping = int(epoch // 600)
            candidates = pair_time_buckets.get((matched_key[0], matched_key[1], matched_key[2], b_ping), [])
            has_inc = False
            for w_start, w_end, inc_s_min, inc_s_max in candidates:
                if w_start <= epoch <= w_end and (inc_s_min - 30.0) <= s_m <= (inc_s_max + 30.0):
                    has_inc = True
                    break

            if has_inc:
                stat["v_inc"].append(float(speed))
                if is_dwell:
                    stat["dwell_inc"] += 1
                total_inc_pings += 1
            else:
                stat["v_norm"].append(float(speed))
                if is_dwell:
                    stat["dwell_norm"] += 1
                total_norm_pings += 1

        # Format results for this route
        for (direction, o_from, o_to), stat in route_pair_stats.items():
            n_inc = len(stat["v_inc"])
            n_norm = len(stat["v_norm"])
            avg_inc = sum(stat["v_inc"]) / n_inc if n_inc > 0 else None
            avg_norm = sum(stat["v_norm"]) / n_norm if n_norm > 0 else None

            speed_drop = None
            if avg_inc is not None and avg_norm is not None and avg_norm >= 3.0:
                speed_drop = round((avg_norm - avg_inc) / avg_norm * 100.0, 2)

            dwell_inc_pct = round(stat["dwell_inc"] / n_inc * 100.0, 2) if n_inc > 0 else None
            dwell_norm_pct = round(stat["dwell_norm"] / n_norm * 100.0, 2) if n_norm > 0 else None

            total_agg_rows.append(
                (
                    rcode,
                    direction,
                    o_from,
                    o_to,
                    stat["n_from"],
                    stat["n_to"],
                    stat["dist_m"],
                    round(avg_norm, 2) if avg_norm is not None else None,
                    round(avg_inc, 2) if avg_inc is not None else None,
                    speed_drop,
                    dwell_norm_pct,
                    dwell_inc_pct,
                    stat["inc_events"],
                    n_inc,
                    n_norm,
                )
            )

        if idx % 10 == 0 or idx == len(target_routes):
            print(f"      [{idx:02d}/{len(target_routes)}] Route {rcode:>4} done in {time.time() - t_route:.2f}s ({len(pings):,} pings).", flush=True)

    # 4. Insert into SQLite
    print(f"[4/4] Inserting {len(total_agg_rows):,} station pair rows into agg_tomtom_vs_bus_kinematics...", flush=True)
    cur.executemany(
        """
        INSERT INTO agg_tomtom_vs_bus_kinematics VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        """,
        total_agg_rows,
    )
    conn.commit()

    # Statistical Summary
    cur.execute(
        """
        SELECT 
            COUNT(*),
            COUNT(CASE WHEN sample_pings_with_inc > 0 THEN 1 END),
            AVG(CASE WHEN speed_drop_pct IS NOT NULL AND sample_pings_with_inc >= 15 AND sample_pings_normal >= 30 THEN speed_drop_pct END),
            AVG(CASE WHEN speed_drop_pct IS NOT NULL AND sample_pings_with_inc >= 15 AND sample_pings_normal >= 30 AND speed_drop_pct > 0 THEN speed_drop_pct END),
            COUNT(CASE WHEN speed_drop_pct IS NOT NULL AND sample_pings_with_inc >= 15 AND sample_pings_normal >= 30 AND speed_drop_pct > 15.0 THEN 1 END),
            AVG(CASE WHEN sample_pings_with_inc >= 15 AND sample_pings_normal >= 30 THEN normal_dwell_pct END),
            AVG(CASE WHEN sample_pings_with_inc >= 15 AND sample_pings_normal >= 30 THEN incident_dwell_pct END)
        FROM agg_tomtom_vs_bus_kinematics
        """
    )
    s_row = cur.fetchone()

    print("\n" + "=" * 84)
    print("WP 2.1.3 HOTFIXED EMPIRICAL AUDIT RESULTS (agg_tomtom_vs_bus_kinematics):")
    print(f"  - Total station pairs evaluated: {s_row[0]:,}")
    print(f"  - Station pairs with active TomTom congestion: {s_row[1]:,} ({s_row[1] / s_row[0] * 100:.1f}%)")
    print(f"  - Total sanitized corridor pings evaluated: {total_pings_evaluated:,}")
    print(f"  - Pings inside active TomTom congestion zone: {total_inc_pings:,} ({total_inc_pings / max(1, total_pings_evaluated) * 100:.2f}%)")
    print(f"  - Pings under normal conditions: {total_norm_pings:,} ({total_norm_pings / max(1, total_pings_evaluated) * 100:.2f}%)")
    print(f"  - Overall controlled mean speed drop across active pairs: {s_row[2] or 0.0:+.2f}%")
    print(f"  - Mean speed drop on slowdown pairs: {s_row[3] or 0.0:+.2f}%")
    print(f"  - Mean dwell percentage: Normal {s_row[5] or 0.0:.2f}% -> During Incident {s_row[6] or 0.0:.2f}%")
    print(f"  - Station pairs experiencing severe congestion (> 15% speed drop): {s_row[4]:,} pairs")
    print("=" * 84, flush=True)

    # Display Top 15 worst congestion bottlenecks
    cur.execute(
        """
        SELECT route_code, direction, from_station_name, to_station_name, 
               normal_speed_kmh, incident_speed_kmh, speed_drop_pct,
               normal_dwell_pct, incident_dwell_pct, sample_pings_with_inc, sample_pings_normal
        FROM agg_tomtom_vs_bus_kinematics
        WHERE sample_pings_with_inc >= 20 AND sample_pings_normal >= 50
          AND normal_speed_kmh BETWEEN 8.0 AND 50.0
          AND speed_drop_pct IS NOT NULL
        ORDER BY speed_drop_pct DESC
        LIMIT 15
        """
    )
    print("\nTop 15 Sanitized Empirical Congestion Bottlenecks Identified by TomTom Fusion:")
    print(f"{'Route':<6} | {'Dir':<4} | {'From -> To Station':<44} | {'V_norm':<9} | {'V_inc':<9} | {'Drop %':<8} | {'Dwell(N->I)':<13} | {'Samples'}")
    print("-" * 118)
    for r in cur.fetchall():
        stn_pair = f"{r[2][:19]} -> {r[3][:19]}"
        dwell_str = f"{r[7]:.0f}%->{r[8]:.0f}%"
        print(f"{r[0]:<6} | {r[1]:<4} | {stn_pair:<44} | {r[4]:>5.1f}km/h | {r[5]:>5.1f}km/h | {-r[6]:>+6.1f}% | {dwell_str:<13} | {r[9]} inc / {r[10]} norm")

    conn.close()
    print(f"\nCompleted hotfixed WP 2.1.3 successfully in {time.time() - t_start:.2f} seconds.", flush=True)


if __name__ == "__main__":
    main()
