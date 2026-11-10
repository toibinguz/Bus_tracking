"""
Empirical Audit of Per-Vehicle GPS Stream Continuity, Station Jumping & Terminal Behavior
Compares:
1. Raw GPS stream (vehicle_unique_pings) vs. Silver Projected stream (route_projected_telemetry)
2. Consecutive ping spatial jumps (delta_s) and station-order skipping (delta_station_order)
3. Mid-trip dropouts / gaps (delta_t > 120s, > 300s while mid-route)
4. Backward jumps (delta_s < 0 within same direction)
5. Exact behavior at the 2 Terminals (Origin Station 0 and Destination Station N):
   - Where does the first ping of a trip actually start (s_first)?
   - Where does the last ping of a trip actually end (L - s_last)?
   - What happens to pings when raw direction == -1 at terminals?
"""

import sqlite3
import numpy as np
import pandas as pd
import sys

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

DB_PATH = "data/hanoi_bus_system.db"


def audit_continuity():
    conn = sqlite3.connect(DB_PATH)
    print("=" * 92)
    print("EMPIRICAL AUDIT: PER-VEHICLE GPS STREAM CONTINUITY, JUMPING & TERMINAL BEHAVIOR")
    print("=" * 92)

    # Load station master to map s_bus_m -> nearest/current station_order and route length
    st_df = pd.read_sql_query(
        """
        SELECT route_code, direction, station_order, station_id, station_name, cum_distance_m
        FROM canonical_station_master
        ORDER BY route_code, direction, station_order
        """,
        conn,
    )
    route_len_map = st_df.groupby(["route_code", "direction"])["cum_distance_m"].max().to_dict()
    route_max_ord = st_df.groupby(["route_code", "direction"])["station_order"].max().to_dict()

    # Load Silver projected telemetry sorted by vehicle and time
    print("\n[*] Loading Silver route_projected_telemetry sorted by (route_code, vehicle_id, device_epoch)...")
    df = pd.read_sql_query(
        """
        SELECT ping_id, route_code, route_id, vehicle_id, plate,
               device_update_time, device_epoch, direction,
               s_bus_m, cross_track_m, derived_speed_kmh
        FROM route_projected_telemetry
        ORDER BY route_code, vehicle_id, device_epoch
        """,
        conn,
    )
    total_silver = len(df)
    print(f"    Loaded {total_silver:,} Silver pings across {df['vehicle_id'].nunique()} vehicles.")

    # Compute consecutive differences per (route_code, vehicle_id)
    same_veh = (df["route_code"] == df["route_code"].shift(1)) & (df["vehicle_id"] == df["vehicle_id"].shift(1))
    same_dir = same_veh & (df["direction"] == df["direction"].shift(1))

    df["dt"] = np.where(same_veh, df["device_epoch"] - df["device_epoch"].shift(1), np.nan)
    df["ds"] = np.where(same_dir, df["s_bus_m"] - df["s_bus_m"].shift(1), np.nan)
    df["prev_s"] = np.where(same_dir, df["s_bus_m"].shift(1), np.nan)
    df["route_len"] = [route_len_map.get((r, d), np.nan) for r, d in zip(df["route_code"], df["direction"])]

    # 1. TEMPORAL & SPATIAL JUMP AUDIT (WITHIN SAME VEHICLE & SAME DIRECTION)
    print("\n" + "=" * 92)
    print("1. KIỂM TRA NHẢY CÓC BẢN GHI (SPATIAL & TEMPORAL JUMPS WITHIN SAME DIRECTION)")
    print("=" * 92)
    valid_trans = df[same_dir & (df["dt"] > 0)].copy()
    n_trans = len(valid_trans)

    # Check within active trips (dt <= 600s)
    active_trans = valid_trans[valid_trans["dt"] <= 600].copy()
    n_act = len(active_trans)

    ds_vals = active_trans["ds"]
    dt_vals = active_trans["dt"]

    print(f"  * Tổng số bước chuyển tiếp cùng chiều (dt <= 600s): {n_act:,} bước")
    print(f"  * Phân bố bước nhảy thời gian (dt):")
    print(f"    - dt <= 60s (Liên tục tốt)           : {(dt_vals <= 60).sum():>9,} ({(dt_vals <= 60).mean()*100:>5.2f}%)")
    print(f"    - 60s < dt <= 90s (Chu kỳ chuẩn)     : {((dt_vals > 60) & (dt_vals <= 90)).sum():>9,} ({((dt_vals > 60) & (dt_vals <= 90)).mean()*100:>5.2f}%)")
    print(f"    - 90s < dt <= 120s (Trễ nhẹ)         : {((dt_vals > 90) & (dt_vals <= 120)).sum():>9,} ({((dt_vals > 90) & (dt_vals <= 120)).mean()*100:>5.2f}%)")
    print(f"    - 120s < dt <= 180s (Mất 1 bản ghi)  : {((dt_vals > 120) & (dt_vals <= 180)).sum():>9,} ({((dt_vals > 120) & (dt_vals <= 180)).mean()*100:>5.2f}%)")
    print(f"    - 180s < dt <= 300s (Mất 2-3 bản ghi): {((dt_vals > 180) & (dt_vals <= 300)).sum():>9,} ({((dt_vals > 180) & (dt_vals <= 300)).mean()*100:>5.2f}%)")
    print(f"    - 300s < dt <= 600s (Đứt quãng 5-10p): {((dt_vals > 300) & (dt_vals <= 600)).sum():>9,} ({((dt_vals > 300) & (dt_vals <= 600)).mean()*100:>5.2f}%)")

    print(f"\n  * Phân bố bước nhảy không gian (ds = s_i - s_{{i-1}}) trong khi dt <= 300s:")
    act300 = valid_trans[valid_trans["dt"] <= 300]
    ds300 = act300["ds"]
    n300 = len(act300)
    print(f"    - Nhảy lùi mạnh (ds < -50m)          : {(ds300 < -50).sum():>9,} ({(ds300 < -50).mean()*100:>5.2f}%) -> Lỗi chiếu / xe quay đầu!")
    print(f"    - Dao động lùi nhẹ (-50m <= ds < 0m) : {((ds300 >= -50) & (ds300 < 0)).sum():>9,} ({((ds300 >= -50) & (ds300 < 0)).mean()*100:>5.2f}%) -> Nhiễu GPS khi dừng")
    print(f"    - Đứng yên (ds == 0m)                : {(ds300 == 0).sum():>9,} ({(ds300 == 0).mean()*100:>5.2f}%)")
    print(f"    - Tiến bình thường (0 < ds <= 500m)  : {((ds300 > 0) & (ds300 <= 500)).sum():>9,} ({((ds300 > 0) & (ds300 <= 500)).mean()*100:>5.2f}%)")
    print(f"    - Nhảy xa (500m < ds <= 1000m)       : {((ds300 > 500) & (ds300 <= 1000)).sum():>9,} ({((ds300 > 500) & (ds300 <= 1000)).mean()*100:>5.2f}%) -> Nhảy qua 1-2 trạm!")
    print(f"    - Nhảy cóc lớn (1000m < ds <= 2000m) : {((ds300 > 1000) & (ds300 <= 2000)).sum():>9,} ({((ds300 > 1000) & (ds300 <= 2000)).mean()*100:>5.2f}%) -> Nhảy qua 2-4 trạm!")
    print(f"    - Nhảy cóc cực lớn (ds > 2000m)      : {(ds300 > 2000).sum():>9,} ({(ds300 > 2000).mean()*100:>5.2f}%) -> Mất tín hiệu / nhảy đoạn!")

    # 2. HOW MANY STATIONS ARE SKIPPED BETWEEN CONSECUTIVE PINGS?
    print("\n" + "=" * 92)
    print("2. KIỂM TRA VIỆC NHẢY CÓC QUA TRẠM DỪNG (STATION SKIPPING PER PING)")
    print("=" * 92)
    # Check inter-station distance across the 48 routes
    st_48 = st_df[st_df["route_code"].isin(df["route_code"].unique())].copy()
    st_48["seg_len"] = st_48.groupby(["route_code", "direction"])["cum_distance_m"].diff()
    seg_lens = st_48["seg_len"].dropna()
    seg_q = np.percentile(seg_lens, [10, 25, 50, 75, 90])
    print(f"  * Khoảng cách thực tế giữa 2 trạm liên tiếp (Delta s_station):")
    print(f"    Mean={seg_lens.mean():.1f}m | P10={seg_q[0]:.1f}m | P25={seg_q[1]:.1f}m | P50 (Median)={seg_q[2]:.1f}m | P75={seg_q[3]:.1f}m | P90={seg_q[4]:.1f}m")
    
    moving_ds = ds300[ds300 > 0]
    ds_q = np.percentile(moving_ds, [10, 25, 50, 75, 90, 95, 99])
    print(f"  * Quãng đường xe đi được giữa 2 ping liên tiếp (khi xe đang chạy ds > 0):")
    print(f"    Mean={moving_ds.mean():.1f}m | P10={ds_q[0]:.1f}m | P25={ds_q[1]:.1f}m | P50 (Median)={ds_q[2]:.1f}m | P75={ds_q[3]:.1f}m | P90={ds_q[4]:.1f}m | P95={ds_q[5]:.1f}m | P99={ds_q[6]:.1f}m")
    print(f"  * So sánh: Khoảng cách trạm trung vị là {seg_q[2]:.1f}m, trong khi bước nhảy ping P75={ds_q[3]:.1f}m, P90={ds_q[4]:.1f}m!")
    print(f"    => Có {(moving_ds > seg_q[2]).mean()*100:.2f}% bước ping nhảy xa hơn khoảng cách trung vị giữa 2 trạm ({seg_q[2]:.0f}m)!")

    # 3. WHY DO MID-TRIP GAPS HAPPEN? COMPARE RAW vs SILVER FOR ONE VEHICLE
    print("\n" + "=" * 92)
    print("3. TẠI SAO CÓ KHOẢNG TRỐNG GIỮA CHUYẾN & Ở 2 ĐẦU BẾN? (RAW PINGS vs. SILVER PINGS)")
    print("=" * 92)
    raw_vs_silver = pd.read_sql_query(
        """
        SELECT v.direction AS raw_dir,
               CASE WHEN v.current_station_id = 0 THEN 'station=0' ELSE 'station>0' END AS st_status,
               COUNT(v.ping_id) AS raw_pings,
               COUNT(t.ping_id) AS silver_kept_pings,
               COUNT(v.ping_id) - COUNT(t.ping_id) AS dropped_pings
        FROM vehicle_unique_pings v
        LEFT JOIN route_projected_telemetry t ON v.ping_id = t.ping_id
        WHERE v.device_update_time >= '2026-10-08'
          AND v.route_id IN (SELECT DISTINCT route_id FROM route_projected_telemetry)
        GROUP BY v.direction, st_status
        ORDER BY v.direction, st_status
        """,
        conn,
    )
    print(raw_vs_silver.to_string(index=False))

    # 4. CHECK ACTUAL START AND END OF TRIPS AT THE 2 TERMINALS!
    print("\n" + "=" * 92)
    print("4. THỰC TẾ XE XUẤT BẾN (ĐẦU BẾN s=0) VÀ VỀ BẾN (CUỐI BẾN s=L) NHƯ THẾ NÀO?")
    print("=" * 92)
    # Segment into trips: break when vehicle changes, direction changes, dt > 300s, or ds < -50m
    new_trip = (~same_dir) | (df["dt"] > 300.0) | (df["ds"] < -50.0)
    df["trip_id"] = new_trip.cumsum()

    trips = df.groupby("trip_id").agg(
        route_code=("route_code", "first"),
        direction=("direction", "first"),
        vehicle_id=("vehicle_id", "first"),
        pings=("ping_id", "count"),
        s_start=("s_bus_m", "first"),
        s_end=("s_bus_m", "last"),
        s_min=("s_bus_m", "min"),
        s_max=("s_bus_m", "max"),
        route_len=("route_len", "first"),
        t_start=("device_epoch", "first"),
        t_end=("device_epoch", "last"),
    )
    valid_trips = trips[(trips["pings"] >= 10) & ((trips["s_max"] - trips["s_min"]) >= 2000.0)].copy()
    valid_trips["dist_from_origin_m"] = valid_trips["s_start"]
    valid_trips["dist_to_dest_m"] = valid_trips["route_len"] - valid_trips["s_end"]
    valid_trips["coverage_pct"] = (valid_trips["s_end"] - valid_trips["s_start"]) / valid_trips["route_len"] * 100.0

    orig_q = np.percentile(valid_trips["dist_from_origin_m"], [10, 25, 50, 75, 90, 95])
    dest_q = np.percentile(valid_trips["dist_to_dest_m"], [10, 25, 50, 75, 90, 95])
    cov_q = np.percentile(valid_trips["coverage_pct"], [10, 25, 50, 75, 90])

    print(f"  * Phân tích trên {len(valid_trips):,} chuyến xe thực tế (>=10 pings, chạy >= 2km):")
    print(f"  * 1) Vị trí ping ĐẦU TIÊN của chuyến (s_start cách Trạm 0 bao xa?):")
    print(f"       P10={orig_q[0]:.0f}m | P25={orig_q[1]:.0f}m | P50 (Trung vị)={orig_q[2]:.0f}m | P75={orig_q[3]:.0f}m | P90={orig_q[4]:.0f}m | P95={orig_q[5]:.0f}m")
    print(f"       - Số chuyến có ping đầu tiên sát Trạm 0 (s_start <= 100m) : {(valid_trips['dist_from_origin_m'] <= 100).sum():,} ({(valid_trips['dist_from_origin_m'] <= 100).mean()*100:.1f}%)")
    print(f"       - Số chuyến bắt đầu sau khi đã rời Trạm 0 > 300m         : {(valid_trips['dist_from_origin_m'] > 300).sum():,} ({(valid_trips['dist_from_origin_m'] > 300).mean()*100:.1f}%)")
    print(f"       - Số chuyến bị cắt cụt giữa đường (s_start > 1000m)       : {(valid_trips['dist_from_origin_m'] > 1000).sum():,} ({(valid_trips['dist_from_origin_m'] > 1000).mean()*100:.1f}%)")

    print(f"\n  * 2) Vị trí ping CUỐI CÙNG của chuyến (s_end còn cách Trạm Cuối L bao xa?):")
    print(f"       P10={dest_q[0]:.0f}m | P25={dest_q[1]:.0f}m | P50 (Trung vị)={dest_q[2]:.0f}m | P75={dest_q[3]:.0f}m | P90={dest_q[4]:.0f}m | P95={dest_q[5]:.0f}m")
    print(f"       - Số chuyến chạm tới sát Trạm Cuối (L - s_end <= 100m)    : {(valid_trips['dist_to_dest_m'] <= 100).sum():,} ({(valid_trips['dist_to_dest_m'] <= 100).mean()*100:.1f}%)")
    print(f"       - Số chuyến mất tín hiệu/đổi chiều trước Trạm Cuối > 300m: {(valid_trips['dist_to_dest_m'] > 300).sum():,} ({(valid_trips['dist_to_dest_m'] > 300).mean()*100:.1f}%)")

    print(f"\n  * 3) Tỷ lệ bao phủ chiều dài toàn tuyến của 1 chuyến (Coverage %):")
    print(f"       P10={cov_q[0]:.1f}% | P25={cov_q[1]:.1f}% | P50 (Trung vị)={cov_q[2]:.1f}% | P75={cov_q[3]:.1f}% | P90={cov_q[4]:.1f}%")

    # 5. PRINT A CONCRETE VEHICLE STREAM IN RAW vs SILVER AROUND TERMINAL TURNAROUND
    print("\n" + "=" * 92)
    print("5. VÍ DỤ CỤ THỂ DÒNG GPS CỦA 1 XE KHI VỀ BẾN VÀ XUẤT BẾN (RAW vs SILVER)")
    print("=" * 92)
    sample_raw = pd.read_sql_query(
        """
        SELECT v.ping_id, v.device_update_time, v.device_epoch, v.direction AS raw_dir,
               v.current_station_id, v.next_station_id, v.lat, v.lon,
               t.direction AS silver_dir, t.s_bus_m, t.cross_track_m, t.derived_speed_kmh
        FROM vehicle_unique_pings v
        LEFT JOIN route_projected_telemetry t ON v.ping_id = t.ping_id
        WHERE v.route_id = (SELECT route_id FROM canonical_route_master WHERE route_code = '02')
          AND v.date_tag = '2026-11-05'
          AND v.vehicle_id = (
              SELECT vehicle_id FROM route_projected_telemetry
              WHERE route_code = '02' AND substr(device_update_time, 1, 10) = '2026-11-05'
              GROUP BY vehicle_id ORDER BY COUNT(*) DESC LIMIT 1
          )
        ORDER BY v.device_epoch
        LIMIT 60
        """,
        conn,
    )
    for idx, r in sample_raw.iterrows():
        status = f"SILVER({r['silver_dir']}, s={r['s_bus_m']:.0f}m, d={r['cross_track_m']:.1f}m, v={r['derived_speed_kmh']})" if pd.notna(r["s_bus_m"]) else "DROPPED (Quarantined / d_perp>35m)"
        print(f"  {r['device_update_time'][11:19]} | raw_dir={r['raw_dir']:>2} | curr_st={r['current_station_id']:>5} -> next_st={r['next_station_id']:>5} | {status}")

    conn.close()


if __name__ == "__main__":
    audit_continuity()
