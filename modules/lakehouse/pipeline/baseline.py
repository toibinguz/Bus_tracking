"""Pure Python + NumPy PySpark helpers for HDFS Silver -> Gold Baseline."""

from __future__ import annotations

from collections import defaultdict
from itertools import groupby
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

import numpy as np

from config.system_config import TRAIN_SPLIT_END_DATE
from core_cpp.native_bridge import (
    build_route_baseline_native,
    is_native_available,
)
from modules.eta.baseline.baseline_core import (
    GOLD_BASELINE_COLUMNS,
    SampleTuple,
    StationTuple,
    build_route_baseline_rows,
    extract_fit_segment_samples,
)

__all__ = [
    "GOLD_BASELINE_COLUMNS",
    "aggregate_route_baseline",
    "build_reference_lookup",
    "compute_route_baseline",
    "extract_partition_samples",
]


def build_reference_lookup(
    reference: Mapping[str, Any],
) -> Tuple[Dict[Tuple[str, str], float], Dict[Tuple[str, str], List[StationTuple]]]:
    """Build (shape_len_map, stations_map) keyed by (route_code, direction) from reference.json."""
    routes: Dict[str, str] = {str(k): str(v) for k, v in reference["routes"].items()}
    shape_len_map: Dict[Tuple[str, str], float] = {}
    for route_id_str, dirs in reference["shapes"].items():
        r_code = routes.get(str(route_id_str))
        if not r_code:
            continue
        for direction, points in dirs.items():
            shape_len_map[(r_code, str(direction))] = max(
                (float(pt[3]) for pt in points), default=0.0
            )

    raw_stations: Dict[Tuple[str, str], List[StationTuple]] = defaultdict(list)
    for st in reference["stations"]:
        r_code = str(st.get("route_code") or routes.get(str(st["route_id"]), ""))
        if not r_code:
            continue
        raw_stations[(r_code, str(st["direction"]))].append(
            (
                int(st["station_order"]),
                int(st["station_id"]),
                str(st["station_name"]),
                float(st["cum_distance_m"]),
            )
        )
    stations_map = {
        key: sorted(items, key=lambda item: item[0])
        for key, items in raw_stations.items()
    }
    return shape_len_map, stations_map


def extract_partition_samples(
    sorted_rows: Iterable[Tuple[Tuple[str, str, int, float], Mapping[str, Any]]],
    shape_len_map: Mapping[Tuple[str, str], float],
    stations_map: Mapping[Tuple[str, str], List[StationTuple]],
    fit_end_date: str,
) -> Iterable[Tuple[str, Tuple[Any, ...]]]:
    """Run SSOT trip segmentation & bracketed crossing on sorted (route_code, direction, vehicle_id) groups."""
    for (route_code, direction, _vehicle_id), group in groupby(
        sorted_rows, key=lambda pair: pair[0][:3]
    ):
        full_st_list = stations_map.get((route_code, direction), [])
        if not full_st_list:
            continue
        shape_len_m = float(shape_len_map.get((route_code, direction), 0.0))
        pings_tuples = [
            (
                str(row["dt"]),
                float(row["device_epoch_s"]),
                float(row["s_bus_m"]),
                row.get("derived_speed_kmh"),
            )
            for _, row in group
        ]
        samples = extract_fit_segment_samples(
            pings_tuples, shape_len_m, full_st_list, fit_end_date
        )
        for ord_a, ord_b, day_type, hr_slot, tt, seg_dist in samples:
            yield (
                route_code,
                (direction, ord_a, ord_b, day_type, hr_slot, tt, seg_dist),
            )


def aggregate_route_baseline(
    route_code: str,
    sample_iter: Iterable[Optional[Tuple[Any, ...]]],
    stations_map: Mapping[Tuple[str, str], List[StationTuple]],
) -> List[Tuple[Any, ...]]:
    """Group executor samples by direction and emit 4-tier Gold baseline matrix rows."""
    samples_by_dir: Dict[str, List[SampleTuple]] = defaultdict(list)
    for item in sample_iter:
        if item is None:
            continue
        d_str, ord_a, ord_b, day_type, hr_slot, tt, seg_dist = item
        samples_by_dir[str(d_str)].append(
            (int(ord_a), int(ord_b), int(day_type), int(hr_slot), float(tt), float(seg_dist))
        )
    stations_by_dir = {
        d_str: stations_map.get((route_code, d_str), [])
        for d_str in ("go", "re")
    }
    rows, _ = build_route_baseline_rows(route_code, stations_by_dir, samples_by_dir)
    return rows


def compute_route_baseline(
    route_code: str,
    rows_iter: Iterable[Tuple[int, str, float, float, str]],
    shape_len_map: Mapping[Tuple[str, str], float],
    stations_map: Mapping[Tuple[str, str], List[StationTuple]],
    fit_end_date: str,
    record_engine=None,
) -> List[Tuple[Any, ...]]:
    """Compute Gold baseline rows for 1 route using C++17 native kernel with Python SSOT fallback."""
    raw_rows = sorted(rows_iter, key=lambda r: (r[0], r[1], r[2], r[3]))
    st_go = stations_map.get((route_code, "go"), [])
    st_re = stations_map.get((route_code, "re"), [])
    if is_native_available() and raw_rows:
        v_ids = np.array([r[0] for r in raw_rows], dtype=np.int32)
        d_ints = np.array([0 if r[1] == "go" else 1 for r in raw_rows], dtype=np.int32)
        epochs = np.array([r[2] for r in raw_rows], dtype=np.float64)
        s_vals = np.array([r[3] for r in raw_rows], dtype=np.float64)
        cells = build_route_baseline_native(
            float(shape_len_map.get((route_code, "go"), 0.0)),
            st_go,
            float(shape_len_map.get((route_code, "re"), 0.0)),
            st_re,
            v_ids,
            d_ints,
            epochs,
            s_vals,
            fit_end_date=fit_end_date,
            train_end_date=TRAIN_SPLIT_END_DATE,
        )
        if cells is not None:
            if record_engine:
                record_engine("cpp_native")
            return [
                (
                    route_code,
                    c["direction"],
                    c["from_station_order"],
                    c["to_station_order"],
                    c["from_station_id"],
                    c["to_station_id"],
                    c["from_station_name"],
                    c["to_station_name"],
                    c["segment_length_m"],
                    c["day_type"],
                    c["hour_slot"],
                    c["sample_count"],
                    c["quality_tier"],
                    c["tt_p10_sec"],
                    c["tt_p50_sec"],
                    c["tt_p90_sec"],
                    c["tt_mean_sec"],
                    c["tt_std_sec"],
                )
                for c in cells
            ]

    if record_engine:
        record_engine("python")
    samples_by_dir: Dict[str, List[SampleTuple]] = defaultdict(list)
    by_vd: Dict[Tuple[int, str], List[Tuple[str, float, float, None]]] = defaultdict(list)
    for vid, d_str, ep, s_m, dt_str in raw_rows:
        by_vd[(int(vid), str(d_str))].append((str(dt_str), float(ep), float(s_m), None))
    for (_vid, d_str), pings in by_vd.items():
        pings.sort(key=lambda p: p[1])
        full_st = stations_map.get((route_code, d_str), [])
        if not full_st:
            continue
        samples_by_dir[d_str].extend(
            extract_fit_segment_samples(
                pings, float(shape_len_map.get((route_code, d_str), 0.0)), full_st, fit_end_date
            )
        )
    rows, _ = build_route_baseline_rows(
        route_code, {"go": st_go, "re": st_re}, samples_by_dir
    )
    return rows
