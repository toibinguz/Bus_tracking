"""Station filtering must not change route observations or bypass pass guards."""
from datetime import datetime, timezone
from types import SimpleNamespace
import threading

import numpy as np
import pytest

from experiments.timbus.timbus_tracker import TimBusClient
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.dto import BusVehicleDTO, RouteLiveResponse
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.projection_tracker import RouteProjectionTracker
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.serving_service import BusMapServingService
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.serving_service import MacroSpeedTracker

NOW = 1000.0


def vehicle(vid, distance):
    return BusVehicleDTO(
        id=vid, plate=f"29A0000{vid}", route_id=1, direction=0,
        lat=distance / 1000, lng=0, deg=0, speed_kmh=20,
        updated_at=datetime.fromtimestamp(NOW - 10, timezone.utc).isoformat(),
    )


class Shape:
    kx = 1000.0
    ky = 1000.0
    _x1 = np.array([0.0])
    _y1 = np.array([0.0])
    _dx = np.array([0.0])
    _dy = np.array([200.0])
    _safe_lens_sq = np.array([200.0 ** 2])
    _seg_lens = np.array([200.0])
    _cum_starts = np.array([0.0])
    _total_len = 200.0

    def project_point(self, lat, lng):
        return lat * 1000, abs(lng) * 1000, 0

    def segment_unit_tangent(self, index):
        return 0, 1


@pytest.fixture
def service(monkeypatch):
    # Exercise production merge/filter/extractor without a model, DB, or network.
    svc = BusMapServingService.__new__(BusMapServingService)
    svc._tb_lock = threading.Lock()
    svc._tb_last_valid = {}
    svc._passed_station_plates = {}
    svc._causal_lock = threading.Lock()
    svc._causal = SimpleNamespace(observe=lambda *a, **k: None, observe_snapshot=lambda *a, **k: None)
    svc._apply_macro_speeds = lambda *args: args[4]
    svc._da = SimpleNamespace(get_timbus_anchors=lambda *args: (True, [1]))
    svc._get_shape_model = lambda *args: Shape()
    # These tests isolate pass guards/merge, not route matching. Installed HMM
    # behavior is checked separately with real geometry and recorded GPS/HTTP.
    svc._prepare_vehicle = lambda route,direction,v,now:v.model_copy(update={
        'projection_checked':True,'matched_projection':Shape().project_point(v.lat,v.lng)})
    monkeypatch.setattr(TimBusClient, "query_central_vehicles", lambda **kwargs: {})
    return svc


def merge(service, bus, use_cache):
    return service._sync_and_merge_timbus(
        route_id=1, dir_int=0, dir_str="go", anchor_sids=[1],
        target_plates=[bus.plate], bm_proj={bus.plate: (bus, bus.lat * 1000, 0)},
        raw_vehicles=[bus], shape_model=Shape(), now_epoch=NOW,
        s_target=100, station_order=2, use_live_cache=use_cache,
    )


@pytest.mark.parametrize("use_cache", [False, True])
@pytest.mark.parametrize("age,distance,expected", [(2, 90, 0), (181, 90, 1), (2, -60, 1)])
def test_pass_guard_applies_equally_to_fresh_and_cached_telemetry(
    service, monkeypatch, use_cache, age, distance, expected
):
    bus = vehicle(1, distance)
    key = (1, 0, 2, bus.plate)
    service._passed_station_plates[key] = NOW - age
    service._tb_last_valid[(1, 0, bus.plate)] = (NOW - 1, distance, bus)
    record = SimpleNamespace(latitude=bus.lat, longitude=0, speed_kmh=20, fetch_timestamp=NOW)
    monkeypatch.setattr(TimBusClient, "query_central_vehicles", lambda **kwargs: {bus.plate: record})
    assert len(merge(service, bus, use_cache)) == expected
    assert (key in service._passed_station_plates) == (expected == 0)


def test_fresh_backward_fix_followed_by_cache_does_not_resurrect_bus(service, monkeypatch):
    bus = vehicle(1, 90)
    service._passed_station_plates[(1, 0, 2, bus.plate)] = NOW - 2
    record = SimpleNamespace(latitude=bus.lat, longitude=0, speed_kmh=20, fetch_timestamp=NOW)
    monkeypatch.setattr(TimBusClient, "query_central_vehicles", lambda **kwargs: {bus.plate: record})
    assert merge(service, bus, False) == []
    monkeypatch.setattr(TimBusClient, "query_central_vehicles", lambda **kwargs: pytest.fail("fresh cache must be used"))
    assert merge(service, bus, True) == []


@pytest.mark.parametrize("held_cache", [False, True])
def test_missing_timbus_does_not_resurrect_passed_bus_from_busmap(service, held_cache):
    bus = vehicle(1, 90)
    service._passed_station_plates[(1, 0, 2, bus.plate)] = NOW - 2
    if held_cache:
        service._tb_last_valid[(1, 0, bus.plate)] = (NOW - 5, 110, vehicle(1, 110))
    assert merge(service, bus, True) == []


def test_off_corridor_position_does_not_poison_pass_guard(service):
    bus = vehicle(1, 110).model_copy(update={"lng": 1})
    assert service._filter_station_vehicles(1, 0, [bus], Shape(), NOW, 100, 2) == []
    assert service._passed_station_plates == {}


@pytest.fixture
def extractor():
    extractor = RouteProjectionTracker.__new__(RouteProjectionTracker)
    extractor._match_lock = threading.RLock()
    extractor._shape_models = {(1, "go"): Shape()}
    extractor._matchers = {}
    extractor._matched = {}
    extractor._directions = {}
    extractor._generations = {}
    extractor._da = SimpleNamespace(
        get_corridor_stations=lambda *args: [(0, 0, 0, 0), (1, 0, 0, 200)],
        get_route_profile=lambda *args: (20, 200, 200),
        get_shape_points=lambda *args: [],
    )
    return extractor


def test_station_requests_preserve_full_fleet_and_leading_bus(service, extractor):
    service._extractor = extractor
    snapshots = []
    service._causal = SimpleNamespace(
        observe=lambda *a, **k: None,
        observe_snapshot=lambda r, d, t, vehicles, valid=True: snapshots.append(set(vehicles)),
    )
    buses = [vehicle(1, 90), vehicle(2, 110)]
    for bus in buses:
        service._tb_last_valid[(1, 0, bus.plate)] = (NOW, bus.lat * 1000, bus)
    response = RouteLiveResponse(
        route_id=1, direction=0, timestamp=buses[0].updated_at, count=2, vehicles=buses,
    )
    # Alternate map and different station requests against the same route state.
    for target, expected_ids in [(None, [1, 2]), (100, [1]), (120, [1, 2]), (80, [])]:
        _, approaching = service._sync_single_direction(
            1, 0, NOW, station_order=int(target) if target is not None else None,
            s_target=target, pre_live_resp=response,
        )
        assert [bus.id for bus in approaching] == expected_ids
        assert snapshots[-1] == {"29A00001", "29A00002"}


def test_cache_does_not_override_newer_busmap_position(service):
    cached = vehicle(1, 90)
    busmap = vehicle(1, 95).model_copy(update={
        "updated_at": datetime.fromtimestamp(NOW, timezone.utc).isoformat(),
    })
    service._tb_last_valid[(1, 0, cached.plate)] = (NOW - 1, 90, cached)
    assert merge(service, busmap, True)[0].lat == busmap.lat


def test_older_timbus_response_cannot_replace_newer_cache(service, monkeypatch):
    newest = vehicle(1, 95)
    service._tb_last_valid[(1, 0, newest.plate)] = (NOW, 95, newest)
    stale = SimpleNamespace(latitude=.03, longitude=0, speed_kmh=20, fetch_timestamp=NOW - 5)
    monkeypatch.setattr(TimBusClient, "query_central_vehicles", lambda **kwargs: {newest.plate: stale})
    assert merge(service, vehicle(1, 90), False)[0].lat == newest.lat
    assert service._tb_last_valid[(1, 0, newest.plate)][0] == NOW


def test_out_of_order_packet_does_not_reset_macro_history():
    tracker = MacroSpeedTracker()
    args = dict(route_id=1, dir_int=0, plate_norm="29A00001",
                raw_speed_kmh=20, bm_speed_kmh=20, route_base_spd_kmh=20)
    tracker.observe_and_estimate(**args, t_sample=1000, s_bus=100)
    previous = tracker.observe_and_estimate(**args, t_sample=1130, s_bus=800)
    history = list(tracker._history[(1, 0, "29A00001")])
    assert tracker.observe_and_estimate(**args, t_sample=1005, s_bus=125) == previous
    assert tracker._history[(1, 0, "29A00001")] == history


def test_out_of_order_packet_does_not_reset_ml_observations(extractor):
    first = vehicle(1, 90)
    latest = vehicle(1, 110).model_copy(update={
        "updated_at": datetime.fromtimestamp(NOW, timezone.utc).isoformat(),
    })
    extractor.update_observation(1, 0, [first], NOW)
    extractor.update_observation(1, 0, [latest], NOW)
    history = extractor.projection_history(1, 0, 1)
    assert sorted(history.values()) == [90, 110]
    stale = vehicle(1, 10).model_copy(update={
        "updated_at": datetime.fromtimestamp(NOW - 5, timezone.utc).isoformat(),
    })
    extractor.update_observation(1, 0, [stale], NOW + 1)
    assert extractor.projection_history(1, 0, 1) == history
    assert extractor._matched[(1, 0, 1)][2].matched_projection[0] == pytest.approx(110)
