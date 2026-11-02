"""
Export Summary Data for Web Dashboard & CLI Tools
Extracts aggregated statistical tables from data/telemetry_audit_2026_10_17_18.db
and writes to data/telemetry_audit_dashboard_data.json.
"""

import os
import sys
import sqlite3
import json
import numpy as np
import pandas as pd

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

DB_PATH = "data/telemetry_audit_2026_10_17_18.db"
OUTPUT_JSON = "data/telemetry_audit_dashboard_data.json"

def main():
    conn = sqlite3.connect(DB_PATH)

    # 1. System KPIs
    df_sys = pd.read_sql_query("SELECT * FROM daily_system_kpis", conn)
    sys_kpis = df_sys.to_dict(orient="records")

    # 2. Latency percentiles (Active moving buses: speed > 5 km/h, latency between -100s and 600s)
    lat_data = {}
    for dt in ["2026-10-17", "2026-10-18"]:
        cur = conn.cursor()
        cur.execute(f"""
        SELECT corr_latency_sec 
        FROM raw_telemetry 
        WHERE date_tag = '{dt}' AND is_moving = 1 AND corr_latency_sec BETWEEN -100 AND 600;
        """)
        arr = np.array([r[0] for r in cur.fetchall()])
        hist, bin_edges = np.histogram(arr, bins=np.linspace(-40, 160, 41))
        lat_data[dt] = {
            "sample_size": len(arr),
            "negative_count": int(np.sum(arr < 0)),
            "negative_pct": float(np.sum(arr < 0) / len(arr) * 100),
            "min": float(np.min(arr)),
            "p5": float(np.percentile(arr, 5)),
            "p25": float(np.percentile(arr, 25)),
            "p50_median": float(np.percentile(arr, 50)),
            "p75": float(np.percentile(arr, 75)),
            "p90": float(np.percentile(arr, 90)),
            "p95": float(np.percentile(arr, 95)),
            "p99": float(np.percentile(arr, 99)),
            "max": float(np.max(arr)),
            "mean": float(np.mean(arr)),
            "std": float(np.std(arr)),
            "histogram": {
                "counts": hist.tolist(),
                "bins": [float(b) for b in bin_edges[:-1]]
            }
        }

    # 3. Intervals distribution (Moving vs Dwell)
    interval_data = {}
    for dt in ["2026-10-17", "2026-10-18"]:
        # Moving
        q_mov = f"""
        SELECT cast(round(delta_t_sec) as int) as dt_round, count(*) as cnt 
        FROM vehicle_intervals 
        WHERE date_tag = '{dt}' AND is_moving = 1 AND delta_t_sec <= 240
        GROUP BY dt_round ORDER BY cnt DESC LIMIT 20;
        """
        df_mov = pd.read_sql_query(q_mov, conn)

        # Dwell
        q_dw = f"""
        SELECT cast(round(delta_t_sec) as int) as dt_round, count(*) as cnt 
        FROM vehicle_intervals 
        WHERE date_tag = '{dt}' AND is_moving = 0 AND delta_t_sec <= 240
        GROUP BY dt_round ORDER BY cnt DESC LIMIT 20;
        """
        df_dw = pd.read_sql_query(q_dw, conn)

        # Overall Categories
        q_cat = f"""
        SELECT category, count(*) as cnt
        FROM vehicle_intervals
        WHERE date_tag = '{dt}'
        GROUP BY category ORDER BY cnt DESC;
        """
        df_cat = pd.read_sql_query(q_cat, conn)

        interval_data[dt] = {
            "top_moving": df_mov.to_dict(orient="records"),
            "top_dwell": df_dw.to_dict(orient="records"),
            "categories": df_cat.to_dict(orient="records")
        }

    # 4. Vehicle KPI table (all 504 vehicles per date)
    df_vkpi = pd.read_sql_query("""
    SELECT 
        date_tag, vehicle_id, plate, route_id,
        operating_start, operating_end, span_hours,
        total_polls, unique_pings, stale_polls, round(stale_ratio_pct, 1) as stale_pct,
        round(delta_t_mean, 1) as mean_interval, round(delta_t_median, 1) as median_interval,
        round(delta_t_std, 1) as std_interval,
        round(delta_t_p10, 1) as p10_interval, round(delta_t_p90, 1) as p90_interval,
        round(moving_delta_t_median, 1) as mov_median, round(dwell_delta_t_median, 1) as dw_median,
        gaps_gt_60s, gaps_gt_120s, gaps_gt_300s, gaps_gt_600s,
        round(median_latency_corr, 1) as median_lat,
        negative_latency_count
    FROM vehicle_daily_kpis
    ORDER BY vehicle_id, date_tag;
    """, conn)
    vehicle_kpis = df_vkpi.to_dict(orient="records")

    # 5. Route Summary (Aggregated across vehicles for 18/10)
    df_route = pd.read_sql_query("""
    SELECT 
        route_id,
        count(distinct vehicle_id) as buses,
        round(avg(unique_pings), 1) as avg_pings,
        round(avg(stale_ratio_pct), 1) as avg_stale_pct,
        round(avg(delta_t_median), 1) as avg_median_interval,
        sum(gaps_gt_120s) as total_gaps_120s,
        round(avg(gaps_gt_120s), 1) as avg_gaps_120s_per_bus,
        sum(gaps_gt_300s) as total_gaps_300s,
        sum(gaps_gt_600s) as total_gaps_600s
    FROM vehicle_daily_kpis
    WHERE date_tag = '2026-10-18'
    GROUP BY route_id
    ORDER BY avg_gaps_120s_per_bus ASC;
    """, conn)
    route_summary = df_route.to_dict(orient="records")

    # 6. Detailed sample vehicles timeline (Top 10 most tracked vehicles)
    top_vids = [r[0] for r in conn.cursor().execute("""
    SELECT vehicle_id FROM vehicle_daily_kpis WHERE date_tag = '2026-10-18' ORDER BY unique_pings DESC LIMIT 10;
    """).fetchall()]

    detailed_vehicles = {}
    for vid in top_vids:
        cur = conn.cursor()
        cur.execute(f"""
        SELECT date_tag, prev_time, curr_time, delta_t_sec, distance_m, speed_kmh, is_moving, category
        FROM vehicle_intervals
        WHERE vehicle_id = {vid}
        ORDER BY date_tag, curr_epoch;
        """)
        rows = cur.fetchall()
        detailed_vehicles[str(vid)] = [
            {
                "date": r[0], "prev_t": r[1], "curr_t": r[2],
                "dt": round(r[3], 1), "dist": round(r[4], 1),
                "spd": round(r[5], 1), "mov": r[6], "cat": r[7]
            }
            for r in rows
        ]

    conn.close()

    result = {
        "system_kpis": sys_kpis,
        "latency_analysis": lat_data,
        "interval_analysis": interval_data,
        "route_summary": route_summary,
        "vehicle_kpis": vehicle_kpis,
        "detailed_sample_vehicles": detailed_vehicles
    }

    with open(OUTPUT_JSON, "w", encoding="utf-8") as fp:
        json.dump(result, fp, ensure_ascii=False, indent=2)

    print(f"[OK] Successfully exported dashboard data to {OUTPUT_JSON} ({os.path.getsize(OUTPUT_JSON):,} bytes).")

if __name__ == "__main__":
    main()

