"""
CLI Tool for Bus Telemetry Audit & Inspection
Allows instant query of vehicle signal periodicity, latency, dropouts, and route stability.
Usage:
  python scripts/query_telemetry_audit.py --summary
  python scripts/query_telemetry_audit.py --vehicle 231968
  python scripts/query_telemetry_audit.py --route 2
  python scripts/query_telemetry_audit.py --worst-dropouts 10
  python scripts/query_telemetry_audit.py --latency-compare
"""

import os
import sys
import argparse
import sqlite3
import pandas as pd

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

DB_PATH = "data/telemetry_audit_2026_10_17_18.db"

def get_conn():
    if not os.path.exists(DB_PATH):
        print(f"[ERROR] Database file '{DB_PATH}' not found!")
        print("Please run: python scripts/build_telemetry_audit_db.py first.")
        sys.exit(1)
    return sqlite3.connect(DB_PATH)

def show_summary():
    conn = get_conn()
    df_sys = pd.read_sql_query("SELECT * FROM daily_system_kpis;", conn)
    print("\n" + "=" * 90)
    print("🚌 TỔNG QUAN HỆ THỐNG TELEMETRY XE BUÝT HÀ NỘI (17/10 VS 18/10)")
    print("=" * 90)
    for _, row in df_sys.iterrows():
        dt = row['date_tag']
        print(f"\n📅 NGÀY: {dt}")
        print(f"  • Tổng số batch tải về:       {int(row['total_batches']):,} files")
        print(f"  • Tổng số bản ghi (polls):     {int(row['total_raw_records']):,} records")
        print(f"  • Tổng số xe quan sát:        {int(row['total_vehicles_seen'])} xe")
        print(f"  • Tổng số pings duy nhất:      {int(row['total_unique_pings']):,} unique pings")
        print(f"  • Tỉ lệ bản tin lặp (Stale %): {row['overall_stale_pct']:.2f}%")
        print(f"  • Độ trễ trung vị (P50):      {row['median_latency_sec']:.2f} giây")
        print(f"  • Độ trễ trung bình (Mean):   {row['mean_latency_sec']:.2f} giây (Std: {row['std_latency_sec']:.2f}s)")
        print(f"  • Bản tin có độ trễ âm (<0s): {int(row['negative_latency_count']):,} ({row['negative_latency_pct']:.2f}%)")
        print(f"  • Chu kỳ trung vị (Delta T):  {row['median_interval_sec']:.1f} giây")
        print(f"  • Số lần gián đoạn > 60s:     {int(row['gaps_gt_60s_count']):,} lần")
        print(f"  • Số lần gián đoạn > 120s:    {int(row['gaps_gt_120s_count']):,} lần")
        print(f"  • Số lần gián đoạn > 300s:    {int(row['gaps_gt_300s_count']):,} lần")
        print(f"  • Số lần gián đoạn > 600s:    {int(row['gaps_gt_600s_count']):,} lần")
    conn.close()

def query_vehicle(vehicle_id):
    conn = get_conn()
    df_kpi = pd.read_sql_query(f"""
    SELECT * FROM vehicle_daily_kpis WHERE vehicle_id = {vehicle_id} ORDER BY date_tag;
    """, conn)
    if df_kpi.empty:
        print(f"[!] Không tìm thấy xe ID {vehicle_id} trong cơ sở dữ liệu.")
        conn.close()
        return

    print("\n" + "=" * 90)
    print(f"🚌 THÔNG TIN VÀ CHU KỲ PHÁT TÍN HIỆU CỦA XE: {vehicle_id} (Biển số: {df_kpi.iloc[0]['plate']}, Tuyến: {df_kpi.iloc[0]['route_id']})")
    print("=" * 90)

    for _, row in df_kpi.iterrows():
        dt = row['date_tag']
        print(f"\n📅 [NGÀY {dt}]")
        print(f"  • Khung giờ hoạt động:   {row['operating_start']} --> {row['operating_end']} ({row['span_hours']:.1f} giờ)")
        print(f"  • Tổng số lần thu thập:  {int(row['total_polls']):,} lần | Pings mới: {int(row['unique_pings']):,} ({100-row['stale_ratio_pct']:.1f}%)")
        print(f"  • Tỉ lệ bản tin không đổi:{row['stale_ratio_pct']:.1f}%")
        print(f"  • Chu kỳ trung vị (P50): {row['delta_t_median']:.1f}s | Trung bình: {row['delta_t_mean']:.1f}s | Độ lệch chuẩn: {row['delta_t_std']:.1f}s")
        print(f"  • Phân vị chu kỳ:         P10={row['delta_t_p10']:.1f}s | P25={row['delta_t_p25']:.1f}s | P75={row['delta_t_p75']:.1f}s | P90={row['delta_t_p90']:.1f}s")
        print(f"  • Chu kỳ khi ĐANG CHẠY:   {row['moving_delta_t_median']:.1f}s (P50)")
        print(f"  • Chu kỳ khi DỪNG / ĐỖ:   {row['dwell_delta_t_median']:.1f}s (P50)")
        print(f"  • Thống kê gián đoạn:    >60s: {int(row['gaps_gt_60s'])} lần | >120s: {int(row['gaps_gt_120s'])} lần | >300s: {int(row['gaps_gt_300s'])} lần | >600s: {int(row['gaps_gt_600s'])} lần")
        print(f"  • Độ trễ crawl - dev:    Trung vị = {row['median_latency_corr']:.1f}s | Số lần âm (<0): {int(row['negative_latency_count'])}")

    # Show top 5 largest dropouts on 18/10
    print(f"\n🔍 [5 KHOẢNG MẤT TÍN HIỆU (DROPOUT GAPS) DÀI NHẤT NGÀY 18/10]:")
    df_gaps = pd.read_sql_query(f"""
    SELECT prev_time, curr_time, delta_t_sec, distance_m, speed_kmh, category
    FROM vehicle_intervals
    WHERE vehicle_id = {vehicle_id} AND date_tag = '2026-10-18'
    ORDER BY delta_t_sec DESC
    LIMIT 5;
    """, conn)
    if not df_gaps.empty:
        for idx, g in df_gaps.iterrows():
            print(f"  #{idx+1}: {g['delta_t_sec']:.1f} giây ({g['category']}) | Từ {g['prev_time']} đến {g['curr_time']} | Quãng đường: {g['distance_m']:.1f}m | Tốc độ: {g['speed_kmh']} km/h")
    else:
        print("  Không có dữ liệu gián đoạn.")
    conn.close()

def query_route(route_id):
    conn = get_conn()
    df_r = pd.read_sql_query(f"""
    SELECT 
        vehicle_id, plate, unique_pings, stale_ratio_pct,
        delta_t_median, moving_delta_t_median, dwell_delta_t_median,
        gaps_gt_120s, gaps_gt_300s, median_latency_corr
    FROM vehicle_daily_kpis
    WHERE route_id = {route_id} AND date_tag = '2026-10-18'
    ORDER BY unique_pings DESC;
    """, conn)
    if df_r.empty:
        print(f"[!] Không tìm thấy xe nào chạy tuyến {route_id} trong ngày 18/10.")
        conn.close()
        return

    print("\n" + "=" * 90)
    print(f"🚌 DANH SÁCH {len(df_r)} XE HOẠT ĐỘNG TRÊN TUYẾN {route_id} (DỮ LIỆU NGÀY 18/10)")
    print("=" * 90)
    print(df_r.to_string(index=False))
    conn.close()

def query_worst_dropouts(limit=10):
    conn = get_conn()
    df_w = pd.read_sql_query(f"""
    SELECT 
        vehicle_id, plate, route_id,
        unique_pings, delta_t_median,
        gaps_gt_120s, gaps_gt_300s, gaps_gt_600s
    FROM vehicle_daily_kpis
    WHERE date_tag = '2026-10-18'
    ORDER BY gaps_gt_120s DESC
    LIMIT {limit};
    """, conn)
    print("\n" + "=" * 90)
    print(f"⚠️ TOP {limit} XE GẶP NHIỀU GIÁN ĐOẠN TÍN HIỆU (>120s) NHẤT NGÀY 18/10")
    print("=" * 90)
    print(df_w.to_string(index=False))
    conn.close()

def query_latency_comparison():
    conn = get_conn()
    print("\n" + "=" * 90)
    print("⏱️ KIỂM CHỨNG ĐỘ TRỄ (LATENCY) VÀ DEV-TIME CRAWLED_AT GIỮA 17/10 VÀ 18/10")
    print("=" * 90)
    df_lat = pd.read_sql_query("""
    SELECT 
        date_tag,
        count(*) as total_samples,
        sum(case when corr_latency_sec < 0 then 1 else 0 end) as neg_latency_count,
        round(sum(case when corr_latency_sec < 0 then 1 else 0 end) * 100.0 / count(*), 2) as neg_pct,
        round(avg(corr_latency_sec), 2) as mean_sec,
        round(min(corr_latency_sec), 2) as min_sec,
        round(max(corr_latency_sec), 2) as max_sec
    FROM raw_telemetry
    WHERE is_moving = 1 AND corr_latency_sec BETWEEN -100 AND 600
    GROUP BY date_tag;
    """, conn)
    print(df_lat.to_string(index=False))
    conn.close()

def main():
    parser = argparse.ArgumentParser(description="Bus Telemetry Audit Query Tool")
    parser.add_argument("--summary", action="store_true", help="Hiển thị tổng quan hệ thống 17/10 vs 18/10")
    parser.add_argument("--vehicle", type=int, help="Tra cứu chu kỳ và thống kê chi tiết theo vehicle_id")
    parser.add_argument("--route", type=int, help="Tra cứu toàn bộ xe thuộc route_id")
    parser.add_argument("--worst-dropouts", type=int, const=10, nargs="?", help="Top N xe bị gián đoạn nhiều nhất")
    parser.add_argument("--latency-compare", action="store_true", help="So sánh chi tiết độ trễ 17/10 vs 18/10")

    args = parser.parse_args()

    if args.summary:
        show_summary()
    elif args.vehicle:
        query_vehicle(args.vehicle)
    elif args.route:
        query_route(args.route)
    elif args.worst_dropouts:
        query_worst_dropouts(args.worst_dropouts)
    elif args.latency_compare:
        query_latency_comparison()
    else:
        # Default show summary and sample vehicle
        show_summary()
        query_vehicle(231968)

if __name__ == "__main__":
    main()

