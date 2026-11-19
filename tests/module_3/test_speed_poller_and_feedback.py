"""Unit tests for SpeedLayerPoller, CausalFeatures thread-safety, and explicit feedback."""

from datetime import datetime
import threading
import types

from fastapi.testclient import TestClient

from config.system_config import TZ_HANOI
from module_3_bus_eta_prediction.step_3_2_feature_store_extractor.causal_eta import (
    CausalFeatures,
    Observation,
)
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation import live_feed
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.dto import (
    BusVehicleDTO,
    RouteLiveResponse,
)
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.model_runtime import (
    ModelRuntime,
)
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.speed_poller import (
    CIRCUIT_ERROR_THRESHOLD,
    SpeedLayerPoller,
    is_operating_hours,
)


def _make_dto(plate: str, age_sec: float, now_ts: float, speed_kmh: float = 0.0) -> BusVehicleDTO:
    iso = datetime.fromtimestamp(now_ts - age_sec, tz=TZ_HANOI).isoformat()
    return BusVehicleDTO(
        id=101,
        plate=plate,
        route_id=27,
        direction=0,
        lat=21.0285,
        lng=105.8542,
        speed_kmh=speed_kmh,
        updated_at=iso,
        matched_projection=(1200.0, 10.0, 2),
    )


class _StubService:
    def __init__(self, recent_plates=None, endpoints=(0.0, 5000.0), near_ct=10.0):
        self.recent_plates = set(recent_plates or ())
        self.endpoints = endpoints
        self.near_ct = near_ct
        self.ingested_bm = []
        self.ingested_tb = []

    def get_poller_route_ids(self):
        return [27]

    def get_timbus_anchors(self, route_id, dir_int):
        return (True, [1676]) if dir_int == 0 else (False, [])

    def get_route_endpoint_s(self, route_id, dir_str):
        return self.endpoints

    def get_recent_timbus_plates(self, route_id, dir_int, now_epoch, max_age_sec=45.0):
        return set(self.recent_plates)

    def ingest_speed_layer_vehicles(self, route_id, dir_int, vehicles, now_epoch):
        self.ingested_bm.append((route_id, dir_int, len(vehicles)))
        return [v.model_copy(update={"matched_projection": (v.matched_projection[0], self.near_ct, 2)}) for v in vehicles]

    def ingest_speed_layer_timbus_hit(self, route_id, dir_int, bm_v, tb_rec, now_epoch):
        self.ingested_tb.append((route_id, dir_int, bm_v.plate))
        return bm_v


def test_is_operating_hours_boundaries():
    t_day = datetime(2026, 11, 19, 12, 0, tzinfo=TZ_HANOI).timestamp()
    t_open = datetime(2026, 11, 19, 4, 45, tzinfo=TZ_HANOI).timestamp()
    t_close = datetime(2026, 11, 19, 22, 30, tzinfo=TZ_HANOI).timestamp()
    t_night = datetime(2026, 11, 19, 2, 15, tzinfo=TZ_HANOI).timestamp()
    assert is_operating_hours(t_day) is True
    assert is_operating_hours(t_open) is True
    assert is_operating_hours(t_close) is False
    assert is_operating_hours(t_night) is False


def test_speed_poller_dedup_and_4_state_classification():
    now_ts = 1_700_000_000.0
    # 29B00001: recent in Serving -> skipped; 29B00002: hit -> RECOVERED_LIVE
    # 29B00003: miss + speed=0 + near terminal -> TERMINAL_OR_DEPOT_PARKED
    # 29B00004: miss + moving on corridor -> ON_CORRIDOR_GAP
    v_skip = _make_dto("29B-000.01", 80.0, now_ts, speed_kmh=20.0)
    v_hit = _make_dto("29B-000.02", 80.0, now_ts, speed_kmh=20.0)
    v_park = _make_dto("29B-000.03", 80.0, now_ts, speed_kmh=0.0).model_copy(
        update={"matched_projection": (100.0, 10.0, 0)}
    )
    v_gap = _make_dto("29B-000.04", 80.0, now_ts, speed_kmh=25.0).model_copy(
        update={"matched_projection": (2000.0, 10.0, 4)}
    )

    svc = _StubService(recent_plates={"29B00001"}, endpoints=(0.0, 5000.0))

    def fake_route_fetcher(r_id, d):
        vehs = [v_skip, v_hit, v_park, v_gap] if d == 0 else []
        return RouteLiveResponse(route_id=r_id, direction=d, count=len(vehs), timestamp="t", vehicles=vehs)

    queried_plates = []

    def fake_tb_fetcher(station_ids, plates, direction=0, timeout=3):
        queried_plates.extend(plates)
        if "29B00002" in plates:
            rec = types.SimpleNamespace(
                plate="29B00002", latitude=21.03, longitude=105.85, speed_kmh=22.0, fetch_timestamp=now_ts
            )
            return {"29B00002": rec}, 1, 0, None
        return {}, 1, 0, None

    poller = SpeedLayerPoller(
        svc,
        stagger_delay_sec=0.0,
        route_fetcher=fake_route_fetcher,
        timbus_fetcher=fake_tb_fetcher,
        now_fn=lambda: now_ts,
    )
    res = poller.run_once(now_epoch=now_ts)

    assert "29B00001" not in queried_plates
    assert res["RECOVERED_LIVE"] == 1
    assert res["TERMINAL_OR_DEPOT_PARKED"] == 1
    assert res["ON_CORRIDOR_GAP"] == 1
    assert len(svc.ingested_tb) == 1
    assert poller._cooldowns[(27, 0, "29B00003")] == now_ts + 180.0
    assert poller._cooldowns[(27, 0, "29B00004")] == now_ts + 45.0


def test_speed_poller_circuit_breaker_opens_on_errors():
    now_ts = 1_700_000_000.0
    vehs = [_make_dto(f"29B-000.0{i}", 90.0 + i, now_ts, speed_kmh=15.0) for i in range(1, 5)]
    svc = _StubService()

    def fake_route_fetcher(r_id, d):
        return RouteLiveResponse(
            route_id=r_id, direction=d, count=len(vehs) if d == 0 else 0,
            timestamp="t", vehicles=vehs if d == 0 else []
        )

    def fake_tb_err(station_ids, plates, direction=0, timeout=3):
        return {}, 0, 1, "TimeoutError: timed out"

    poller = SpeedLayerPoller(
        svc,
        timbus_workers=1,
        stagger_delay_sec=0.0,
        circuit_breaker_sec=90.0,
        route_fetcher=fake_route_fetcher,
        timbus_fetcher=fake_tb_err,
        now_fn=lambda: now_ts,
    )
    res = poller.run_once(now_epoch=now_ts)
    assert res["UPSTREAM_ERROR"] == CIRCUIT_ERROR_THRESHOLD
    assert res["skipped_circuit"] == 1
    snap = poller.get_health_snapshot()
    assert snap["circuit_state"] == "OPEN"
    assert snap["status"] == "degraded"


def test_causal_features_thread_safety():
    class _FakeDA:
        def get_shape_points(self, route_id, dir_str):
            return [(0, 21.0, 105.8, 0.0), (1, 21.01, 105.81, 1500.0)]

        def get_corridor_stations(self, route_id, dir_str):
            return [(0, 1, "S0", 0.0), (1, 2, "S1", 1000.0)]

        def get_route_idx(self, route_id):
            return 0

        def get_route_profile(self, route_id, dir_str):
            return 20.0, 500.0, 1000.0

        def get_baseline_cell(self, route_id, direction, s_from, s_to, day, hour):
            return (150.0, 180.0, 220.0, 185.0, 20.0, 0)

    cf = CausalFeatures(_FakeDA())
    errors = []

    def writer():
        try:
            for i in range(50):
                t = 1_700_000_000.0 + i * 5
                cf.observe(Observation(27, 0, "29B00001", "busmap", t, t, 21.001 + i * 1e-4, 105.801, (i,), "live"))
                cf.observe_snapshot(27, 0, t, ["29B00001"])
        except Exception as exc:
            errors.append(exc)

    def reader():
        try:
            for i in range(50):
                cf.features(27, 0, "29B00001", 1, 1_700_000_000.0 + i * 5)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=writer), threading.Thread(target=reader)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors


def test_explicit_feedback_upstream_error_and_health(monkeypatch):
    monkeypatch.setenv("DISABLE_SPEED_POLLER", "1")
    monkeypatch.setattr(
        "module_1_data_ingestion_and_preprocessing.step_1_1_busmap_crawler_and_relay.catalog_refresher.fetch_route_buses_live_status",
        lambda route_id, direction=0: ([], "URLError: connection refused"),
    )
    live_feed.live_cache.clear()
    resp = live_feed.fetch_live_vehicles_for_route(route_id=99999, direction=0)
    assert resp.upstream_status == "upstream_error"
    assert "connection refused" in (resp.upstream_error or "")

    runtime = ModelRuntime(residual_eta=None)
    eta, reason = runtime.predict_p50_with_reason({"route_id_idx": 0})
    assert eta is None
    assert reason == "model_unavailable"

    from module_3_bus_eta_prediction.step_3_5_web_demo import app as web_app

    monkeypatch.setattr(
        web_app.speed_poller,
        "get_health_snapshot",
        lambda: {"status": "degraded", "circuit_state": "OPEN", "cycle_count": 1},
    )
    client = TestClient(web_app.app)
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "degraded"
    assert body["healthy"] is False
    assert body["poller"]["circuit_state"] == "OPEN"
