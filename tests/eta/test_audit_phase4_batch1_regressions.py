"""Regression tests for Phase 4 Batch 1-3 surgical fixes (AUD-P0 & AUD-P1)."""

from datetime import datetime
from types import SimpleNamespace
import threading

import numpy as np
import pytest
from fastapi import HTTPException

from config.system_config import TZ_HANOI
from modules.eta.serving.timbus_client import BusRecord, TimBusClient
from modules.ingestion.sanitizer.telemetry_sanitizer import (
    sanitize_and_validate_telemetry,
)
from modules.eta.serving.dto import (
    BusVehicleDTO,
    RouteStationsResponse,
    StationItemDTO,
)
from modules.eta.serving.eta_policy import (
    BusState,
    compute_station_eta,
    project_filter_extrapolate,
)
from modules.eta.serving.model_runtime import ModelRuntime
from modules.eta.serving.serving_service import (
    BusMapServingService,
    MacroSpeedTracker,
)
from modules.eta.serving.speed_poller import (
    SpeedLayerPoller,
)
from modules.eta.web_demo import app as web_app


class _FakeShape:
    kx = 1000.0
    ky = 1000.0
    _x1 = np.array([0.0])
    _y1 = np.array([0.0])
    _dx = np.array([0.0])
    _dy = np.array([1000.0])
    _safe_lens_sq = np.array([1000.0 ** 2])
    _seg_lens = np.array([1000.0])
    _cum_starts = np.array([0.0])
    _total_len = 1000.0

    def project_point(self, lat, lng):
        return lat * 1000.0, abs(lng) * 1000.0, 0

    def segment_unit_tangent(self, index):
        return 0.0, 1.0


class _FakeDataAccess:
    def __init__(self):
        self.looked_up_pairs = []

    def lookup_baseline_tt(self, route_id, dir_int, from_order, to_order, day_type, hour_slot, seg_len_m):
        self.looked_up_pairs.append((from_order, to_order))
        return 50.0, 60.0, 80.0, 62.0, 10.0


def test_sparse_station_order_eta_and_app_endpoint(monkeypatch):
    """AUD-P0-01: station_order có gap ([0, 1, 2, 4, 5]) không lỗi IndexError/404 và tra đúng (2, 4)."""
    da = _FakeDataAccess()
    station_s = [0.0, 200.0, 400.0, 700.0, 900.0]
    station_orders = [0, 1, 2, 4, 5]
    target_st = StationItemDTO(
        station_id=505,
        station_order=5,
        station_name="Trạm cuối 5",
        lat=0.9,
        lon=0.0,
        cum_distance_m=900.0,
    )
    now = 2000.0
    v = BusVehicleDTO(
        id=1,
        plate="29B11111",
        route_id=42,
        direction=1,
        lat=0.5,
        lng=0.0,
        deg=0.0,
        speed_kmh=25.0,
        raw_speed_kmh=25.0,
        updated_at=datetime.fromtimestamp(now - 5, TZ_HANOI).isoformat(),
    )
    bs = BusState(
        vehicle=v,
        s_now=500.0,
        d_station=400.0,
        v_obs_mps=25.0 / 3.6,
        delta_t_age=5.0,
        t_ping=now - 5,
        seg_idx=0,
        ping_time="12:00:00",
    )

    dto = compute_station_eta(
        bs,
        route_id=42,
        dir_int=1,
        target_st=target_st,
        station_s=station_s,
        now_epoch=now,
        data_access=da,
        day_type=0,
        hour_slot=12,
        ml_p50=None,
        prediction_source="baseline_fallback",
        station_orders=station_orders,
    )
    assert dto.stops_remaining == 2
    assert da.looked_up_pairs == [(2, 4), (4, 5)]

    sparse_stations = RouteStationsResponse(
        route_id=42,
        route_code="42",
        direction=1,
        direction_str="re",
        station_count=5,
        stations=[
            StationItemDTO(station_id=100 + o, station_order=o, station_name=f"S{o}", lat=s / 1000.0, lon=0.0, cum_distance_m=s)
            for o, s in zip(station_orders, station_s)
        ],
    )
    dummy_service = SimpleNamespace(
        resolve_route_id=lambda ident: 42,
        get_route_stations=lambda rid, d: sparse_stations,
        get_station_eta=lambda rid, d, so: SimpleNamespace(ok=True, station_order=so),
    )
    monkeypatch.setattr(web_app, "service", dummy_service)
    res_last = web_app.get_station_eta(route_id=42, direction=1, station_order=5)
    assert res_last.station_order == 5

    with pytest.raises(HTTPException) as exc_info:
        web_app.get_station_eta(route_id=42, direction=1, station_order=3)
    assert exc_info.value.status_code == 404


def test_at_station_d_zero_returns_zero_eta():
    """AUD-P1-08: Xe đang ở đúng trạm (d_station == 0.0) không được cộng thời gian chặng kế tiếp."""
    da = _FakeDataAccess()
    station_s = [0.0, 200.0, 500.0, 900.0]
    target_st = StationItemDTO(
        station_id=2, station_order=2, station_name="Giữa tuyến", lat=0.5, lon=0.0, cum_distance_m=500.0
    )
    now = 2000.0
    v = BusVehicleDTO(
        id=2,
        plate="29B22222",
        route_id=1,
        direction=0,
        lat=0.5,
        lng=0.0,
        speed_kmh=0.0,
        raw_speed_kmh=0.0,
        updated_at=datetime.fromtimestamp(now, TZ_HANOI).isoformat(),
    )
    bs = BusState(
        vehicle=v, s_now=500.0, d_station=0.0, v_obs_mps=0.0, delta_t_age=0.0, t_ping=now, seg_idx=0, ping_time="12:00:00"
    )
    dto = compute_station_eta(
        bs, 1, 0, target_st, station_s, now, da, 0, 12, ml_p50=300.0, prediction_source="ml_calibrated"
    )
    assert dto.eta_seconds == 0.0
    assert dto.stops_remaining == 0
    assert da.looked_up_pairs == []


def test_stopped_bus_heading_and_traffic_status_and_tracker_reset():
    """AUD-P0-06 & AUD-P1-07: Xe dừng 0 km/h được seed ~18 km/h không bị loại heading, gắn UN_TAC, và reset sau 1800s."""
    shape = _FakeShape()
    now = 5000.0
    v = BusVehicleDTO(
        id=3,
        plate="29B33333",
        route_id=1,
        direction=0,
        lat=0.2,
        lng=0.0,
        deg=180.0,
        speed_kmh=18.0,
        raw_speed_kmh=0.0,
        speed_window_sec=5.0,
        updated_at=datetime.fromtimestamp(now - 2, TZ_HANOI).isoformat(),
    )
    bs = project_filter_extrapolate(v, shape, 800.0, now)
    assert bs is not None

    da = _FakeDataAccess()
    target_st = StationItemDTO(station_id=3, station_order=2, station_name="S2", lat=0.8, lon=0.0, cum_distance_m=800.0)
    dto = compute_station_eta(bs, 1, 0, target_st, [0.0, 400.0, 800.0], now, da, 0, 12, None, "baseline_fallback")
    assert dto.traffic_status == "UN_TAC"

    tracker = MacroSpeedTracker()
    tracker.observe_and_estimate(1, 0, "29B33333", 100.0, 100.0, 25.0, 25.0, 18.0)
    tracker.observe_and_estimate(1, 0, "29B33333", 250.0, 1100.0, 25.0, 25.0, 18.0)
    spd, win_dt = tracker.observe_and_estimate(1, 0, "29B33333", 250.0 + 3600.0, 120.0, 0.0, 0.0, 18.0)
    assert win_dt == 0.0
    assert spd == 18.0
    removed = tracker.sweep_stale(250.0 + 3600.0 + 4000.0, max_idle_sec=3600.0)
    assert removed == 1


def test_clock_skewed_busmap_does_not_beat_timbus_and_stale_not_recorded_as_passed(monkeypatch):
    """AUD-P0-04 & AUD-P1-08: BusMap clock chạy nhanh hơn now_epoch không đè TimBus; ping quá hạn không ghi vào Pass Guard."""
    svc = BusMapServingService.__new__(BusMapServingService)
    svc._tb_lock = threading.Lock()
    svc._tb_last_valid = {}
    svc._passed_station_plates = {}
    svc._projection_generations = {}
    svc._causal_lock = threading.Lock()
    svc._causal = SimpleNamespace(observe=lambda *a, **k: None, observe_snapshot=lambda *a, **k: None)
    svc._apply_macro_speeds = lambda *args: args[4]
    svc._da = SimpleNamespace(get_timbus_anchors=lambda *args: (True, [1]))
    svc._get_shape_model = lambda *args: _FakeShape()
    svc._prepare_vehicle = lambda route, direction, v, now: v.model_copy(
        update={"projection_checked": True, "matched_projection": _FakeShape().project_point(v.lat, v.lng)}
    )

    now = 1000.0
    bm_skewed = BusVehicleDTO(
        id=10,
        plate="29B-444.44",
        route_id=1,
        direction=0,
        lat=0.25,
        lng=0.0,
        speed_kmh=15.0,
        updated_at=datetime.fromtimestamp(now + 120.0, TZ_HANOI).isoformat(),
    )
    monkeypatch.setattr(
        TimBusClient,
        "query_central_vehicles",
        lambda **kwargs: {
            "29B44444": BusRecord(
                plate="29B44444",
                route="01",
                next_station_id=500,
                distance_m=10,
                next_station_name="Bến",
                speed_kmh=20,
                latitude=0.20,
                longitude=0.0,
                status=0,
                direction="Đi",
            )
        },
    )
    bm_proj = {"29B44444": (bm_skewed, 250.0, 0.0)}
    merged = svc._sync_and_merge_timbus(
        1, 0, "go", [1], ["29B44444"], bm_proj, [bm_skewed], _FakeShape(), now, s_target=800.0, use_live_cache=False
    )
    assert len(merged) == 1
    assert merged[0].telemetry_source == "timbus"

    stale_past = BusVehicleDTO(
        id=11,
        plate="29B-555.55",
        route_id=1,
        direction=0,
        lat=0.90,
        lng=0.0,
        speed_kmh=20.0,
        updated_at=datetime.fromtimestamp(now - 500.0, TZ_HANOI).isoformat(),
    )
    out = svc._filter_station_vehicles(1, 0, [stale_past], _FakeShape(), now, s_target=500.0, station_order=2)
    assert out == []
    assert svc._passed_station_plates == {}


def test_model_runtime_validate_route_mapping_and_poller_off_hours_cleanup():
    """AUD-P1-05 & AUD-P1-07: Kiểm tra khớp manifest_routes và dọn _prev_active khi vào off_hours."""
    fake_res = SimpleNamespace(domains={"route_id_idx": [0, 1]})
    rt = ModelRuntime(residual_eta=fake_res, manifest_routes=("02", "01"))
    assert rt.validate_route_mapping({"01": 0, "02": 1}) is True
    assert rt.available is True
    assert rt.validate_route_mapping({"01": 0, "02": 1, "99": 2}) is False
    assert rt.available is False

    svc = SimpleNamespace(get_poller_route_ids=lambda: [])
    poller = SpeedLayerPoller(svc, now_fn=lambda: datetime(2026, 11, 26, 23, 0, tzinfo=TZ_HANOI).timestamp())
    poller._prev_active[(1, 0)] = {"29A00001": object()}
    poller._cooldowns[(1, 0, "29A00001")] = datetime(2026, 11, 26, 22, 0, tzinfo=TZ_HANOI).timestamp()
    threading.Timer(0.05, poller._stop_event.set).start()
    poller._run_loop()
    assert poller._prev_active == {}
    assert poller._cooldowns == {}


def test_telemetry_sanitizer_naive_iso_uses_hanoi_tz():
    """AUD-P0-03: Naive ISO string phải được gắn TZ_HANOI (+07:00), bất biến theo timezone hệ điều hành."""
    raw = {
        "Lat": 105.85,
        "Lng": 21.02,
        "Speed": 20.0,
        "direction": 0,
        "RouteId": 1,
        "lastUpdateTime": "2026-11-26T10:00:00",
        "currentStationId": 10,
    }
    cache = {}
    res = sanitize_and_validate_telemetry(raw, vid=99, target_route_ids={1}, kinematic_cache=cache)
    assert res is not None
    expected_epoch = datetime(2026, 11, 26, 10, 0, 0, tzinfo=TZ_HANOI).timestamp()
    assert abs(cache[99]["epoch"] - expected_epoch) < 1e-6
