"""Benchmark C++17 RouteHMM (g++ -O3) vs Python RouteHMM (bbox prefilter) on real Hanoi bus pings."""

from __future__ import annotations

import ctypes
import os
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from config.system_config import (
    BATCH_HMM_HORIZON_SEC,
    DEFAULT_DB_PATH,
    FRENET_MAX_SPEED_MPS,
    MAX_CORRIDOR_CROSS_TRACK_M,
    MAX_GPS_BACKWARD_JITTER_M,
    METERS_PER_DEG_LAT,
    METERS_PER_DEG_LON_EQUATOR,
    STALE_DELTA_T_MAX_SEC,
    TERMINAL_RESET_ZONE_M,
)
from module_1_data_ingestion_and_preprocessing.step_1_4_frenet_spatial_projection.route_matcher import (
    RouteHMM,
    ShapeProjectionModel,
)


def main() -> None:
    if hasattr(os, "add_dll_directory") and os.path.isdir(r"C:\msys64\ucrt64\bin"):
        os.add_dll_directory(r"C:\msys64\ucrt64\bin")
    dll_path = Path(__file__).resolve().parent / "route_hmm_fast.dll"
    lib = ctypes.CDLL(str(dll_path))

    lib.cpp_create_shape.argtypes = [
        ctypes.c_int,
        np.ctypeslib.ndpointer(dtype=np.float64, flags="C_CONTIGUOUS"),
        np.ctypeslib.ndpointer(dtype=np.float64, flags="C_CONTIGUOUS"),
        np.ctypeslib.ndpointer(dtype=np.float64, flags="C_CONTIGUOUS"),
        ctypes.c_double,
        ctypes.c_double,
    ]
    lib.cpp_create_shape.restype = ctypes.c_void_p
    lib.cpp_free_shape.argtypes = [ctypes.c_void_p]
    lib.cpp_free_shape.restype = None
    lib.cpp_project_runs.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        np.ctypeslib.ndpointer(dtype=np.int64, flags="C_CONTIGUOUS"),
        np.ctypeslib.ndpointer(dtype=np.float64, flags="C_CONTIGUOUS"),
        np.ctypeslib.ndpointer(dtype=np.float64, flags="C_CONTIGUOUS"),
        np.ctypeslib.ndpointer(dtype=np.float64, flags="C_CONTIGUOUS"),
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_double,
        np.ctypeslib.ndpointer(dtype=np.int32, flags="C_CONTIGUOUS"),
        np.ctypeslib.ndpointer(dtype=np.float64, flags="C_CONTIGUOUS"),
        np.ctypeslib.ndpointer(dtype=np.float64, flags="C_CONTIGUOUS"),
    ]
    lib.cpp_project_runs.restype = None

    db_path = ROOT / DEFAULT_DB_PATH
    with sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True) as conn:
        route_row = conn.execute(
            "SELECT route_id FROM canonical_route_master WHERE route_code = '01'"
        ).fetchone()
        route_id = int(route_row[0])
        shape_pts = conn.execute(
            """
            SELECT point_order, lat, lon, cum_distance_m
            FROM canonical_shape_master
            WHERE route_id = ? AND direction = 'go'
            ORDER BY point_order
            """,
            (route_id,),
        ).fetchall()
        raw_pings = conn.execute(
            """
            SELECT vehicle_id, device_epoch, lat, lon
            FROM vehicle_unique_pings
            WHERE route_id = ? AND direction = 0 AND lat BETWEEN 20.5 AND 21.5 AND lon BETWEEN 105.0 AND 106.5
            ORDER BY vehicle_id, device_epoch
            LIMIT 100000
            """,
            (route_id,),
        ).fetchall()

    n_pings = len(raw_pings)
    if n_pings == 0:
        raise RuntimeError("No pings found for Route 01 direction=0 benchmark")

    # Group into monotonic-per-vehicle runs
    runs: list[list[tuple[float, float, float]]] = []
    cur_vid = None
    for vid, ep, lat, lon in raw_pings:
        if vid != cur_vid:
            runs.append([])
            cur_vid = vid
        runs[-1].append((float(ep), float(lat), float(lon)))

    # Flat contiguous arrays for C++
    epochs_arr = np.array([p[1] for p in raw_pings], dtype=np.float64)
    lats_arr = np.array([p[2] for p in raw_pings], dtype=np.float64)
    lons_arr = np.array([p[3] for p in raw_pings], dtype=np.float64)
    offsets = [0]
    for r in runs:
        offsets.append(offsets[-1] + len(r))
    offsets_arr = np.array(offsets, dtype=np.int64)

    s_lats = np.array([float(p[1]) for p in shape_pts], dtype=np.float64)
    s_lons = np.array([float(p[2]) for p in shape_pts], dtype=np.float64)
    s_cums = np.array([float(p[3]) for p in shape_pts], dtype=np.float64)

    # 1. Python benchmark (excluding SQLite I/O)
    py_model = ShapeProjectionModel.build(shape_pts)
    py_matched = np.zeros(n_pings, dtype=np.int32)
    py_s = np.zeros(n_pings, dtype=np.float64)
    py_ct = np.zeros(n_pings, dtype=np.float64)

    t0 = time.perf_counter()
    pos = 0
    for r in runs:
        hmm = RouteHMM(py_model, horizon=BATCH_HMM_HORIZON_SEC)
        prev_ep = None
        for idx, (ep, lat, lon) in enumerate(r):
            if prev_ep is not None and ep <= prev_ep:
                pos += 1
                continue
            prev_ep = ep
            m = hmm.update(ep, lat, lon, idx)
            if m is not None:
                py_matched[pos] = 1
                py_s[pos] = m.s
                py_ct[pos] = m.cross_track
            pos += 1
    py_elapsed = time.perf_counter() - t0

    # 2. C++17 benchmark (warm + timed)
    cpp_shape = lib.cpp_create_shape(
        len(shape_pts),
        s_lats,
        s_lons,
        s_cums,
        METERS_PER_DEG_LAT,
        METERS_PER_DEG_LON_EQUATOR,
    )
    cpp_matched = np.zeros(n_pings, dtype=np.int32)
    cpp_s = np.zeros(n_pings, dtype=np.float64)
    cpp_ct = np.zeros(n_pings, dtype=np.float64)
    try:
        t1 = time.perf_counter()
        lib.cpp_project_runs(
            cpp_shape,
            len(runs),
            offsets_arr,
            epochs_arr,
            lats_arr,
            lons_arr,
            MAX_CORRIDOR_CROSS_TRACK_M,
            MAX_GPS_BACKWARD_JITTER_M,
            FRENET_MAX_SPEED_MPS,
            TERMINAL_RESET_ZONE_M,
            STALE_DELTA_T_MAX_SEC,
            BATCH_HMM_HORIZON_SEC,
            cpp_matched,
            cpp_s,
            cpp_ct,
        )
        cpp_elapsed = time.perf_counter() - t1
    finally:
        lib.cpp_free_shape(cpp_shape)

    both = (py_matched == 1) & (cpp_matched == 1)
    exact_mask_rate = float((py_matched == cpp_matched).mean() * 100.0)
    max_ds = float(np.max(np.abs(py_s[both] - cpp_s[both]))) if np.any(both) else 0.0
    max_dct = float(np.max(np.abs(py_ct[both] - cpp_ct[both]))) if np.any(both) else 0.0
    exact_vals = int(np.sum((py_s[both] == cpp_s[both]) & (py_ct[both] == cpp_ct[both])))
    total_both = int(np.sum(both))

    print(f"Dataset: Route 01 (go), pings={n_pings:,}, vehicles/runs={len(runs)}, shape_pts={len(shape_pts)}")
    print(f"Python RouteHMM (bbox): {py_elapsed:.4f}s ({n_pings / py_elapsed:,.0f} pings/s)")
    print(f"C++17  RouteHMM (-O3) : {cpp_elapsed:.4f}s ({n_pings / cpp_elapsed:,.0f} pings/s)")
    print(f"Speedup (C++ vs Py)   : {py_elapsed / cpp_elapsed:.2f}x")
    print(
        f"Parity: matched_py={int(py_matched.sum()):,}, matched_cpp={int(cpp_matched.sum()):,}, "
        f"mask_agree={exact_mask_rate:.4f}%, exact_s_ct={exact_vals:,}/{total_both:,}, "
        f"max|ds|={max_ds:.4f}m, max|dct|={max_dct:.4f}m"
    )


if __name__ == "__main__":
    main()
