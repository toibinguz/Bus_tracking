"""
Empirical EDA for User Questions 2 & 3:
1. Day-of-Week (Mon-Fri vs Saturday vs Sunday) & 18 Hourly Slots Analysis:
   - How different is Saturday from Weekday and Sunday across hours 05..22?
   - What is the sample density (N/cell) and Held-Out Test MAE/MedAE under:
     * Scheme A: 2 Day-Types (Weekday vs Weekend) x 18 Hours
     * Scheme B: 3 Day-Types (Weekday, Saturday, Sunday) x 18 Hours (raw vs 3-hour kernel-pooled for Sat/Sun)
     * Scheme C: 3 Day-Types x 7 Traffic Regimes (Early 05-06, AM Peak 07-08, AM Shoulder 09-10, Midday 11-15, PM Peak 16-18, Evening 19-20, Night 21-22)
2. Terminal Stations (First & Last Station) Noise Analysis:
   - Compare segment variance & Test ETA error at Origin Terminal (station_order 0 -> 1),
     Destination Terminal (station_order N-1 -> N), vs Interior Active Corridor (1 .. N-1).
   - Measure Test Set ETA improvement when Live ETA only tracks active in-transit buses
     (excluding origin terminal staging zone and destination terminal parking gate).
"""

import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
import numpy as np
import pandas as pd
import pyarrow.dataset as ds_pa

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from config.system_config import (
    DEFAULT_DB_PATH,
    DEFAULT_LAKEHOUSE_ROOT,
    SEGMENT_MAX_SPEED_KMPH,
    SEGMENT_MIN_SPEED_KMPH,
    TEST_SPLIT_START_DATE,
    TRAIN_SPLIT_END_DATE,
    TZ_HANOI,
)
from module_1_data_ingestion_and_preprocessing.step_1_3_telemetry_kinematic_sanitizer.trip_segmenter import (
    segment_trajectory_into_trips,
)
from module_3_bus_eta_prediction.step_3_1_historical_baseline_model.baseline_matrix_builder import (
    extract_bracketed_station_arrivals,
)

DB_PATH = os.path.join(BASE_DIR, DEFAULT_DB_PATH)
SILVER_TEL_DIR = os.path.join(BASE_DIR, DEFAULT_LAKEHOUSE_ROOT, "silver", "route_projected_telemetry")


def hour_to_regime(hr: int) -> int:
    if hr <= 6:
        return 0  # 05:00-06:59 Early Morning
    elif hr <= 8:
        return 1  # 07:00-08:59 Morning Rush
    elif hr <= 10:
        return 2  # 09:00-10:59 Late Morning
    elif hr <= 15:
        return 3  # 11:00-15:59 Midday
    elif hr <= 18:
        return 4  # 16:00-18:59 Afternoon/Evening Rush
    elif hr <= 20:
        return 5  # 19:00-20:59 Evening
    else:
        return 6  # 21:00-22:59 Late Night


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    shape_rows = cur.execute(
        "SELECT route_code, direction, MAX(cum_distance_m) FROM canonical_shape_master GROUP BY route_code, direction"
    ).fetchall()
    shape_len_map = {(r, d): float(l) for r, d, l in shape_rows}

    st_rows = cur.execute(
        "SELECT route_code, direction, station_order, station_id, station_name, cum_distance_m FROM canonical_station_master ORDER BY route_code, direction, station_order"
    ).fetchall()
    stations_map = defaultdict(list)
    for r_code, d_str, st_ord, st_id, st_name, s_m in st_rows:
        stations_map[(r_code, d_str)].append((int(st_ord), int(st_id), str(st_name), float(s_m)))
    conn.close()

    dataset = ds_pa.dataset(SILVER_TEL_DIR, format="parquet", partitioning="hive")
    tbl = dataset.to_table(
        columns=["route_code", "vehicle_id", "device_update_time", "device_epoch", "direction", "s_bus_m", "derived_speed_kmh"]
    )
    df_all = tbl.to_pandas()
    df_all["dt"] = df_all["device_update_time"].str.slice(0, 10)
    df_all = df_all.sort_values(["route_code", "vehicle_id", "direction", "device_epoch"]).reset_index(drop=True)

    # Count distinct dates by day_type in Train vs Test
    train_dates = sorted(df_all[df_all["dt"] <= TRAIN_SPLIT_END_DATE]["dt"].unique())
    test_dates = sorted(df_all[df_all["dt"] >= TEST_SPLIT_START_DATE]["dt"].unique())

    def count_dows(dates):
        wk, sat, sun = 0, 0, 0
        for d in dates:
            wd = datetime.strptime(d, "%Y-%m-%d").weekday()
            if wd < 5:
                wk += 1
            elif wd == 5:
                sat += 1
            else:
                sun += 1
        return wk, sat, sun

    tr_wk, tr_sat, tr_sun = count_dows(train_dates)
    te_wk, te_sat, te_sun = count_dows(test_dates)
    print("=" * 95)
    print("1. CALENDAR DISTRIBUTION OF TRAIN vs TEST DAYS (WEEKDAY vs SATURDAY vs SUNDAY)")
    print("=" * 95)
    print(f"  * Train Dates ({len(train_dates)} days): Mon-Fri={tr_wk} days | Saturday={tr_sat} days | Sunday={tr_sun} days")
    print(f"  * Test Dates  ({len(test_dates)} days) : Mon-Fri={te_wk} days | Saturday={te_sat} days | Sunday={te_sun} days")

    # Collect segment traversals with (route_code, d_str, ord_a, ord_b, max_ord, seg_dist, tt, spd_kmh, dow, hour, is_train)
    records = []
    test_trips_info = []

    for (r_code, vid, d_str), grp in df_all.groupby(["route_code", "vehicle_id", "direction"], sort=False):
        r_len = shape_len_map.get((r_code, d_str), 0.0)
        st_list = stations_map.get((r_code, d_str), [])
        if len(st_list) < 2:
            continue
        max_ord = st_list[-1][0]

        pings_tuples = list(
            zip(grp["dt"].tolist(), grp["device_epoch"].tolist(), grp["s_bus_m"].tolist(), grp["derived_speed_kmh"].tolist())
        )
        trips = segment_trajectory_into_trips(pings_tuples, epoch_idx=1, s_idx=2, shape_len_m=r_len, trim_terminals=True)

        for tr in trips:
            is_train = tr[0][0] <= TRAIN_SPLIT_END_DATE
            arrivals = extract_bracketed_station_arrivals(tr, st_list, epoch_idx=1, s_idx=2)
            if len(arrivals) < 2:
                continue
            if not is_train:
                test_trips_info.append((r_code, d_str, st_list, arrivals))

            for k in range(len(st_list) - 1):
                ord_a, _, _, s_a = st_list[k]
                ord_b, _, _, s_b = st_list[k + 1]
                seg_dist = s_b - s_a
                if seg_dist <= 1.0:
                    continue
                if ord_a in arrivals and ord_b in arrivals:
                    tt = arrivals[ord_b] - arrivals[ord_a]
                    if tt <= 0:
                        continue
                    spd_kmh = (seg_dist / tt) * 3.6
                    if not (SEGMENT_MIN_SPEED_KMPH <= spd_kmh <= SEGMENT_MAX_SPEED_KMPH):
                        continue
                    dt_obj = datetime.fromtimestamp(arrivals[ord_a], tz=TZ_HANOI)
                    wd = dt_obj.weekday()
                    day_cat = 0 if wd < 5 else (1 if wd == 5 else 2)  # 0=Mon-Fri, 1=Sat, 2=Sun
                    hr = min(22, max(5, dt_obj.hour))
                    records.append((r_code, d_str, ord_a, ord_b, max_ord, seg_dist, tt, spd_kmh, day_cat, hr, is_train))

    df_seg = pd.DataFrame(
        records,
        columns=["route_code", "direction", "ord_a", "ord_b", "max_ord", "seg_dist", "tt", "spd_kmh", "day_cat", "hr", "is_train"],
    )
    df_train = df_seg[df_seg["is_train"]]
    df_test = df_seg[~df_seg["is_train"]]

    print("\n" + "=" * 95)
    print("2. EMPIRICAL KINEMATICS: WEEKDAY (Mon-Fri) vs SATURDAY (Thứ 7) vs SUNDAY (Chủ Nhật) BY HOUR")
    print("=" * 95)
    piv_spd = df_train.pivot_table(index="hr", columns="day_cat", values="spd_kmh", aggfunc="median")
    piv_cnt = df_train.pivot_table(index="hr", columns="day_cat", values="spd_kmh", aggfunc="count")
    print(f"  {'Hour':<6} | {'Mon-Fri Spd':<13} | {'Saturday Spd':<13} | {'Sunday Spd':<13} | {'Sat vs Wkday':<13} | {'Sat vs Sun':<12} | {'Sat Samples':<11}")
    print("  " + "-" * 88)
    for hr in range(5, 23):
        if hr not in piv_spd.index:
            continue
        s_wk = piv_spd.loc[hr, 0] if 0 in piv_spd.columns else np.nan
        s_sat = piv_spd.loc[hr, 1] if 1 in piv_spd.columns else np.nan
        s_sun = piv_spd.loc[hr, 2] if 2 in piv_spd.columns else np.nan
        c_sat = int(piv_cnt.loc[hr, 1]) if 1 in piv_cnt.columns and not pd.isna(piv_cnt.loc[hr, 1]) else 0
        print(
            f"  {hr:02d}:00  | {s_wk:>8.2f} km/h | {s_sat:>8.2f} km/h | {s_sun:>8.2f} km/h | {s_sat - s_wk:>+7.2f} km/h | {s_sat - s_sun:>+6.2f} km/h | {c_sat:>9,}"
        )

    # Compare 3 Baseline Schemes on Test Set segment travel time prediction:
    # Scheme A: 2 Day-Types (0=Mon-Fri, 1=Sat+Sun) x 18 Hours
    # Scheme B: 3 Day-Types (0=Mon-Fri, 1=Sat, 2=Sun) x 18 Hours (with 3-hour sliding window pooling when N < 5)
    # Scheme C: 3 Day-Types (0=Mon-Fri, 1=Sat, 2=Sun) x 7 Traffic Regimes
    print("\n" + "=" * 95)
    print("3. BENCHMARKING TIME-GRANULARITY SCHEMES ON HELD-OUT TEST SET (SATURDAY & SUNDAY FOCUS)")
    print("=" * 95)

    # Build lookup dictionaries from df_train
    # Global segment median fallback
    seg_glob = df_train.groupby(["route_code", "direction", "ord_a", "ord_b"])["tt"].median().to_dict()

    # Scheme A: 2 day types x 18 hours
    df_train_a = df_train.copy()
    df_train_a["wknd"] = (df_train_a["day_cat"] >= 1).astype(int)
    map_a = df_train_a.groupby(["route_code", "direction", "ord_a", "ord_b", "wknd", "hr"])["tt"].agg(["median", "count"]).to_dict("index")
    map_a_day = df_train_a.groupby(["route_code", "direction", "ord_a", "ord_b", "wknd"])["tt"].median().to_dict()

    # Scheme B1: Raw 3 day types x 18 hours (fallback to day_cat median if count < 3)
    map_b_raw = df_train.groupby(["route_code", "direction", "ord_a", "ord_b", "day_cat", "hr"])["tt"].agg(["median", "count"]).to_dict("index")
    map_b_day = df_train.groupby(["route_code", "direction", "ord_a", "ord_b", "day_cat"])["tt"].median().to_dict()

    # Scheme B2: 3 day types x 18 hours WITH 3-Hour Kernel Pooling [hr-1, hr, hr+1] when direct count < 8
    slot_lists_3d = defaultdict(list)
    for row in df_train.itertuples(index=False):
        slot_lists_3d[(row.route_code, row.direction, row.ord_a, row.ord_b, row.day_cat, row.hr)].append(row.tt)

    # Scheme C: 3 day types x 7 Traffic Regimes
    df_train_c = df_train.copy()
    df_train_c["reg"] = df_train_c["hr"].apply(hour_to_regime)
    map_c = df_train_c.groupby(["route_code", "direction", "ord_a", "ord_b", "day_cat", "reg"])["tt"].agg(["median", "count"]).to_dict("index")

    errs_a, errs_b1, errs_b2, errs_c = defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list)
    for row in df_test.itertuples(index=False):
        seg_k = (row.route_code, row.direction, row.ord_a, row.ord_b)
        glob_v = seg_glob.get(seg_k, row.seg_dist / 5.0)
        wknd = 1 if row.day_cat >= 1 else 0
        reg = hour_to_regime(row.hr)

        # Pred A
        ca = map_a.get((*seg_k, wknd, row.hr))
        pa = ca["median"] if (ca and ca["count"] >= 3) else map_a_day.get((*seg_k, wknd), glob_v)

        # Pred B1
        cb1 = map_b_raw.get((*seg_k, row.day_cat, row.hr))
        pb1 = cb1["median"] if (cb1 and cb1["count"] >= 3) else map_b_day.get((*seg_k, row.day_cat), glob_v)

        # Pred B2 (3-day-type + adjacent hour pooling if count < 8)
        direct_l = slot_lists_3d.get((*seg_k, row.day_cat, row.hr), [])
        if len(direct_l) >= 8:
            pb2 = float(np.median(direct_l))
        else:
            pool_l = []
            for h_adj in (row.hr - 1, row.hr, row.hr + 1):
                pool_l.extend(slot_lists_3d.get((*seg_k, row.day_cat, h_adj), []))
            if len(pool_l) >= 3:
                pb2 = float(np.median(pool_l))
            else:
                pb2 = map_b_day.get((*seg_k, row.day_cat), glob_v)

        # Pred C (3-day-type x 7 Traffic Regimes)
        cc = map_c.get((*seg_k, row.day_cat, reg))
        pc = cc["median"] if (cc and cc["count"] >= 3) else map_b_day.get((*seg_k, row.day_cat), glob_v)

        for d_label in ("ALL", f"DAY_{row.day_cat}"):
            errs_a[d_label].append(row.tt - pa)
            errs_b1[d_label].append(row.tt - pb1)
            errs_b2[d_label].append(row.tt - pb2)
            errs_c[d_label].append(row.tt - pc)

    for d_label, title in [("ALL", "All Test Days"), ("DAY_0", "Mon-Fri (Weekday)"), ("DAY_1", "Saturday (Thứ 7)"), ("DAY_2", "Sunday (Chủ Nhật)")]:
        print(f"\n  [{title}] (N={len(errs_a[d_label]):,}):")
        for s_name, e_dict in [
            ("Scheme A  (2 Day-Types x 18 Hours)                 ", errs_a),
            ("Scheme B1 (3 Day-Types x 18 Hours Raw)             ", errs_b1),
            ("Scheme B2 (3 Day-Types x 18 Hours + 3h Kernel Pool)", errs_b2),
            ("Scheme C  (3 Day-Types x 7 Traffic Regimes)        ", errs_c),
        ]:
            arr = np.array(e_dict[d_label])
            print(
                f"    * {s_name}: MAE={np.mean(np.abs(arr)):>6.2f}s | MedAE={np.median(np.abs(arr)):>6.2f}s | Bias={np.mean(arr):>+6.2f}s | RMSE={np.sqrt(np.mean(arr**2)):>6.2f}s"
            )

    print("\n" + "=" * 95)
    print("4. TERMINAL STATIONS NOISE ANALYSIS (FIRST SEGMENT 0->1 & LAST SEGMENT N-1->N vs INTERIOR)")
    print("=" * 95)
    df_seg["pos_type"] = "Interior (1 .. N-1)"
    df_seg.loc[df_seg["ord_a"] == 0, "pos_type"] = "First Segment (0 -> 1)"
    df_seg.loc[df_seg["ord_b"] == df_seg["max_ord"], "pos_type"] = "Last Segment (N-1 -> N)"

    for p_type, grp in df_seg.groupby("pos_type"):
        cv_per_seg = grp.groupby(["route_code", "direction", "ord_a"])["tt"].apply(lambda s: np.std(s) / max(1.0, np.mean(s)) if len(s) >= 5 else np.nan).dropna()
        print(
            f"  * {p_type:<26}: Samples={len(grp):>9,} | Median Speed={grp['spd_kmh'].median():>5.2f} km/h | "
            f"P10 Speed={np.percentile(grp['spd_kmh'], 10):>5.2f} km/h | Median Coeff-of-Variation (Std/Mean)={cv_per_seg.median():.3f}"
        )

    # Multi-station Test ETA: All station pairs vs Interior-Only (1 <= start_order < end_order <= max_ord - 1)
    all_gt15_err = []
    int_gt15_err = []
    terminal_origin_err = []
    terminal_dest_err = []

    for r_code, d_str, st_list, arrivals in test_trips_info:
        max_o = st_list[-1][0]
        ord_to_k = {st[0]: idx_k for idx_k, st in enumerate(st_list)}
        sorted_ords = sorted(arrivals.keys())
        for i_a in range(len(sorted_ords)):
            o_start = sorted_ords[i_a]
            k_start = ord_to_k[o_start]
            t_start = arrivals[o_start]
            dt_obj = datetime.fromtimestamp(t_start, tz=TZ_HANOI)
            wknd = 1 if dt_obj.weekday() >= 5 else 0
            hr = min(22, max(5, dt_obj.hour))
            for i_b in range(i_a + 1, len(sorted_ords)):
                o_end = sorted_ords[i_b]
                k_end = ord_to_k[o_end]
                n_hops = k_end - k_start
                actual_eta = arrivals[o_end] - t_start
                if actual_eta <= 0 or actual_eta > 7200:
                    continue
                pred_eta = 0.0
                for k_s in range(k_start, k_end):
                    u, v = st_list[k_s][0], st_list[k_s + 1][0]
                    seg_k = (r_code, d_str, u, v)
                    ca = map_a.get((*seg_k, wknd, hr))
                    pred_eta += ca["median"] if (ca and ca["count"] >= 3) else map_a_day.get((*seg_k, wknd), seg_glob.get(seg_k, 60.0))
                err = actual_eta - pred_eta
                if n_hops > 15:
                    all_gt15_err.append(err)
                    if o_start >= 1 and o_end <= max_o - 1:
                        int_gt15_err.append(err)
                if o_start == 0:
                    terminal_origin_err.append(err)
                if o_end == max_o:
                    terminal_dest_err.append(err)

    print("\n  [Multi-Station ETA Impact of Terminal Boundary Exclusion on Test Set]:")
    for lbl, arr_l in [
        ("Origin Terminal Start (ord_start == 0)         ", terminal_origin_err),
        ("Destination Terminal End (ord_end == N)        ", terminal_dest_err),
        ("All >15 Station Pairs (Including 0 and N)      ", all_gt15_err),
        ("Active In-Transit Only (1 <= ord < N, >15 hops)", int_gt15_err),
    ]:
        if not arr_l:
            continue
        a = np.array(arr_l)
        print(f"    * {lbl}: N={len(a):>9,} | MAE={np.mean(np.abs(a)):>6.2f}s | MedAE={np.median(np.abs(a)):>6.2f}s | RMSE={np.sqrt(np.mean(a**2)):>6.2f}s")


if __name__ == "__main__":
    main()
