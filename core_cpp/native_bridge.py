"""C++17 cross-platform native bridge (.dll on Windows, .so on Linux/Docker)."""

from __future__ import annotations

import ctypes
from datetime import date
import os
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from config.system_config import TRAIN_SPLIT_END_DATE

_NATIVE_DIR = Path(__file__).resolve().parent
_LIB: Optional[ctypes.CDLL] = None
_LOAD_TRIED = False


def _find_native_binary() -> Optional[Path]:
    if os.name == "nt":
        cand = _NATIVE_DIR / "bus_native_core.dll"
        return cand if cand.is_file() else None
    for cand in (
        Path("/opt/spark/native/libbus_native_core.so"),
        _NATIVE_DIR / "libbus_native_core.so",
    ):
        if cand.is_file():
            return cand
    return None


def _load_native_lib() -> Optional[ctypes.CDLL]:
    global _LIB, _LOAD_TRIED
    if _LOAD_TRIED:
        return _LIB
    _LOAD_TRIED = True
    bin_path = _find_native_binary()
    if bin_path is None:
        return None
    try:
        if os.name == "nt" and hasattr(os, "add_dll_directory") and os.path.isdir(r"C:\msys64\ucrt64\bin"):
            os.add_dll_directory(r"C:\msys64\ucrt64\bin")
        lib = ctypes.CDLL(str(bin_path))

        f32 = np.ctypeslib.ndpointer(dtype=np.float32, flags="C_CONTIGUOUS")
        f64 = np.ctypeslib.ndpointer(dtype=np.float64, flags="C_CONTIGUOUS")
        u8 = np.ctypeslib.ndpointer(dtype=np.uint8, flags="C_CONTIGUOUS")
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

        lib.cpp_extract_route_causal_features.argtypes = [
            ctypes.c_int32,
            f64, f64, f64,
            i32, i64, f64,
            u8, f64, f64, f64, f64, f64, i32,
            i32, f64, f64, f64, f64, f64,
            ctypes.c_int32, ctypes.c_int32, f64, i32, i32, f64,
            ctypes.c_double, ctypes.c_double, ctypes.c_double, ctypes.c_double,
            ctypes.POINTER(ctypes.c_int32),
        ]
        lib.cpp_extract_route_causal_features.restype = ctypes.c_void_p

        lib.cpp_get_causal_feature_counts.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_int64),
            i64,
        ]
        lib.cpp_get_causal_feature_counts.restype = None

        lib.cpp_copy_causal_features.argtypes = [
            ctypes.c_void_p,
            f32, i32, i64, i64, i32, f64, f64, f64, f64, f64, f64,
        ]
        lib.cpp_copy_causal_features.restype = None

        lib.cpp_free_causal_features.argtypes = [ctypes.c_void_p]
        lib.cpp_free_causal_features.restype = None

        _LIB = lib
    except Exception:
        _LIB = None
    return _LIB


def is_native_available() -> bool:
    """Return True if the compiled C++17 native kernel (.dll/.so) loads cleanly."""
    return _load_native_lib() is not None


def _shape_arrays(shape_pts: Sequence[Tuple[float, float, float, float]]):
    if not shape_pts or len(shape_pts) < 2:
        empty = np.zeros(0, dtype=np.float64)
        return 0, empty, empty, empty
    arr = np.asarray(shape_pts, dtype=np.float64)
    return (
        len(arr),
        np.ascontiguousarray(arr[:, 1], dtype=np.float64),
        np.ascontiguousarray(arr[:, 2], dtype=np.float64),
        np.ascontiguousarray(arr[:, 3], dtype=np.float64),
    )


def project_route_pings_native(
    route_id: int,
    route_code: str,
    pings: Sequence[Tuple[Any, ...]],
    shapes: Mapping[str, Sequence[Tuple[float, float, float, float]]],
    st_dir: Mapping[Tuple[int, int], str],
) -> Optional[List[Tuple[Any, ...]]]:
    """Project raw pings of 1 route using C++17 RouteHMM; returns None if binary unavailable."""
    lib = _load_native_lib()
    if lib is None:
        return None
    n = len(pings)
    if n == 0:
        return []

    n_go, lat_go, lon_go, cum_go = _shape_arrays(shapes.get("go", ()))
    n_re, lat_re, lon_re, cum_re = _shape_arrays(shapes.get("re", ()))
    if n_go < 2 and n_re < 2:
        return []

    route_st = [
        (int(sid), 0 if str(d).lower() == "go" else 1)
        for (rid, sid), d in st_dir.items()
        if rid == route_id and str(d).lower() in ("go", "re")
    ]
    sd_ids = np.ascontiguousarray([x[0] for x in route_st], dtype=np.int32)
    sd_vals = np.ascontiguousarray([x[1] for x in route_st], dtype=np.int32)

    ping_ids = np.empty(n, dtype=np.int64)
    veh_ids = np.empty(n, dtype=np.int32)
    epochs = np.empty(n, dtype=np.float64)
    raw_dirs = np.empty(n, dtype=np.int32)
    lats = np.empty(n, dtype=np.float64)
    lons = np.empty(n, dtype=np.float64)
    st_ids = np.empty(n, dtype=np.int32)

    for idx, row in enumerate(pings):
        ping_ids[idx] = int(row[0])
        veh_ids[idx] = int(row[1])
        epochs[idx] = float(row[4])
        raw_dirs[idx] = int(row[5]) if row[5] is not None else -1
        lats[idx] = float(row[6])
        lons[idx] = float(row[7])
        st_ids[idx] = int(row[8]) if row[8] is not None else 0

    out_cnt = ctypes.c_int32(0)
    o_idx = np.empty(n, dtype=np.int32)
    o_dir = np.empty(n, dtype=np.int32)
    o_s = np.empty(n, dtype=np.float64)
    o_ct = np.empty(n, dtype=np.float64)
    o_hspd = np.empty(n, dtype=np.int32)
    o_spd = np.empty(n, dtype=np.float64)

    lib.cpp_project_route_full(
        n_go, lat_go, lon_go, cum_go,
        n_re, lat_re, lon_re, cum_re,
        len(sd_ids), sd_ids, sd_vals,
        n, ping_ids, veh_ids, epochs, raw_dirs, lats, lons, st_ids,
        ctypes.byref(out_cnt),
        o_idx, o_dir, o_s, o_ct, o_hspd, o_spd,
    )

    k = int(out_cnt.value)
    records: List[Tuple[Any, ...]] = []
    for t in range(k):
        row = pings[int(o_idx[t])]
        d_str = "go" if int(o_dir[t]) == 0 else "re"
        spd_val = float(o_spd[t]) if int(o_hspd[t]) else None
        records.append(
            (
                row[0],
                route_code,
                route_id,
                row[1],
                row[2],
                row[3],
                row[4],
                d_str,
                row[6],
                row[7],
                float(o_s[t]),
                float(o_ct[t]),
                spd_val,
            )
        )
    return records


def build_route_baseline_native(
    shape_len_go: float,
    stations_go_full: Sequence[Tuple[int, int, str, float]],
    shape_len_re: float,
    stations_re_full: Sequence[Tuple[int, int, str, float]],
    vehicle_ids: np.ndarray,
    dir_ints: np.ndarray,
    epochs: np.ndarray,
    s_vals: np.ndarray,
    fit_end_date: str = TRAIN_SPLIT_END_DATE,
    train_end_date: str = TRAIN_SPLIT_END_DATE,
) -> Optional[List[Dict[str, Any]]]:
    """Compute segment baseline cells for 1 route in C++17; returns None if binary unavailable."""
    lib = _load_native_lib()
    if lib is None:
        return None

    act_go = list(stations_go_full[1:-1]) if len(stations_go_full) >= 4 else list(stations_go_full)
    act_re = list(stations_re_full[1:-1]) if len(stations_re_full) >= 4 else list(stations_re_full)
    max_cells = (max(0, len(act_go) - 1) + max(0, len(act_re) - 1)) * 51 + 16
    if max_cells <= 16:
        return []

    s_go_arr = np.ascontiguousarray([float(x[3]) for x in stations_go_full], dtype=np.float64)
    s_re_arr = np.ascontiguousarray([float(x[3]) for x in stations_re_full], dtype=np.float64)
    fit_day = (date.fromisoformat(fit_end_date) - date(1970, 1, 1)).days
    train_day = (date.fromisoformat(train_end_date) - date(1970, 1, 1)).days

    v_arr = np.ascontiguousarray(vehicle_ids, dtype=np.int32)
    d_arr = np.ascontiguousarray(dir_ints, dtype=np.int32)
    e_arr = np.ascontiguousarray(epochs, dtype=np.float64)
    s_arr = np.ascontiguousarray(s_vals, dtype=np.float64)

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

    lib.cpp_build_route_baseline(
        float(shape_len_go), len(s_go_arr), s_go_arr,
        float(shape_len_re), len(s_re_arr), s_re_arr,
        fit_day, train_day,
        len(v_arr), v_arr, d_arr, e_arr, s_arr,
        ctypes.byref(out_nc),
        o_dir, o_k, o_dt, o_hr, o_neff, o_tier, o_slen, o_p10, o_p50, o_p90, o_mean, o_std,
    )

    acts = (act_go, act_re)
    cells: List[Dict[str, Any]] = []
    for i in range(int(out_nc.value)):
        d_i = int(o_dir[i])
        k_i = int(o_k[i])
        st_a = acts[d_i][k_i]
        st_b = acts[d_i][k_i + 1]
        cells.append(
            {
                "direction": "go" if d_i == 0 else "re",
                "from_station_order": int(st_a[0]),
                "to_station_order": int(st_b[0]),
                "from_station_id": int(st_a[1]),
                "to_station_id": int(st_b[1]),
                "from_station_name": str(st_a[2]),
                "to_station_name": str(st_b[2]),
                "segment_length_m": float(o_slen[i]),
                "day_type": int(o_dt[i]),
                "hour_slot": int(o_hr[i]),
                "sample_count": int(o_neff[i]),
                "quality_tier": int(o_tier[i]),
                "tt_p10_sec": float(o_p10[i]),
                "tt_p50_sec": float(o_p50[i]),
                "tt_p90_sec": float(o_p90[i]),
                "tt_mean_sec": float(o_mean[i]),
                "tt_std_sec": float(o_std[i]),
            }
        )
    return cells


def extract_route_causal_features_native(
    *,
    route_id_idx: int,
    route_len_by_dir: Mapping[int, float],
    route_base_speed_by_dir: Mapping[int, float],
    route_spacing_by_dir: Mapping[int, float],
    corridors_by_dir: Mapping[int, Sequence[Tuple[int, int, str, float]]],
    baseline_lookup: Any,
    route_id_for_lookup: Any,
    incidents_by_dir: Mapping[int, Sequence[Tuple[float, float, float, float, float]]],
    n_vehicles: int,
    obs_epoch: np.ndarray,
    obs_dir: np.ndarray,
    obs_veh_idx: np.ndarray,
    obs_s_bus: np.ndarray,
    baseline_cutoff_epoch: float,
    validation_epoch: float,
    test_epoch: float,
    cadence_sec: float,
) -> Optional[Tuple[Dict[str, np.ndarray], Dict[str, int]]]:
    """Extract 40-column causal features & labels across both directions of 1 route in C++17; None if unavailable."""
    lib = _load_native_lib()
    if lib is None:
        return None

    n_obs = len(obs_epoch)
    st_orders_list: List[int] = []
    st_s_list: List[float] = []
    n_st_arr = np.zeros(2, dtype=np.int32)
    rlen_arr = np.zeros(2, dtype=np.float64)
    bspd_arr = np.zeros(2, dtype=np.float64)
    spac_arr = np.zeros(2, dtype=np.float64)

    bm_valid_parts, bm_p10_parts, bm_p50_parts, bm_p90_parts, bm_mean_parts, bm_std_parts, bm_tier_parts = (
        [], [], [], [], [], [], []
    )
    inc_parts = []
    n_inc_arr = np.zeros(2, dtype=np.int32)

    for d_int in (0, 1):
        corr = list(corridors_by_dir.get(d_int, ()))
        n_st = len(corr)
        n_st_arr[d_int] = n_st
        rlen_arr[d_int] = float(route_len_by_dir.get(d_int, 0.0))
        bspd_arr[d_int] = float(route_base_speed_by_dir.get(d_int, 0.0))
        spac_arr[d_int] = float(route_spacing_by_dir.get(d_int, 0.0))
        if n_st > 0:
            st_orders_list.extend(int(st[0]) for st in corr)
            st_s_list.extend(float(st[3]) for st in corr)

        n_seg = max(0, n_st - 1)
        grid_n = 51 * n_seg
        bv = np.zeros(grid_n, dtype=np.uint8)
        bp10 = np.zeros(grid_n, dtype=np.float64)
        bp50 = np.zeros(grid_n, dtype=np.float64)
        bp90 = np.zeros(grid_n, dtype=np.float64)
        bmean = np.zeros(grid_n, dtype=np.float64)
        bstd = np.zeros(grid_n, dtype=np.float64)
        btier = np.zeros(grid_n, dtype=np.int32)
        if n_seg > 0:
            for day_type in (0, 1, 2):
                for hr in range(5, 22):
                    base = (day_type * 17 + (hr - 5)) * n_seg
                    for k in range(n_seg):
                        cell = baseline_lookup.get_baseline_cell(
                            route_id_for_lookup, d_int, int(corr[k][0]), int(corr[k + 1][0]), day_type, hr
                        )
                        if cell is not None:
                            idx = base + k
                            bv[idx] = 1
                            bp10[idx] = float(cell[0])
                            bp50[idx] = float(cell[1])
                            bp90[idx] = float(cell[2])
                            bmean[idx] = float(cell[3])
                            bstd[idx] = float(cell[4])
                            btier[idx] = int(cell[5])
        bm_valid_parts.append(bv)
        bm_p10_parts.append(bp10)
        bm_p50_parts.append(bp50)
        bm_p90_parts.append(bp90)
        bm_mean_parts.append(bmean)
        bm_std_parts.append(bstd)
        bm_tier_parts.append(btier)

        d_inc = list(incidents_by_dir.get(d_int, ()))
        n_inc_arr[d_int] = len(d_inc)
        inc_parts.extend(d_inc)

    if n_obs == 0 or route_id_idx < 0 or (n_st_arr[0] < 2 and n_st_arr[1] < 2):
        return {
            "features": np.zeros((0, 40), dtype=np.float32),
            "veh_idx": np.zeros(0, dtype=np.int32),
            "journey": np.zeros(0, dtype=np.int64),
            "target": np.zeros(0, dtype=np.int64),
            "split": np.zeros(0, dtype=np.int32),
            "as_of": np.zeros(0, dtype=np.float64),
            "eta_seconds": np.zeros(0, dtype=np.float64),
            "bracket_before": np.zeros(0, dtype=np.float64),
            "bracket_after": np.zeros(0, dtype=np.float64),
            "crossing_epoch": np.zeros(0, dtype=np.float64),
            "history_seconds": np.zeros(0, dtype=np.float64),
        }, {}

    st_orders = np.ascontiguousarray(st_orders_list, dtype=np.int64)
    st_s = np.ascontiguousarray(st_s_list, dtype=np.float64)
    bm_valid = np.ascontiguousarray(np.concatenate(bm_valid_parts), dtype=np.uint8)
    bm_p10 = np.ascontiguousarray(np.concatenate(bm_p10_parts), dtype=np.float64)
    bm_p50 = np.ascontiguousarray(np.concatenate(bm_p50_parts), dtype=np.float64)
    bm_p90 = np.ascontiguousarray(np.concatenate(bm_p90_parts), dtype=np.float64)
    bm_mean = np.ascontiguousarray(np.concatenate(bm_mean_parts), dtype=np.float64)
    bm_std = np.ascontiguousarray(np.concatenate(bm_std_parts), dtype=np.float64)
    bm_tier = np.ascontiguousarray(np.concatenate(bm_tier_parts), dtype=np.int32)

    if inc_parts:
        inc_arr = np.asarray(inc_parts, dtype=np.float64)
        inc_s_min = np.ascontiguousarray(inc_arr[:, 0], dtype=np.float64)
        inc_s_max = np.ascontiguousarray(inc_arr[:, 1], dtype=np.float64)
        inc_delay = np.ascontiguousarray(inc_arr[:, 2], dtype=np.float64)
        inc_crawled = np.ascontiguousarray(inc_arr[:, 3], dtype=np.float64)
        inc_expires = np.ascontiguousarray(inc_arr[:, 4], dtype=np.float64)
    else:
        empty_f64 = np.zeros(0, dtype=np.float64)
        inc_s_min = inc_s_max = inc_delay = inc_crawled = inc_expires = empty_f64

    ep_arr = np.ascontiguousarray(obs_epoch, dtype=np.float64)
    dr_arr = np.ascontiguousarray(obs_dir, dtype=np.int32)
    vh_arr = np.ascontiguousarray(obs_veh_idx, dtype=np.int32)
    sb_arr = np.ascontiguousarray(obs_s_bus, dtype=np.float64)

    out_rows_c = ctypes.c_int32(0)
    handle = lib.cpp_extract_route_causal_features(
        int(route_id_idx),
        rlen_arr, bspd_arr, spac_arr,
        n_st_arr, st_orders, st_s,
        bm_valid, bm_p10, bm_p50, bm_p90, bm_mean, bm_std, bm_tier,
        n_inc_arr, inc_s_min, inc_s_max, inc_delay, inc_crawled, inc_expires,
        int(n_vehicles), int(n_obs), ep_arr, dr_arr, vh_arr, sb_arr,
        float(baseline_cutoff_epoch), float(validation_epoch), float(test_epoch), float(cadence_sec),
        ctypes.byref(out_rows_c),
    )
    if not handle:
        raise RuntimeError("cpp_extract_route_causal_features returned NULL")

    try:
        err_c = ctypes.c_int64(0)
        cnt_arr = np.zeros(10, dtype=np.int64)
        lib.cpp_get_causal_feature_counts(handle, ctypes.byref(err_c), cnt_arr)
        if int(err_c.value) != 0:
            raise ValueError("Silver partition timestamps overlap baseline fitting or arrive out of order")

        n_rows = int(out_rows_c.value)
        features = np.empty((n_rows, 40), dtype=np.float32)
        veh_idx_out = np.empty(n_rows, dtype=np.int32)
        journey_out = np.empty(n_rows, dtype=np.int64)
        target_out = np.empty(n_rows, dtype=np.int64)
        split_out = np.empty(n_rows, dtype=np.int32)
        as_of_out = np.empty(n_rows, dtype=np.float64)
        eta_out = np.empty(n_rows, dtype=np.float64)
        bb_out = np.empty(n_rows, dtype=np.float64)
        ba_out = np.empty(n_rows, dtype=np.float64)
        cr_out = np.empty(n_rows, dtype=np.float64)
        hs_out = np.empty(n_rows, dtype=np.float64)

        if n_rows > 0:
            lib.cpp_copy_causal_features(
                handle,
                features.ravel(),
                veh_idx_out,
                journey_out,
                target_out,
                split_out,
                as_of_out,
                eta_out,
                bb_out,
                ba_out,
                cr_out,
                hs_out,
            )

        count_names = (
            "observations",
            "matched_observations",
            "forecast_attempts",
            "feature_rejected",
            "no_crossing",
            "invalid_eta",
            "label_crosses_split",
            "labeled_train",
            "labeled_validation",
            "labeled_test",
        )
        counts = {name: int(val) for name, val in zip(count_names, cnt_arr) if int(val) > 0}
        arrays = {
            "features": features,
            "veh_idx": veh_idx_out,
            "journey": journey_out,
            "target": target_out,
            "split": split_out,
            "as_of": as_of_out,
            "eta_seconds": eta_out,
            "bracket_before": bb_out,
            "bracket_after": ba_out,
            "crossing_epoch": cr_out,
            "history_seconds": hs_out,
        }
        return arrays, counts
    finally:
        lib.cpp_free_causal_features(handle)
