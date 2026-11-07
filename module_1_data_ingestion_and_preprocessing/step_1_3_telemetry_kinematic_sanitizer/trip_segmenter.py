"""
Trip Segmentation Module (Canonical Vertical Slice - v2.0 Continuity-Aware)
Implements Checklist 1, 2, and 3 from docs/03_SILVER_TRAJECTORY_CONTINUITY_AND_ETA_CHECKLIST.md:
- Bridges mid-trip detour/signal gaps (300s < dt <= 1800s) when the bus continues
  moving forward in the same direction at a valid macroscopic speed (2 - 60 km/h).
- Splits trips on direction flips, backward resets (ds < -200m), or long breaks (dt > 1800s).
- Trims stationary tail pings at destination terminals (where raw_dir stays frozen while parked).
"""

from typing import List, Tuple, Any, Optional

MAX_CONTINUOUS_GAP_SEC = 300.0
MAX_BRIDGEABLE_DETOUR_GAP_SEC = 1800.0
MAX_BACKWARD_JITTER_M = 50.0
MAX_BACKWARD_RESET_M = 200.0
MIN_PINGS_PER_TRIP = 5
MIN_TRIP_DISTANCE_M = 500.0


def trim_terminal_stationary_ends(
    trip: List[Tuple[Any, ...]],
    s_idx: int = 10,
    stationary_tol_m: float = 15.0,
) -> List[Tuple[Any, ...]]:
    """
    Checklist 2 & 3:
    - At trip end (destination terminal): Keep only up to the FIRST ping that reaches
      within `stationary_tol_m` of the trip's final position, removing parked tail pings.
    - At trip start (origin terminal): Keep from the LAST ping before the bus leaves
      its initial stationary staging spot (`s_start + stationary_tol_m`).
    """
    if len(trip) < 2:
        return trip

    s_vals = [float(p[s_idx]) for p in trip]
    s_first = s_vals[0]
    s_last = s_vals[-1]

    # Trim origin staging prefix: advance start_idx while subsequent pings remain at s_first
    start_idx = 0
    while start_idx + 1 < len(trip) and (s_vals[start_idx + 1] - s_first) <= stationary_tol_m:
        start_idx += 1

    # Trim destination parked suffix: pull back end_idx to the first ping reaching s_last
    end_idx = len(trip) - 1
    while end_idx > start_idx and (s_last - s_vals[end_idx - 1]) <= stationary_tol_m:
        end_idx -= 1

    return trip[start_idx : end_idx + 1]


def segment_trajectory_into_trips(
    pings: List[Tuple[Any, ...]],
    epoch_idx: int = 4,
    s_idx: int = 10,
    shape_len_m: Optional[float] = None,
    trim_terminals: bool = True,
) -> List[List[Tuple[Any, ...]]]:
    """
    Split a chronologically sorted sequence of projected pings for a single vehicle
    and single direction into valid monotonic forward transit trips.
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

        # Check if a 300s..1800s gap is a valid mid-trip detour/signal dropout bridge
        is_valid_detour_bridge = False
        if MAX_CONTINUOUS_GAP_SEC < dt <= MAX_BRIDGEABLE_DETOUR_GAP_SEC and ds > 100.0:
            avg_spd_kmh = (ds / dt) * 3.6
            if 2.0 <= avg_spd_kmh <= 60.0:
                is_valid_detour_bridge = True

        is_break = (
            (dt > MAX_CONTINUOUS_GAP_SEC and not is_valid_detour_bridge)
            or ds < -MAX_BACKWARD_JITTER_M
            or s < (max_s - MAX_BACKWARD_RESET_M)
            or is_terminal_reset
        )

        if is_break:
            final_trip = trim_terminal_stationary_ends(curr_trip, s_idx=s_idx) if trim_terminals else curr_trip
            if len(final_trip) >= MIN_PINGS_PER_TRIP:
                trip_span = float(final_trip[-1][s_idx]) - float(final_trip[0][s_idx])
                if trip_span >= MIN_TRIP_DISTANCE_M:
                    trips.append(final_trip)
            curr_trip = [p]
            max_s = s
        else:
            curr_trip.append(p)
            if s > max_s:
                max_s = s

    if curr_trip:
        final_trip = trim_terminal_stationary_ends(curr_trip, s_idx=s_idx) if trim_terminals else curr_trip
        if len(final_trip) >= MIN_PINGS_PER_TRIP:
            trip_span = float(final_trip[-1][s_idx]) - float(final_trip[0][s_idx])
            if trip_span >= MIN_TRIP_DISTANCE_M:
                trips.append(final_trip)

    return trips
