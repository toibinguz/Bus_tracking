"""
Deep Statistical Analysis of Bus Telemetry Audit (2026-10-17 vs 2026-10-18)
Answers the 3 core questions:
1. Signal Period Pattern per Vehicle (Moving vs Dwell)
2. Impact of crawled_at Dev-Time Change (Latency, Jitter, Negative Delay Elimination)
3. Packet Loss & Telemetry Gap Audit per Vehicle & Corridor
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

def run_analysis():
    if not os.path.exists(DB_PATH):
        print(f"Error: Database {DB_PATH} not found!")
        return

    conn = sqlite3.connect(DB_PATH)

    print("=" * 80)
    print("PHAN TICH CHUYEN SAU DU LIEU TELEMETRY XE BUYT (NGAY 17/10 VA 18/10)")
    print("=" * 80)

    # 1. QUESTION 2: Impact of crawled_at Dev-Time Change
    print("\n" + "#" * 80)
    print("CAU HOI 2: KIEM CHUNG THAY DOI DEV-TIME (TRUONG crawled_at) VA DO TRE (LATENCY)")
    print("#" * 80)

    q2_summary = pd.read_sql_query("""
    SELECT 
        date_tag,
        total_raw_records,
        total_vehicles_seen,
        negative_latency_count,
        negative_latency_pct,
        mean_latency_sec,
        median_latency_sec,
        std_latency_sec
    FROM daily_system_kpis;
    """, conn)
    print("\n[BẢNG 1] So sánh tổng quan toàn hệ thống giữa 17/10 và 18/10:")
    print(q2_summary.to_string(index=False))

    # Latency quantiles for active moving buses (speed > 5 km/h, latency between -100s and 600s)
    lat_quantiles = []
    for dt in ["2026-10-17", "2026-10-18"]:
        cur = conn.cursor()
        cur.execute(f"""
        SELECT corr_latency_sec 
        FROM raw_telemetry 
        WHERE date_tag = '{dt}' AND is_moving = 1 AND corr_latency_sec BETWEEN -100 AND 600;
        """)
        arr = np.array([r[0] for r in cur.fetchall()])
        lat_quantiles.append({
            "date": dt,
            "sample_size": len(arr),
            "negative_latencies": int(np.sum(arr < 0)),
            "neg_pct": float(np.sum(arr < 0) / len(arr) * 100),
            "min_sec": float(np.min(arr)),
            "p1_sec": float(np.percentile(arr, 1)),
            "p5_sec": float(np.percentile(arr, 5)),
            "p25_sec": float(np.percentile(arr, 25)),
            "p50_median_sec": float(np.percentile(arr, 50)),
            "p75_sec": float(np.percentile(arr, 75)),
            "p90_sec": float(np.percentile(arr, 90)),
            "p95_sec": float(np.percentile(arr, 95)),
            "p99_sec": float(np.percentile(arr, 99)),
            "max_sec": float(np.max(arr)),
            "mean_sec": float(np.mean(arr)),
            "std_sec": float(np.std(arr))
        })
    df_lat = pd.DataFrame(lat_quantiles)
    print("\n[BẢNG 2] Phân phối độ trễ (Latency Distribution) cho các xe đang chạy (Speed > 5 km/h):")
    print(df_lat.to_string(index=False))

    # Distinct timestamps per sweep comparison
    print("\n[BẢNG 3] Số lượng timestamp crawled_at riêng biệt trong 1 lượt quét 504 xe:")
    cur = conn.cursor()
    cur.execute("""
    SELECT date_tag, batch_file, count(DISTINCT crawled_at) as distinct_crawl_ts, count(*) as total_records
    FROM raw_telemetry
    WHERE batch_file LIKE '%120%'
    GROUP BY date_tag, batch_file
    LIMIT 4;
    """)
    for row in cur.fetchall():
        print(f"  Ngày {row[0]} | File {row[1]}: {row[2]} crawled_at distinct trên tổng {row[3]} bản ghi.")

    # 2. QUESTION 1: Signal Period Pattern per Vehicle
    print("\n" + "#" * 80)
    print("CAU HOI 1: CHU KY TIN HIEU CUA 1 XE VA PATTERN TRUYEN TIN (PERIODICITY PATTERN)")
    print("#" * 80)

    # Top 10 intervals for moving buses across days
    for dt in ["2026-10-17", "2026-10-18"]:
        q_intervals = f"""
        SELECT 
            cast(round(delta_t_sec) as int) as delta_t_round,
            count(*) as count_pings,
            round(count(*) * 100.0 / sum(count(*)) over (), 2) as pct
        FROM vehicle_intervals
        WHERE date_tag = '{dt}' AND is_moving = 1 AND delta_t_sec <= 180
        GROUP BY delta_t_round
        ORDER BY count_pings DESC
        LIMIT 10;
        """
        df_int = pd.read_sql_query(q_intervals, conn)
        print(f"\n[BẢNG 4-{dt}] Top 10 chu kỳ khoảng cách thời gian (Delta T) khi xe ĐANG CHẠY (Speed > 5 km/h):")
        print(df_int.to_string(index=False))

    # Dwell/stop intervals
    for dt in ["2026-10-17", "2026-10-18"]:
        q_dwell = f"""
        SELECT 
            cast(round(delta_t_sec) as int) as delta_t_round,
            count(*) as count_pings,
            round(count(*) * 100.0 / sum(count(*)) over (), 2) as pct
        FROM vehicle_intervals
        WHERE date_tag = '{dt}' AND is_moving = 0 AND delta_t_sec <= 180
        GROUP BY delta_t_round
        ORDER BY count_pings DESC
        LIMIT 10;
        """
        df_dw = pd.read_sql_query(q_dwell, conn)
        print(f"\n[BẢNG 5-{dt}] Top 10 chu kỳ khoảng cách thời gian (Delta T) khi xe DỪNG / ĐỖ (Speed <= 5 km/h):")
        print(df_dw.to_string(index=False))

    # Single vehicle deep dive: e.g. Vehicle 231968 (Tuyến 02) and Vehicle 231966 (Tuyến 02)
    sample_vids = [231968, 231966, 231981, 232017]
    print(f"\n[BẢNG 6] Deep-dive chu kỳ tín hiệu trên các xe cụ thể ({sample_vids}):")
    q_vids = f"""
    SELECT 
        date_tag, vehicle_id, plate, route_id,
        unique_pings, total_polls, stale_ratio_pct,
        delta_t_mean, delta_t_median, delta_t_std,
        delta_t_p10, delta_t_p90,
        moving_delta_t_median, dwell_delta_t_median,
        gaps_gt_60s, gaps_gt_120s, gaps_gt_300s
    FROM vehicle_daily_kpis
    WHERE vehicle_id IN ({','.join(str(v) for v in sample_vids)})
    ORDER BY vehicle_id, date_tag;
    """
    df_v = pd.read_sql_query(q_vids, conn)
    print(df_v.to_string(index=False))

    # 3. QUESTION 3: Packet Loss and Telemetry Gap Audit
    print("\n" + "#" * 80)
    print("CAU HOI 3: KIEM CHUNG THIEU HUT BAN TIN & PHAN TICH GAP / BLACKOUT THEO XE VA TUYEN")
    print("#" * 80)

    for dt in ["2026-10-17", "2026-10-18"]:
        df_kpi = pd.read_sql_query(f"SELECT * FROM vehicle_daily_kpis WHERE date_tag = '{dt}'", conn)
        print(f"\n[BẢNG 7-{dt}] Thống kê cấp xe (Vehicle-Level Aggregate) - 504 xe:")
        print(f"  - Số bản tin unique trung bình/xe: Mean = {df_kpi['unique_pings'].mean():.1f}, Median = {df_kpi['unique_pings'].median():.1f}")
        print(f"  - Tỉ lệ bản tin trùng/không đổi (Stale Ratio): Mean = {df_kpi['stale_ratio_pct'].mean():.2f}%, Median = {df_kpi['stale_ratio_pct'].median():.2f}%")
        print(f"  - Chu kỳ cập nhật trung bình (Delta T Mean): {df_kpi['delta_t_mean'].mean():.2f}s, Median = {df_kpi['delta_t_mean'].median():.2f}s, Std = {df_kpi['delta_t_std'].mean():.2f}s")
        print(f"  - P90 Delta T: {df_kpi['delta_t_p90'].mean():.2f}s | P95: {df_kpi['delta_t_p95'].mean():.2f}s | P99: {df_kpi['delta_t_p99'].mean():.2f}s")
        print(f"  - Tổng số khoảng trễ > 60s:  {df_kpi['gaps_gt_60s'].sum():,} (TB {df_kpi['gaps_gt_60s'].mean():.1f} lần/xe)")
        print(f"  - Tổng số khoảng trễ > 120s: {df_kpi['gaps_gt_120s'].sum():,} (TB {df_kpi['gaps_gt_120s'].mean():.1f} lần/xe)")
        print(f"  - Tổng số khoảng trễ > 300s: {df_kpi['gaps_gt_300s'].sum():,} (TB {df_kpi['gaps_gt_300s'].mean():.1f} lần/xe)")
        print(f"  - Tổng số khoảng trễ > 600s: {df_kpi['gaps_gt_600s'].sum():,} (TB {df_kpi['gaps_gt_600s'].mean():.1f} lần/xe)")

    # Route breakdown of packet gaps
    print("\n[BẢNG 8] Top 10 tuyến có chất lượng truyền tin ổn định nhất (ít gap > 120s nhất):")
    q_route_best = """
    SELECT 
        route_id,
        count(distinct vehicle_id) as buses,
        round(avg(unique_pings), 1) as avg_pings_per_bus,
        round(avg(stale_ratio_pct), 2) as stale_pct,
        round(avg(delta_t_median), 1) as median_interval_sec,
        sum(gaps_gt_120s) as total_gaps_120s,
        round(avg(gaps_gt_120s), 1) as avg_gaps_120s_per_bus,
        sum(gaps_gt_300s) as total_gaps_300s
    FROM vehicle_daily_kpis
    WHERE date_tag = '2026-10-18'
    GROUP BY route_id
    HAVING buses >= 5
    ORDER BY avg_gaps_120s_per_bus ASC
    LIMIT 10;
    """
    df_rb = pd.read_sql_query(q_route_best, conn)
    print(df_rb.to_string(index=False))

    print("\n[BẢNG 9] Top 10 tuyến gặp gián đoạn tín hiệu nhiều nhất (nhiều gap > 120s nhất):")
    q_route_worst = """
    SELECT 
        route_id,
        count(distinct vehicle_id) as buses,
        round(avg(unique_pings), 1) as avg_pings_per_bus,
        round(avg(stale_ratio_pct), 2) as stale_pct,
        round(avg(delta_t_median), 1) as median_interval_sec,
        sum(gaps_gt_120s) as total_gaps_120s,
        round(avg(gaps_gt_120s), 1) as avg_gaps_120s_per_bus,
        sum(gaps_gt_300s) as total_gaps_300s
    FROM vehicle_daily_kpis
    WHERE date_tag = '2026-10-18'
    GROUP BY route_id
    HAVING buses >= 5
    ORDER BY avg_gaps_120s_per_bus DESC
    LIMIT 10;
    """
    df_rw = pd.read_sql_query(q_route_worst, conn)
    print(df_rw.to_string(index=False))

    conn.close()

if __name__ == "__main__":
    run_analysis()
