from module_1_data_ingestion_and_preprocessing.step_1_4_frenet_spatial_projection.projection_boundary import (
    ProjectableEvent,
    project_route_events,
)


ROUTE_ID = 1
ROUTE_CODE = "01"
SHAPES = {
    "go": [(1, 21.0, 105.0, 0.0), (2, 21.0, 105.01, 1040.0)],
    "re": [(1, 21.0, 105.01, 0.0), (2, 21.0, 105.0, 1040.0)],
}


def event(event_id, epoch, lon, direction="go", station_id=None, lat=21.0):
    return ProjectableEvent(
        event_id=event_id,
        legacy_ping_id=None,
        route_id=ROUTE_ID,
        route_code=ROUTE_CODE,
        vehicle_id=100,
        plate="fixture",
        device_update_time=f"fixture-{epoch}",
        device_epoch_s=epoch,
        direction_hint=direction,
        current_station_id=station_id,
        lat=lat,
        lon=lon,
    )


def test_f1_normal_forward_run_has_increasing_position_and_speed():
    output, diagnostics = project_route_events(
        [event("a", 0, 105.001), event("b", 20, 105.002)], SHAPES, {}
    )
    assert diagnostics == {}
    assert [row.event_id for row in output] == ["a", "b"]
    assert output[0].s_bus_m < output[1].s_bus_m
    assert output[1].derived_speed_kmh is not None


def test_f2_station_override_wins_over_direction_hint():
    output, _ = project_route_events(
        [event("override", 0, 105.009, direction="go", station_id=77)],
        SHAPES,
        {(ROUTE_ID, 77): "re"},
    )
    assert output[0].direction == "re"


def test_f3_short_bracketed_direction_glitch_is_relabelled():
    output, _ = project_route_events(
        [
            event("first", 0, 105.001, "go"),
            event("glitch", 10, 105.002, "re"),
            event("last", 20, 105.003, "go"),
        ],
        SHAPES,
        {},
    )
    assert [row.direction for row in output] == ["go", "go", "go"]


def test_f4_off_corridor_event_is_excluded():
    output, diagnostics = project_route_events([event("off", 0, 105.001, lat=22.0)], SHAPES, {})
    assert output == []
    assert diagnostics["off_corridor_or_rejected_projection"] == 1


def test_f5_long_gap_does_not_generate_continuity_speed():
    output, _ = project_route_events(
        [event("first", 0, 105.001), event("late", 1000, 105.002)], SHAPES, {}
    )
    assert output[1].derived_speed_kmh is None


def test_duplicate_vehicle_timestamp_is_quarantined_deterministically():
    output, diagnostics = project_route_events(
        [event("a", 0, 105.001), event("b", 0, 105.002)], SHAPES, {}
    )
    assert [row.event_id for row in output] == ["a"]
    assert diagnostics["duplicate_timestamp"] == 1
