"""Storage-independent Frenet projection boundary defined by SPEC-26."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Mapping, Sequence

from config.system_config import (
    GPS_DRIFT_MAX_SPEED_KMPH,
    MAX_CORRIDOR_CROSS_TRACK_M,
    MAX_GPS_BACKWARD_JITTER_M,
    STALE_DELTA_T_MAX_SEC,
)

from .multi_route_projector import project_points_to_shape


VALID_DIRECTIONS = frozenset({"go", "re"})


@dataclass(frozen=True)
class ProjectableEvent:
    event_id: str
    legacy_ping_id: int | None
    route_id: int
    route_code: str
    vehicle_id: int
    plate: str | None
    device_update_time: str
    device_epoch_s: float
    direction_hint: str
    current_station_id: int | None
    lat: float
    lon: float


@dataclass(frozen=True)
class ProjectedEvent:
    event_id: str
    legacy_ping_id: int | None
    route_code: str
    route_id: int
    vehicle_id: int
    plate: str | None
    device_update_time: str
    device_epoch_s: float
    direction: str
    lat: float
    lon: float
    s_bus_m: float
    cross_track_m: float
    derived_speed_kmh: float | None


def project_route_events(
    events: Sequence[ProjectableEvent],
    shape_by_direction: Mapping[str, list[tuple[float, float, float, float]]],
    station_direction_lookup: Mapping[tuple[int, int], str],
) -> tuple[list[ProjectedEvent], dict[str, int]]:
    """Project a single route without I/O, preserving the legacy worker policy."""
    diagnostics: Counter[str] = Counter()
    if not events:
        return [], dict(diagnostics)

    route_ids = {event.route_id for event in events}
    route_codes = {event.route_code for event in events}
    if len(route_ids) != 1 or len(route_codes) != 1:
        raise ValueError("project_route_events accepts exactly one route_id and route_code")

    ordered = sorted(events, key=lambda event: (event.vehicle_id, event.device_epoch_s, event.event_id))
    by_vehicle: dict[int, list[tuple[ProjectableEvent, str]]] = defaultdict(list)
    timestamps: set[tuple[int, float]] = set()
    for event in ordered:
        timestamp_key = (event.vehicle_id, event.device_epoch_s)
        if timestamp_key in timestamps:
            diagnostics["duplicate_timestamp"] += 1
            continue
        timestamps.add(timestamp_key)
        station_key = (event.route_id, event.current_station_id) if event.current_station_id else None
        direction = station_direction_lookup.get(station_key) if station_key else None
        direction = direction or event.direction_hint
        if direction not in VALID_DIRECTIONS:
            diagnostics["unknown_direction"] += 1
            continue
        by_vehicle[event.vehicle_id].append((event, direction))

    accepted_geometry: dict[str, tuple[ProjectableEvent, str, float, float]] = {}
    for vehicle_events in by_vehicle.values():
        direction_runs: list[list[object]] = []
        for item in vehicle_events:
            if not direction_runs or item[1] != direction_runs[-1][0]:
                direction_runs.append([item[1], [item]])
            else:
                direction_runs[-1][1].append(item)  # type: ignore[union-attr]

        run_index = 1
        while run_index < len(direction_runs) - 1:
            previous_direction, previous_events = direction_runs[run_index - 1]
            current_direction, current_events = direction_runs[run_index]
            next_direction, next_events = direction_runs[run_index + 1]
            previous_items = previous_events  # type: ignore[assignment]
            current_items = current_events  # type: ignore[assignment]
            next_items = next_events  # type: ignore[assignment]
            span_seconds = next_items[0][0].device_epoch_s - previous_items[-1][0].device_epoch_s
            if previous_direction == next_direction and 0 < span_seconds <= STALE_DELTA_T_MAX_SEC:
                relabelled = [(event, previous_direction) for event, _ in current_items]
                previous_items.extend(relabelled)
                previous_items.extend(next_items)
                del direction_runs[run_index : run_index + 2]
            else:
                run_index += 1

        for direction, run_events in direction_runs:
            items = run_events  # type: ignore[assignment]
            shape = shape_by_direction.get(direction)
            if not shape:
                diagnostics["missing_shape"] += len(items)
                continue
            projection_input = [
                (event.event_id, event.lat, event.lon, event.device_epoch_s)
                for event, _ in items
            ]
            projected = {
                event_id: (s_bus_m, cross_track_m)
                for event_id, s_bus_m, cross_track_m in project_points_to_shape(projection_input, shape)
            }
            for event, _ in items:
                result = projected.get(event.event_id)
                if result is None or result[1] > MAX_CORRIDOR_CROSS_TRACK_M:
                    diagnostics["off_corridor_or_rejected_projection"] += 1
                    continue
                accepted_geometry[event.event_id] = (event, direction, result[0], result[1])

    output: list[ProjectedEvent] = []
    for vehicle_id in sorted(by_vehicle):
        vehicle_rows = sorted(
            (value for value in accepted_geometry.values() if value[0].vehicle_id == vehicle_id),
            key=lambda value: (value[0].device_epoch_s, value[0].event_id),
        )
        for index, (event, direction, s_bus_m, cross_track_m) in enumerate(vehicle_rows):
            derived_speed_kmh = None
            if index:
                previous_event, previous_direction, previous_s, _ = vehicle_rows[index - 1]
                delta_seconds = event.device_epoch_s - previous_event.device_epoch_s
                delta_s = round(s_bus_m - previous_s, 1)
                same_trip = (
                    0 < delta_seconds <= STALE_DELTA_T_MAX_SEC
                    and direction == previous_direction
                    and delta_s >= -MAX_GPS_BACKWARD_JITTER_M
                )
                if same_trip:
                    candidate_speed = round(max(0.0, delta_s) / delta_seconds * 3.6, 2)
                    if candidate_speed <= GPS_DRIFT_MAX_SPEED_KMPH:
                        derived_speed_kmh = candidate_speed
            output.append(
                ProjectedEvent(
                    event_id=event.event_id,
                    legacy_ping_id=event.legacy_ping_id,
                    route_code=event.route_code,
                    route_id=event.route_id,
                    vehicle_id=event.vehicle_id,
                    plate=event.plate,
                    device_update_time=event.device_update_time,
                    device_epoch_s=event.device_epoch_s,
                    direction=direction,
                    lat=event.lat,
                    lon=event.lon,
                    s_bus_m=s_bus_m,
                    cross_track_m=cross_track_m,
                    derived_speed_kmh=derived_speed_kmh,
                )
            )
    return output, dict(diagnostics)
