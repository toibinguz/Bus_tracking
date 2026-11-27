"""Full-dataset verification & speed benchmark of C++17 native kernels vs Python (all 48 routes, read-only)."""

from __future__ import annotations

import ctypes
import gc
import os
import sqlite3
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.dataset as ds_pa

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from config.hardware_guard import check_memory_pressure, set_process_below_normal_priority
from config.system_config import (
    CANONICAL_START_DATE,
    DEFAULT_DB_PATH,
    DEFAULT_LAKEHOUSE_ROOT,
    HANOI_BBOX,
    MIN_CLUSTER_ROUTE_DAYS,
    TRAIN_SPLIT_END_DATE,
)
from experiments.hmm_direction_eval.eval_dual_hmm_direction import load_canonical_shapes
from experiments.hmm_direction_eval.eval_joint_bidirectional_hmm import JointBidirectionalHMM
from module_3_bus_eta_prediction.step_3_1_historical_baseline_model.baseline_matrix_builder import (
    get_active_corridor_stations,
)


def load_cpp_lib():
    if hasattr(os, "add_dll_directory") and os.path.isdir(r"C:\msys64\ucrt64\bin"):
        os.add_dll_directory(r"C:\msys64\ucrt64\bin")
    dll_path = Path(__file__).resolve().parent / "bus_native_core.dll"
    lib = ctypes.CDLL(str(dll_path))

    f64 = np.ctypeslib.ndpointer(dtype=np.float64, flags="C_CONTIGUOUS")
    i32 = np.ctypeslib.ndpointer(dtype=np.int32, flags="C_CONTIGUOUS")
    i64 = np.ctypeslib.ndpointer(dtype=np.int64, flags="C_CONTIGUOUS")

    lib.cpp_project_route_full.argtypes = [
        ctypes.c_int, f64, f64, f64,
        ctypes.c_int, f64, f64, f64,
        ctypes.c_int, i32, i32,
        ctypes.c_int, i64, i32, f64, i32, f64, f64, i32,
        ctypes.POINTER(ctypes.c_int32),
        i32, i32, f64, f64, i32, f64,
    ]
    lib.cpp_project_route_full.restype = None

    lib.cpp_build_route_baseline.argtypes = [
        ctypes.c_double, ctypes.c_int, f64,
        ctypes.c_double, ctypes.c_int, f64,
        ctypes.c_int64, ctypes.c_int64,
        ctypes.c_int, i32, i32, f64, f64,
        ctypes.POINTER(ctypes.c_int32),
        i32, i32, i32, i32, i32, i32, f64, f64, f64, f64, f64, f64,
    ]
    lib.cpp_build_route_baseline.restype = None

    lib.cpp_run_joint_bidirectional_hmm.argtypes = [
        ctypes.c_int, f64, f64, f64,
        ctypes.c_int, f64, f64, f64,
        ctypes.c_int, i64,
        f64, f64, f64,
        i32, i32, f64,
    ]
    lib.cpp_run_joint_bidirectional_hmm.restype = None
    return lib


def verify_silver_projection_all_48(lib, db_path: Path):
    print("\n=== 1. KIỂM CHỨNG C++ SILVER PROJECTION TRÊN TOÀN BỘ 48 TUYẾN (12.58M RAW PINGS) ===")
    conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    cur = conn.cursor()

    st_rows = cur.execute(
        """
        SELECT route_id, station_id, MIN(direction)
        FROM canonical_station_master
        GROUP BY route_id, station_id
        HAVING COUNT(DISTINCT direction) = 1
        """
    ).fetchall()
    st_by_route = defaultdict(list)
    for rid, sid, d in st_rows:
        st_by_route[int(rid)].append((int(sid), 0 if d == "go" else 1))

    shapes = {}
    for rid, d, po, lat, lon, cum in cur.execute(
        "SELECT route_id, direction, point_order, lat, lon, cum_distance_m FROM canonical_shape_master ORDER BY route_id, direction, point_order"
    ).fetchall():
        shapes.setdefault(int(rid), {"go": [], "re": []})
        if d.lower() in ("go", "re"):
            shapes[int(rid)][d.lower()].append((lat, lon, cum))

    active_routes = cur.execute(
        """
        SELECT DISTINCT r.route_id, r.route_code, count(t.ping_id) as pings
        FROM canonical_route_master r
        JOIN vehicle_unique_pings t ON r.route_id = t.route_id
        WHERE r.route_id IN (SELECT DISTINCT route_id FROM canonical_shape_master)
          AND t.device_update_time >= ?
        GROUP BY r.route_id, r.route_code
        HAVING count(DISTINCT t.date_tag) >= ?
        ORDER BY pings DESC
        """,
        (CANONICAL_START_DATE, MIN_CLUSTER_ROUTE_DAYS),
    ).fetchall()

    t_wall0 = time.perf_counter()
    cpp_compute_total = 0.0
    total_raw = 0
    total_cpp = 0
    total_db = 0
    matched_ids_total = 0
    dir_mismatches = 0
    max_ds = 0.0
    max_dct = 0.0
    max_dspd = 0.0
    exact_s_ct = 0
    spd_both = 0
    spd_exact = 0

    for idx_r, (rid, rc, _) in enumerate(active_routes, 1):
        rid = int(rid)
        raw = cur.execute(
            """
            SELECT ping_id, vehicle_id, device_epoch, direction, lat, lon, current_station_id
            FROM vehicle_unique_pings
            WHERE route_id = ? AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ? AND device_update_time >= ?
            ORDER BY vehicle_id, device_epoch, ping_id
            """,
            (rid, HANOI_BBOX["min_lat"], HANOI_BBOX["max_lat"], HANOI_BBOX["min_lon"], HANOI_BBOX["max_lon"], CANONICAL_START_DATE),
        ).fetchall()
        n_raw = len(raw)
        total_raw += n_raw

        raw_arr = np.array([(r[0], r[1], r[2], r[3], r[4], r[5], r[6] if r[6] is not None else 0) for r in raw], dtype=np.float64)
        ping_ids = np.ascontiguousarray(raw_arr[:, 0], dtype=np.int64)
        veh_ids = np.ascontiguousarray(raw_arr[:, 1], dtype=np.int32)
        epochs = np.ascontiguousarray(raw_arr[:, 2], dtype=np.float64)
        raw_dirs = np.ascontiguousarray(raw_arr[:, 3], dtype=np.int32)
        lats = np.ascontiguousarray(raw_arr[:, 4], dtype=np.float64)
        lons = np.ascontiguousarray(raw_arr[:, 5], dtype=np.float64)
        st_ids = np.ascontiguousarray(raw_arr[:, 6], dtype=np.int32)
        del raw, raw_arr

        sh = shapes.get(rid, {"go": [], "re": []})
        empty = np.zeros(0, dtype=np.float64)
        g_pts = np.array(sh["go"], dtype=np.float64) if sh["go"] else np.zeros((0, 3), dtype=np.float64)
        r_pts = np.array(sh["re"], dtype=np.float64) if sh["re"] else np.zeros((0, 3), dtype=np.float64)
        st_list = st_by_route.get(rid, [])
        sd_ids = np.array([x[0] for x in st_list], dtype=np.int32)
        sd_vals = np.array([x[1] for x in st_list], dtype=np.int32)

        out_cnt = ctypes.c_int32(0)
        out_idx = np.empty(n_raw, dtype=np.int32)
        out_dir = np.empty(n_raw, dtype=np.int32)
        out_s = np.empty(n_raw, dtype=np.float64)
        out_ct = np.empty(n_raw, dtype=np.float64)
        out_hspd = np.empty(n_raw, dtype=np.int32)
        out_spd = np.empty(n_raw, dtype=np.float64)

        t_c0 = time.perf_counter()
        lib.cpp_project_route_full(
            len(g_pts),
            np.ascontiguousarray(g_pts[:, 0]) if len(g_pts) else empty,
            np.ascontiguousarray(g_pts[:, 1]) if len(g_pts) else empty,
            np.ascontiguousarray(g_pts[:, 2]) if len(g_pts) else empty,
            len(r_pts),
            np.ascontiguousarray(r_pts[:, 0]) if len(r_pts) else empty,
            np.ascontiguousarray(r_pts[:, 1]) if len(r_pts) else empty,
            np.ascontiguousarray(r_pts[:, 2]) if len(r_pts) else empty,
            len(sd_ids), sd_ids, sd_vals,
            n_raw, ping_ids, veh_ids, epochs, raw_dirs, lats, lons, st_ids,
            ctypes.byref(out_cnt),
            out_idx, out_dir, out_s, out_ct, out_hspd, out_spd,
        )
        cpp_compute_total += time.perf_counter() - t_c0

        k = int(out_cnt.value)
        total_cpp += k
        cpp_pids = ping_ids[out_idx[:k]]
        cpp_map = {
            int(pid): (int(out_dir[t]), float(out_s[t]), float(out_ct[t]), float(out_spd[t]) if out_hspd[t] else None)
            for t, pid in enumerate(cpp_pids)
        }

        # Đọc bảng chuẩn route_projected_telemetry của tuyến để đối chiếu 1-1
        db_rows = cur.execute(
            "SELECT ping_id, direction, s_bus_m, cross_track_m, derived_speed_kmh FROM route_projected_telemetry WHERE route_id = ?",
            (rid,),
        ).fetchall()
        total_db += len(db_rows)
        for pid, d_str, s_db, ct_db, spd_db in db_rows:
            rec = cpp_map.get(int(pid))
            if rec is None:
                continue
            matched_ids_total += 1
            d_c, s_c, ct_c, spd_c = rec
            if d_c != (0 if d_str == "go" else 1):
                dir_mismatches += 1
            ds = abs(s_c - float(s_db))
            dct = abs(ct_c - float(ct_db))
            if ds > max_ds: max_ds = ds
            if dct > max_dct: max_dct = dct
            if ds == 0.0 and dct == 0.0:
                exact_s_ct += 1
            if spd_c is not None and spd_db is not None:
                spd_both += 1
                dspd = abs(spd_c - float(spd_db))
                if dspd > max_dspd: max_dspd = dspd
                if dspd < 1e-6:
                    spd_exact += 1

        if idx_r % 12 == 0 or idx_r == len(active_routes):
            print(f"  [{idx_r:02d}/{len(active_routes)}] Route {rc:<5} | cpp_compute_cum={cpp_compute_total:.2f}s | exact_s_ct={exact_s_ct:,}/{matched_ids_total:,}", flush=True)
        del ping_ids, veh_ids, epochs, raw_dirs, lats, lons, st_ids, out_idx, out_dir, out_s, out_ct, out_hspd, out_spd, cpp_map, db_rows
        if idx_r % 8 == 0:
            gc.collect()
            check_memory_pressure(label=f"cpp_silver={rc}")

    conn.close()
    wall_total = time.perf_counter() - t_wall0
    print(
        f"  KẾT QUẢ C++ SILVER (48 tuyến):\n"
        f"    - Raw pings: {total_raw:,} | C++ projected: {total_cpp:,} | DB SQLite: {total_db:,}\n"
        f"    - Khớp ping_id: {matched_ids_total:,}/{total_db:,} ({matched_ids_total/total_db*100:.4f}%) | Sai lệch chiều: {dir_mismatches}\n"
        f"    - Exact bit-for-bit (s & ct): {exact_s_ct:,}/{matched_ids_total:,} ({exact_s_ct/matched_ids_total*100:.4f}%)\n"
        f"    - Max |Δs|={max_ds:.4f}m, Max |Δct|={max_dct:.4f}m, Max |Δspeed|={max_dspd:.4f} km/h (exact speed: {spd_exact:,}/{spd_both:,})\n"
        f"    - Thời gian C++ thuần (compute 48 tuyến): {cpp_compute_total:.2f}s ({total_raw/cpp_compute_total:,.0f} raw pings/s) | Tổng (gồm đọc & đối chiếu SQLite): {wall_total:.2f}s"
    )


def verify_baseline_matrix_all_48(lib, db_path: Path):
    print("\n=== 2. KIỂM CHỨNG C++ BASELINE MATRIX TRÊN TOÀN BỘ 48 TUYẾN (9.84M SILVER -> 169,830 Ô) ===")
    conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    cur = conn.cursor()

    shape_len = {(r, d): float(l) for r, d, l in cur.execute(
        "SELECT route_code, direction, MAX(cum_distance_m) FROM canonical_shape_master GROUP BY route_code, direction"
    ).fetchall()}
    stations_map = defaultdict(list)
    for rc, d_str, st_ord, st_id, st_name, s_m in cur.execute(
        "SELECT route_code, direction, station_order, station_id, station_name, cum_distance_m FROM canonical_station_master ORDER BY route_code, direction, station_order"
    ).fetchall():
        stations_map[(rc, d_str)].append((int(st_ord), int(st_id), str(st_name), float(s_m)))

    db_cells = {}
    for rc, d_str, o_a, o_b, dt_v, hr_v, cnt, qt, s_len, p10, p50, p90, mean_v, std_v in cur.execute(
        "SELECT route_code, direction, from_station_order, to_station_order, day_type, hour_slot, sample_count, quality_tier, segment_length_m, tt_p10_sec, tt_p50_sec, tt_p90_sec, tt_mean_sec, tt_std_sec FROM agg_segment_travel_times"
    ).fetchall():
        db_cells[(rc, d_str, int(o_a), int(o_b), int(dt_v), int(hr_v))] = (
            int(cnt), int(qt), float(s_len), float(p10), float(p50), float(p90), float(mean_v), float(std_v)
        )
    conn.close()

    fit_end_day = (date.fromisoformat("2026-10-17") - date(1970, 1, 1)).days
    train_end_day = (date.fromisoformat(TRAIN_SPLIT_END_DATE) - date(1970, 1, 1)).days

    silver_dir = ROOT / DEFAULT_LAKEHOUSE_ROOT / "silver" / "route_projected_telemetry"
    route_dirs = sorted(d for d in os.listdir(silver_dir) if d.startswith("route_code="))
    dt_part = ds_pa.partitioning(pa.schema([("dt", pa.string())]), flavor="hive")

    t_wall0 = time.perf_counter()
    cpp_compute_total = 0.0
    total_pings = 0
    total_cpp_cells = 0
    matched_cells = 0
    cnt_exact = 0
    tier_exact = 0
    max_dp50 = 0.0
    max_dmean = 0.0
    max_dp10 = 0.0
    max_dp90 = 0.0
    max_dstd = 0.0

    for d_name in route_dirs:
        rc = d_name.split("=", 1)[1]
        ds_r = ds_pa.dataset(str(silver_dir / d_name), format="parquet", partitioning=dt_part)
        df = ds_r.to_table(columns=["vehicle_id", "direction", "device_epoch", "s_bus_m"]).to_pandas()
        total_pings += len(df)
        df["dir_int"] = (df["direction"] == "re").astype(np.int32)
        df = df.sort_values(["vehicle_id", "dir_int", "device_epoch"], kind="mergesort")

        veh_ids = np.ascontiguousarray(df["vehicle_id"].to_numpy(), dtype=np.int32)
        dir_ints = np.ascontiguousarray(df["dir_int"].to_numpy(), dtype=np.int32)
        epochs = np.ascontiguousarray(df["device_epoch"].to_numpy(), dtype=np.float64)
        s_vals = np.ascontiguousarray(df["s_bus_m"].to_numpy(), dtype=np.float64)
        del df

        st_go_full = stations_map.get((rc, "go"), [])
        st_re_full = stations_map.get((rc, "re"), [])
        act_go = get_active_corridor_stations(st_go_full)
        act_re = get_active_corridor_stations(st_re_full)
        max_cells = (max(0, len(act_go) - 1) + max(0, len(act_re) - 1)) * 51 + 16

        s_go_arr = np.ascontiguousarray([x[3] for x in st_go_full], dtype=np.float64)
        s_re_arr = np.ascontiguousarray([x[3] for x in st_re_full], dtype=np.float64)

        out_nc = ctypes.c_int32(0)
        o_dir = np.empty(max_cells, dtype=np.int32)
        o_k = np.empty(max_cells, dtype=np.int32)
        o_dt = np.empty(max_cells, dtype=np.int32)
        o_hr = np.empty(max_cells, dtype=np.int32)
        o_neff = np.empty(max_cells, dtype=np.int32)
        o_tier = np.empty(max_cells, dtype=np.int32)
        o_slen = np.empty(max_cells, dtype=np.float64)
        o_p10 = np.empty(max_cells, dtype=np.float64)
        o_p50 = np.empty(max_cells, dtype=np.float64)
        o_p90 = np.empty(max_cells, dtype=np.float64)
        o_mean = np.empty(max_cells, dtype=np.float64)
        o_std = np.empty(max_cells, dtype=np.float64)

        t_c0 = time.perf_counter()
        lib.cpp_build_route_baseline(
            shape_len.get((rc, "go"), 0.0), len(s_go_arr), s_go_arr,
            shape_len.get((rc, "re"), 0.0), len(s_re_arr), s_re_arr,
            fit_end_day, train_end_day,
            len(veh_ids), veh_ids, dir_ints, epochs, s_vals,
            ctypes.byref(out_nc),
            o_dir, o_k, o_dt, o_hr, o_neff, o_tier, o_slen, o_p10, o_p50, o_p90, o_mean, o_std,
        )
        cpp_compute_total += time.perf_counter() - t_c0

        nc = int(out_nc.value)
        total_cpp_cells += nc
        acts = (act_go, act_re)
        for i in range(nc):
            d_i = int(o_dir[i])
            k_i = int(o_k[i])
            d_str = "go" if d_i == 0 else "re"
            ord_a = acts[d_i][k_i][0]
            ord_b = acts[d_i][k_i + 1][0]
            key = (rc, d_str, ord_a, ord_b, int(o_dt[i]), int(o_hr[i]))
            ref = db_cells.get(key)
            if ref is None:
                continue
            matched_cells += 1
            if int(o_neff[i]) == ref[0]:
                cnt_exact += 1
            if int(o_tier[i]) == ref[1]:
                tier_exact += 1
            max_dp10 = max(max_dp10, abs(float(o_p10[i]) - ref[3]))
            max_dp50 = max(max_dp50, abs(float(o_p50[i]) - ref[4]))
            max_dp90 = max(max_dp90, abs(float(o_p90[i]) - ref[5]))
            max_dmean = max(max_dmean, abs(float(o_mean[i]) - ref[6]))
            max_dstd = max(max_dstd, abs(float(o_std[i]) - ref[7]))

        del veh_ids, dir_ints, epochs, s_vals
        check_memory_pressure(label=f"cpp_base={rc}")

    wall_total = time.perf_counter() - t_wall0
    print(
        f"  KẾT QUẢ C++ BASELINE MATRIX (48 tuyến, {total_pings:,} Silver pings):\n"
        f"    - Số ô: C++ {total_cpp_cells:,} vs SQLite {len(db_cells):,} | Khớp khóa: {matched_cells:,}\n"
        f"    - Exact sample_count: {cnt_exact:,}/{matched_cells:,} | Exact quality_tier: {tier_exact:,}/{matched_cells:,}\n"
        f"    - Max |Δp50|={max_dp50:.4f}s, Max |Δmean|={max_dmean:.4f}s, Max |Δp10|={max_dp10:.4f}s, Max |Δp90|={max_dp90:.4f}s, Max |Δstd|={max_dstd:.4f}s\n"
        f"    - Thời gian C++ thuần: {cpp_compute_total:.3f}s ({total_pings/cpp_compute_total:,.0f} pings/s) | Tổng (gồm đọc Parquet + sort + đối chiếu): {wall_total:.2f}s"
    )


def verify_joint_hmm_parity_and_speed(lib, db_path: Path):
    print("\n=== 3. KIỂM CHỨNG C++ vs PYTHON JOINT BIDIRECTIONAL HMM (5 TUYẾN, ~170K PINGS) ===")
    routes = ["01", "02", "27", "32", "E03"]
    with sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True) as conn:
        shapes_model, rmap, _ = load_canonical_shapes(conn, routes)
        raw_shapes = {}
        for rc in routes:
            for d in ("go", "re"):
                pts = conn.execute(
                    "SELECT lat, lon, cum_distance_m FROM canonical_shape_master WHERE route_id=? AND direction=? ORDER BY point_order",
                    (rmap[rc], d),
                ).fetchall()
                raw_shapes[(rc, d)] = np.array(pts, dtype=np.float64)

        total_pings = 0
        py_time = 0.0
        cpp_time = 0.0
        both_valid = 0
        dir_agree = 0
        max_ds = 0.0
        valid_agree = 0

        for rc in routes:
            rows = conn.execute(
                """
                SELECT vehicle_id, device_epoch, lat, lon
                FROM vehicle_unique_pings
                WHERE route_id = ? AND date_tag BETWEEN '2026-11-16' AND '2026-11-18'
                  AND direction IN (0, 1) AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?
                ORDER BY vehicle_id, device_epoch
                """,
                (rmap[rc], HANOI_BBOX["min_lat"], HANOI_BBOX["max_lat"], HANOI_BBOX["min_lon"], HANOI_BBOX["max_lon"]),
            ).fetchall()
            n = len(rows)
            total_pings += n
            arr = np.array(rows, dtype=np.float64)
            vids = arr[:, 0].astype(np.int64)
            eps = np.ascontiguousarray(arr[:, 1], dtype=np.float64)
            lats = np.ascontiguousarray(arr[:, 2], dtype=np.float64)
            lons = np.ascontiguousarray(arr[:, 3], dtype=np.float64)

            splits = np.flatnonzero(vids[1:] != vids[:-1]) + 1
            offsets = np.concatenate(([0], splits, [n])).astype(np.int64)
            n_runs = len(offsets) - 1

            # Python
            py_v = np.zeros(n, dtype=np.int32)
            py_d = np.full(n, -1, dtype=np.int32)
            py_s = np.zeros(n, dtype=np.float64)
            t0 = time.perf_counter()
            for r in range(n_runs):
                j = JointBidirectionalHMM(shapes_model[rc]["go"], shapes_model[rc]["re"])
                for idx in range(int(offsets[r]), int(offsets[r + 1])):
                    d_str, s_v, _ = j.update(float(eps[idx]), float(lats[idx]), float(lons[idx]))
                    if d_str is not None and s_v is not None:
                        py_v[idx] = 1
                        py_d[idx] = 0 if d_str == "go" else 1
                        py_s[idx] = s_v
            py_time += time.perf_counter() - t0

            # C++
            g = raw_shapes[(rc, "go")]
            r_sh = raw_shapes[(rc, "re")]
            cpp_v = np.zeros(n, dtype=np.int32)
            cpp_d = np.full(n, -1, dtype=np.int32)
            cpp_s = np.zeros(n, dtype=np.float64)
            t1 = time.perf_counter()
            lib.cpp_run_joint_bidirectional_hmm(
                len(g), np.ascontiguousarray(g[:, 0]), np.ascontiguousarray(g[:, 1]), np.ascontiguousarray(g[:, 2]),
                len(r_sh), np.ascontiguousarray(r_sh[:, 0]), np.ascontiguousarray(r_sh[:, 1]), np.ascontiguousarray(r_sh[:, 2]),
                n_runs, offsets, eps, lats, lons,
                cpp_v, cpp_d, cpp_s,
            )
            cpp_time += time.perf_counter() - t1

            valid_agree += int(np.sum(py_v == cpp_v))
            mask = (py_v == 1) & (cpp_v == 1)
            both_valid += int(np.sum(mask))
            dir_agree += int(np.sum(py_d[mask] == cpp_d[mask]))
            same_d = mask & (py_d == cpp_d)
            if np.any(same_d):
                max_ds = max(max_ds, float(np.max(np.abs(py_s[same_d] - cpp_s[same_d]))))

    print(
        f"  KẾT QUẢ JOINT HMM (5 tuyến, {total_pings:,} pings):\n"
        f"    - Python: {py_time:.2f}s ({total_pings/py_time:,.0f} pings/s) | C++: {cpp_time:.3f}s ({total_pings/cpp_time:,.0f} pings/s) -> Speedup {py_time/cpp_time:.1f}x\n"
        f"    - Parity: valid_mask={valid_agree:,}/{total_pings:,} ({valid_agree/total_pings*100:.4f}%), dir_agree={dir_agree:,}/{both_valid:,} ({dir_agree/both_valid*100:.4f}%), max|Δs|={max_ds:.4f}m"
    )


def main():
    set_process_below_normal_priority()
    db_path = ROOT / DEFAULT_DB_PATH
    lib = load_cpp_lib()
    verify_joint_hmm_parity_and_speed(lib, db_path)
    verify_baseline_matrix_all_48(lib, db_path)
    verify_silver_projection_all_48(lib, db_path)


if __name__ == "__main__":
    main()
