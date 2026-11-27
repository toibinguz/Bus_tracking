"""C++17 native bridge for high-speed Batch Spatial Projection & Baseline Matrix."""

from __future__ import annotations

import ctypes
import os
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from config.system_config import TRAIN_SPLIT_END_DATE

_DLL_PATH = Path(__file__).resolve().parent / "bus_native_core.dll"
_LIB: Optional[ctypes.CDLL] = None
_LOAD_TRIED = False


def _load_native_lib() -> Optional[ctypes.CDLL]:
    global _LIB, _LOAD_TRIED
    if _LOAD_TRIED:
        return _LIB
    _LOAD_TRIED = True
    if not _DLL_PATH.is_file():
        return None
    try:
        if hasattr(os, "add_dll_directory") and os.path.isdir(r"C:\msys64\ucrt64\bin"):
            os.add_dll_directory(r"C:\msys64\ucrt64\bin")
        lib = ctypes.CDLL(str(_DLL_PATH))

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
        _LIB = lib
    except Exception:
        _LIB = None
    return _LIB


def is_native_available() -> bool:
    """Return True if the compiled C++17 native kernel DLL loads cleanly."""
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
    """Project raw SQLite pings of 1 route using C++17 RouteHMM; returns None if DLL unavailable."""
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

    route_st = [(int(sid), 0 if str(d).lower() == "go" else 1) for (rid, sid), d in st_dir.items() if rid == route_id and str(d).lower() in ("go", "re")]
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
        # (ping_id, vehicle_id, plate, device_update_time, device_epoch, direction, lat, lon, current_station_id)
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
                row[0],       # ping_id
                route_code,   # route_code
                route_id,     # route_id
                row[1],       # vehicle_id
                row[2],       # plate
                row[3],       # device_update_time
                row[4],       # device_epoch
                d_str,        # direction
                row[6],       # lat
                row[7],       # lon
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
    """Compute segment baseline cells for 1 route in C++17; returns None if DLL unavailable."""
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
