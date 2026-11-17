"""Station filtering must not change route observations or bypass pass guards."""
from datetime import datetime, timezone
from types import SimpleNamespace
import threading

import pytest

from experiments.timbus.timbus_tracker import TimBusClient
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.dto import BusVehicleDTO, RouteLiveResponse
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.online_features import OnlineFeatureExtractor
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.serving_service import BusMapServingService

NOW = 1000.0


def vehicle(vid, distance):
    return BusVehicleDTO(
        id=vid, plate=f"29A0000{vid}", route_id=1, direction=0,
        lat=distance / 1000, lng=0, deg=0, speed_kmh=20,
        updated_at=datetime.fromtimestamp(NOW - 10, timezone.utc).isoformat(),
    )


class Shape:
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
    svc._apply_macro_speeds = lambda *args: args[4]
    svc._da = SimpleNamespace(get_timbus_anchors=lambda *args: (True, [1]))
    svc._get_shape_model = lambda *args: Shape()
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


def test_station_requests_preserve_full_fleet_and_leading_bus(service):
    extractor = OnlineFeatureExtractor.__new__(OnlineFeatureExtractor)
    extractor._obs_lock = threading.Lock()
    extractor._obs = {}
    extractor._fleet = {}
    extractor._da = SimpleNamespace(
        get_corridor_stations=lambda *args: [(0, 0, 0, 0), (1, 0, 0, 200)],
        get_route_profile=lambda *args: (20, 200, 200),
    )
    extractor._get_shape_model = lambda *args: Shape()
    extractor._segment_array = lambda *args, **kwargs: [36]
    service._extractor = extractor
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
        fleet = extractor._fleet[(1, 0)]
        assert set(fleet) == {1, 2}
        assert fleet[2][1] - fleet[1][1] == pytest.approx(20)
        assert set(extractor._obs) == {(1, 0, 1), (1, 0, 2)}
