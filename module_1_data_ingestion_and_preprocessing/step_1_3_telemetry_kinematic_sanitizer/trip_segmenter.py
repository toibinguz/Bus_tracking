"""
Trip Segmentation Module (Canonical Vertical Slice)
Unified trajectory segmentation engine used consistently across:
- Step 1.4: Frenet Spatial Projection & Kinematic Derivation
- Step 3.1: Historical Baseline Matrix Calculation
- Step 3.2: Gold Feature Store Extraction

Enforces single source of truth for trip boundaries:
- MAX_TRIP_GAP_SEC = 300.0 (5 minutes telemetry blackout triggers new trip)
- MAX_BACKWARD_JUMP_M = 50.0 (backward jump > 50m indicates new trip or reversal)
- MIN_PINGS_PER_TRIP = 5 (trips with fewer than 5 pings are discarded as noise)
- MIN_TRIP_DISTANCE_M = 500.0 (minimum cumulative trip span)
"""

from typing import List, Tuple, Dict, Any, Optional

MAX_TRIP_GAP_SEC = 300.0
MAX_BACKWARD_JUMP_M = 50.0
MIN_PINGS_PER_TRIP = 5
MIN_TRIP_DISTANCE_M = 500.0


def segment_trajectory_into_trips(
    pings: List[Tuple[Any, ...]],
    epoch_idx: int = 4,
    s_idx: int = 10,
    shape_len_m: Optional[float] = None
) -> List[List[Tuple[Any, ...]]]:
    """
    Split a chronologically sorted sequence of projected pings for a single vehicle
    into valid monotonic forward transit trips.

    Args:
        pings: List of ping tuples sorted by epoch.
        epoch_idx: Index of device_epoch in tuple.
        s_idx: Index of s_bus_m in tuple.
        shape_len_m: Optional total length of route shape. If provided, allows
                     detecting terminal turnaround resets (s near L -> s near 0).

    Returns:
        List of trips, each trip is a List of ping tuples.
    """
    if not pings:
        return []

    trips: List[List[Tuple[Any, ...]]] = []
    curr_trip: List[Tuple[Any, ...]] = []
    max_s = -1.0

    for p in pings:
        epoch = float(p[epoch_idx])
        s = float(p[s_idx])

        if not curr_trip:
            curr_trip.append(p)
            max_s = s
            continue

        prev_epoch = float(curr_trip[-1][epoch_idx])
        prev_s = float(curr_trip[-1][s_idx])
        dt = epoch - prev_epoch
        ds = s - prev_s

        # Terminal turnaround detection
        is_terminal_reset = False
        if shape_len_m and shape_len_m > 1000.0:
            if prev_s >= (shape_len_m - 800.0) and s <= 800.0:
                is_terminal_reset = True

        # Trip break conditions
        is_break = (
            dt > MAX_TRIP_GAP_SEC or
            ds < -MAX_BACKWARD_JUMP_M or
            s < (max_s - 300.0) or
            is_terminal_reset
        )

        if is_break:
            if len(curr_trip) >= MIN_PINGS_PER_TRIP:
                trip_span = max_s - float(curr_trip[0][s_idx])
                if trip_span >= MIN_TRIP_DISTANCE_M:
                    trips.append(curr_trip)
            curr_trip = [p]
            max_s = s
        else:
            curr_trip.append(p)
            if s > max_s:
                max_s = s

    if len(curr_trip) >= MIN_PINGS_PER_TRIP:
        trip_span = max_s - float(curr_trip[0][s_idx])
        if trip_span >= MIN_TRIP_DISTANCE_M:
            trips.append(curr_trip)

    return trips

