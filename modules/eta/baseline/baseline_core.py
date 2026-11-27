"""Pure SSOT baseline travel-time extraction and 4-tier matrix aggregation.

Depends ONLY on stdlib + numpy + config.system_config + trip_segmenter + temporal_contract
so both local Pandas pipelines and PySpark executors share the exact same logic.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

import numpy as np

from config.system_config import (
    BASELINE_MAX_HOUR_SLOT,
    BASELINE_MIN_HOUR_SLOT,
    BASELINE_SAT_SUN_KERNEL_MIN_DIRECT,
    BASELINE_TIER0_MIN_SAMPLES,
    BASELINE_TIER0_MIN_SAMPLES_WEEKEND,
    BASELINE_TIER1_MIN_SAMPLES,
    BRACKET_MAX_DS_M,
    BRACKET_MAX_DT_SEC,
    BRACKET_SEG_LEN_FACTOR,
    DAY_TYPE_SATURDAY,
    DAY_TYPE_SUNDAY,
    DAY_TYPE_WEEKDAY,
    DEFAULT_URBAN_BUS_SPEED_KMPH,
    EXCLUDE_TERMINAL_BOUNDARY_STATIONS,
    SEGMENT_MAX_SPEED_KMPH,
    SEGMENT_MIN_SPEED_KMPH,
    TRAIN_SPLIT_END_DATE,
    TZ_HANOI,
)
from modules.ingestion.sanitizer.trip_segmenter import (
    segment_trajectory_into_trips,
)
from modules.eta.temporal_contract import split_at_dates

StationTuple = Tuple[int, int, str, float]
SampleTuple = Tuple[int, int, int, int, float, float]  # (ord_a, ord_b, day_type, hr_slot, tt, seg_dist)

GOLD_BASELINE_COLUMNS: Tuple[str, ...] = (
    "route_code",
    "direction",
    "from_station_order",
    "to_station_order",
    "from_station_id",
    "to_station_id",
    "from_station_name",
    "to_station_name",
    "segment_length_m",
    "day_type",
    "hour_slot",
    "sample_count",
    "quality_tier",
    "tt_p10_sec",
    "tt_p50_sec",
    "tt_p90_sec",
    "tt_mean_sec",
    "tt_std_sec",
)


def get_active_corridor_stations(st_list: Sequence[StationTuple]) -> List[StationTuple]:
    """TD-19: exclude origin/destination terminal boundary stations when enabled."""
    if EXCLUDE_TERMINAL_BOUNDARY_STATIONS and len(st_list) >= 4:
        return list(st_list[1:-1])
    return list(st_list)


def get_bus_terminal_or_corridor_status(
    s_bus_m: float, st_list: Sequence[StationTuple]
) -> str:
    """TD-19: classify same-direction bus into terminal or active-in-transit state."""
    if len(st_list) >= 4:
        if s_bus_m < st_list[1][3]:
            return "AT_ORIGIN_TERMINAL"
        if s_bus_m >= st_list[-2][3]:
            return "AT_DESTINATION_TERMINAL"
    return "ACTIVE_IN_TRANSIT"


def extract_bracketed_station_arrivals(
    trip: Sequence[Tuple[Any, ...]],
    stations: Sequence[StationTuple],
    epoch_idx: int = 1,
    s_idx: int = 2,
) -> Dict[int, float]:
    """Interpolate station arrivals strictly when tightly bracketed by consecutive pings."""
    if len(trip) < 2 or not stations:
        return {}

    epochs = np.array([float(p[epoch_idx]) for p in trip], dtype=np.float64)
    s_vals = np.array([float(p[s_idx]) for p in trip], dtype=np.float64)

    s_mono = np.maximum.accumulate(s_vals)
    s_start = s_mono[0]
    s_end = s_mono[-1]

    arrivals: Dict[int, float] = {}
    n_pings = len(trip)
    n_st = len(stations)
    p_idx = 0

    for k_st, (st_order, _, _, s_st) in enumerate(stations):
        if s_st < s_start or s_st > s_end:
            continue

        while p_idx + 1 < n_pings and s_mono[p_idx + 1] < s_st:
            p_idx += 1

        if p_idx + 1 >= n_pings:
            break

        s0 = s_mono[p_idx]
        s1 = s_mono[p_idx + 1]
        t0 = epochs[p_idx]
        t1 = epochs[p_idx + 1]
        dt = t1 - t0
        ds = s1 - s0

        prev_st_s = stations[k_st - 1][3] if k_st > 0 else s_st
        next_st_s = stations[k_st + 1][3] if k_st + 1 < n_st else s_st
        local_seg_len = max(s_st - prev_st_s, next_st_s - s_st)
        max_allowed_ds = max(BRACKET_MAX_DS_M, BRACKET_SEG_LEN_FACTOR * local_seg_len)

        if 0.0 < dt <= BRACKET_MAX_DT_SEC and 0.0 <= ds <= max_allowed_ds:
            if ds > 1e-3:
                ratio = (s_st - s0) / ds
                t_arr = t0 + ratio * dt
            else:
                t_arr = t0
            arrivals[st_order] = float(t_arr)

    return arrivals


def extract_fit_segment_samples(
    pings_tuples: Sequence[Tuple[Any, ...]],
    shape_len_m: float,
    full_st_list: Sequence[StationTuple],
    fit_end_date: str,
) -> List[SampleTuple]:
    """Segment one vehicle-direction timeline and extract valid fit segment samples."""
    st_list = get_active_corridor_stations(full_st_list)
    if len(st_list) < 2 or not pings_tuples:
        return []

    samples: List[SampleTuple] = []
    for window in split_at_dates(pings_tuples, [fit_end_date, TRAIN_SPLIT_END_DATE]):
        trips = segment_trajectory_into_trips(
            window, epoch_idx=1, s_idx=2, shape_len_m=shape_len_m, trim_terminals=True
        )
        for tr in trips:
            if tr[-1][0] > fit_end_date:
                continue
            arrivals = extract_bracketed_station_arrivals(tr, st_list, epoch_idx=1, s_idx=2)
            if len(arrivals) < 2:
                continue
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
                    day_type = (
                        DAY_TYPE_WEEKDAY
                        if wd < 5
                        else (DAY_TYPE_SATURDAY if wd == 5 else DAY_TYPE_SUNDAY)
                    )
                    hr_slot = min(BASELINE_MAX_HOUR_SLOT, max(BASELINE_MIN_HOUR_SLOT, dt_obj.hour))
                    samples.append((ord_a, ord_b, day_type, hr_slot, float(tt), float(seg_dist)))
    return samples


def build_route_baseline_rows(
    route_code: str,
    stations_by_dir: Mapping[str, Sequence[StationTuple]],
    samples_by_dir: Mapping[str, Iterable[SampleTuple]],
) -> Tuple[List[Tuple[Any, ...]], Dict[int, int]]:
    """Aggregate extracted segment samples into the 4-tier Gold baseline matrix for one route."""
    rows: List[Tuple[Any, ...]] = []
    tier_counts: Dict[int, int] = {0: 0, 1: 0, 2: 0, 3: 0}

    for d_str in ("go", "re"):
        st_list = get_active_corridor_stations(stations_by_dir.get(d_str, ()))
        if len(st_list) < 2:
            continue

        slot_samples: Dict[Tuple[int, int, int, int], List[float]] = defaultdict(list)
        daytype_samples: Dict[Tuple[int, int, int], List[float]] = defaultdict(list)
        seg_all_samples: Dict[Tuple[int, int], List[float]] = defaultdict(list)
        tot_d = 0.0
        tot_t = 0.0

        for ord_a, ord_b, day_type, hr_slot, tt, seg_dist in samples_by_dir.get(d_str, ()):
            slot_samples[(ord_a, ord_b, day_type, hr_slot)].append(tt)
            daytype_samples[(ord_a, ord_b, day_type)].append(tt)
            seg_all_samples[(ord_a, ord_b)].append(tt)
            tot_d += seg_dist
            tot_t += tt

        route_avg_mps = (tot_d / tot_t) if tot_t > 0 else (DEFAULT_URBAN_BUS_SPEED_KMPH / 3.6)

        for k in range(len(st_list) - 1):
            ord_a, id_a, name_a, s_a = st_list[k]
            ord_b, id_b, name_b, s_b = st_list[k + 1]
            seg_dist = round(max(15.0, s_b - s_a), 1)

            for day_type in (DAY_TYPE_WEEKDAY, DAY_TYPE_SATURDAY, DAY_TYPE_SUNDAY):
                tier0_thresh = (
                    BASELINE_TIER0_MIN_SAMPLES
                    if day_type == DAY_TYPE_WEEKDAY
                    else BASELINE_TIER0_MIN_SAMPLES_WEEKEND
                )
                for hr_slot in range(BASELINE_MIN_HOUR_SLOT, BASELINE_MAX_HOUR_SLOT + 1):
                    direct_vals = slot_samples.get((ord_a, ord_b, day_type, hr_slot), [])
                    n_direct = len(direct_vals)

                    if day_type in (DAY_TYPE_SATURDAY, DAY_TYPE_SUNDAY) and n_direct < BASELINE_SAT_SUN_KERNEL_MIN_DIRECT:
                        eff_vals: List[float] = []
                        for h_adj in (hr_slot - 1, hr_slot, hr_slot + 1):
                            eff_vals.extend(slot_samples.get((ord_a, ord_b, day_type, h_adj), []))
                    else:
                        eff_vals = direct_vals

                    n_eff = len(eff_vals)

                    if n_eff >= tier0_thresh:
                        q_tier = 0
                        used_vals = eff_vals
                    elif n_eff >= BASELINE_TIER1_MIN_SAMPLES:
                        q_tier = 1
                        used_vals = eff_vals
                    else:
                        neighbor_vals: List[float] = []
                        for h_adj in (hr_slot - 1, hr_slot, hr_slot + 1):
                            neighbor_vals.extend(slot_samples.get((ord_a, ord_b, day_type, h_adj), []))
                        if len(neighbor_vals) >= BASELINE_TIER1_MIN_SAMPLES:
                            q_tier = 2
                            used_vals = neighbor_vals
                        elif len(daytype_samples.get((ord_a, ord_b, day_type), [])) >= BASELINE_TIER1_MIN_SAMPLES:
                            q_tier = 2
                            used_vals = daytype_samples[(ord_a, ord_b, day_type)]
                        elif len(seg_all_samples.get((ord_a, ord_b), [])) >= 1:
                            q_tier = 2
                            used_vals = seg_all_samples[(ord_a, ord_b)]
                        else:
                            q_tier = 3
                            used_vals = []

                    tier_counts[q_tier] += 1

                    if used_vals:
                        arr = np.array(used_vals, dtype=np.float64)
                        p10 = float(np.percentile(arr, 10))
                        p50 = float(np.percentile(arr, 50))
                        p90 = float(np.percentile(arr, 90))
                        mean_v = float(np.mean(arr))
                        std_v = float(np.std(arr)) if len(arr) > 1 else round(0.15 * mean_v, 2)
                    else:
                        p50 = seg_dist / max(1.0, route_avg_mps)
                        p10 = p50 * 0.75
                        p90 = p50 * 1.35
                        mean_v = p50
                        std_v = p50 * 0.20

                    rows.append(
                        (
                            route_code,
                            d_str,
                            ord_a,
                            ord_b,
                            id_a,
                            id_b,
                            name_a,
                            name_b,
                            seg_dist,
                            day_type,
                            hr_slot,
                            n_eff,
                            q_tier,
                            round(p10, 2),
                            round(p50, 2),
                            round(p90, 2),
                            round(mean_v, 2),
                            round(std_v, 2),
                        )
                    )

    return rows, tier_counts
