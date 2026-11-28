"""Integration & DoD verification tests for decoupled Speed Layer (SQLite WAL bridge)."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import importlib
import os
import sqlite3
import subprocess
import sys
import types

from fastapi.testclient import TestClient

from config.system_config import TZ_HANOI
from modules.eta.serving.dto import BusVehicleDTO, RouteLiveResponse
from modules.eta.serving.serving_service import BusMapServingService
from modules.eta.serving.speed_poller import SpeedLayerPoller
from modules.eta.serving.speed_view_store import SpeedViewStore, SpeedViewSyncer


def _make_live_dto(
    plate: str,
    now_ts: float,
    age_sec: float = 10.0,
    lat: float = 21.0285,
    lng: float = 105.8542,
    speed_kmh: float = 24.0,
    route_id: int = 2,
    direction: int = 0,
    vid: int = 101,
) -> BusVehicleDTO:
    iso = datetime.fromtimestamp(now_ts - age_sec, tz=TZ_HANOI).isoformat()
    return BusVehicleDTO(
        id=vid,
        plate=plate,
        route_id=route_id,
        direction=direction,
        lat=lat,
        lng=lng,
        speed_kmh=speed_kmh,
        raw_speed_kmh=speed_kmh,
        updated_at=iso,
    )


def _pick_route_and_point(svc: BusMapServingService):
    """Pick a real baseline route that has shapes, stations, and TimBus anchors."""
    for rid in svc.get_poller_route_ids():
        ok, anchors = svc.get_timbus_anchors(rid, 0)
        shape = svc.get_route_shape(rid, 0)
        if ok and anchors and shape and shape.coordinates:
            mid = shape.coordinates[len(shape.coordinates) // 2]
            return rid, anchors[0], float(mid[0]), float(mid[1])
    raise AssertionError("No route with TimBus anchors and shape found in Serving DB")


def test_dod1_speed_worker_has_zero_fastapi_or_uvicorn_import():
    """DoD-1: Importing speed_worker / running wrapper must never import fastapi or uvicorn."""
    code = (
        "import sys; "
        "import modules.eta.serving.speed_worker; "
        "bad = [m for m in ('fastapi', 'uvicorn') if m in sys.modules]; "
        "assert not bad, f'Unexpected web imports: {bad}'"
    )
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert res.returncode == 0, res.stderr or res.stdout


def test_dod2_sqlite_wal_schema_pragmas_and_concurrent_rw(tmp_path):
    """DoD-2: Verify WAL mode, 4-table DDL, TTL pruning, and lock-free concurrent RW."""
    db_path = tmp_path / "speed_view.db"
    writer = SpeedViewStore(db_path, create_if_missing=True)
    reader = SpeedViewStore(db_path, create_if_missing=False)
    try:
        conn = sqlite3.connect(str(db_path))
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        conn.close()
        assert str(mode).lower() == "wal"
        assert {
            "speed_batches",
            "recent_timbus_focus",
            "live_incidents_snapshot",
            "poller_health",
        }.issubset(tables)

        now_ts = 1_700_000_000.0
        session_id = "sess-wal-test"

        def write_worker():
            for idx in range(1, 26):
                dto = _make_live_dto("29B-111.11", now_ts + idx, lat=21.02 + idx * 1e-4, vid=idx)
                writer.append_busmap_batch(session_id, 2, 0, now_ts + idx, [dto])
                writer.save_health(
                    session_id,
                    os.getpid(),
                    {"status": "running", "cycle_count": idx, "last_cycle_epoch": now_ts + idx},
                    now_ts + idx,
                )

        def read_focus_worker():
            seen = 0
            last_seq = 0
            for idx in range(25):
                reader.record_focus_timbus_hits(2, 0, [("29B99999", now_ts + idx)])
                batches, last_seq, _, _, _ = reader.fetch_batches_since(last_seq, session_id, min_epoch=0.0)
                seqs = [b["seq"] for b in batches]
                assert seqs == sorted(seqs)
                seen += len(batches)
            # Drain remaining tail
            batches, last_seq, _, _, _ = reader.fetch_batches_since(last_seq, session_id, min_epoch=0.0)
            seen += len(batches)
            return seen

        with ThreadPoolExecutor(max_workers=2) as pool:
            wf = pool.submit(write_worker)
            rf = pool.submit(read_focus_worker)
            wf.result()
            _ = rf.result()

        # Verify all 25 batches readable in strict seq order
        all_batches, end_seq, _, _, _ = reader.fetch_batches_since(0, None, min_epoch=0.0)
        assert len(all_batches) == 25
        assert [b["seq"] for b in all_batches] == list(range(1, 26))
        assert end_seq == 25

        # Prune older than TTL=10s relative to now_ts + 25
        removed = writer.prune_expired(now_ts + 25, ttl_sec=10.0)
        assert removed > 0
        rem_batches, _, _, _, _ = reader.fetch_batches_since(0, None, min_epoch=0.0)
        assert all(b["observed_epoch"] >= now_ts + 15 for b in rem_batches)
    finally:
        reader.close()
        writer.close()


def test_dod3_cross_process_timbus_politeness(tmp_path, monkeypatch):
    """DoD-3: Real BusMapServingService 5s focus hit writes SQLite lease; Speed Worker skips within <45s."""
    import modules.eta.serving.serving_service as serving_mod
    from modules.eta.serving.timbus_client import TimBusClient

    db_path = tmp_path / "speed_view.db"
    now_ts = datetime.now(TZ_HANOI).timestamp()

    serving_store = SpeedViewStore(db_path, create_if_missing=True)
    serving_svc = BusMapServingService(load_model=False, speed_view_store=serving_store)
    rid, anchor, lat, lng = _pick_route_and_point(serving_svc)

    speed_store = SpeedViewStore(db_path, create_if_missing=True)
    speed_svc = BusMapServingService(load_model=False)
    try:
        stale_bm = _make_live_dto(
            "29B-777.77", now_ts, age_sec=90.0, lat=lat, lng=lng, speed_kmh=18.0, route_id=rid, direction=0
        )

        # Drive the REAL Serving focus-mode flow via get_live_vehicles (no direct store bypass)
        monkeypatch.setattr(
            serving_mod,
            "fetch_live_vehicles_for_route",
            lambda route_id, direction: RouteLiveResponse(
                route_id=route_id,
                direction=direction,
                count=1 if direction == 0 else 0,
                timestamp="t",
                vehicles=[stale_bm] if direction == 0 else [],
            ),
        )
        tb_hit = types.SimpleNamespace(
            plate="29B77777",
            route="",
            latitude=lat,
            longitude=lng,
            speed_kmh=21.0,
            fetch_timestamp=now_ts,
        )
        monkeypatch.setattr(
            TimBusClient,
            "query_central_vehicles_with_status",
            staticmethod(lambda **kw: ({"29B77777": tb_hit} if kw.get("direction") == 0 else {}, 1, 0, None)),
        )

        live_resp = serving_svc.get_live_vehicles(rid, 0)
        assert live_resp.count == 1
        assert "29B77777" in serving_store.get_recent_focus_plates(rid, 0, now_ts + 5.0, max_age_sec=45.0)

        queried = []

        def fake_route_fetcher(r_id, d):
            vehs = [stale_bm] if (r_id == rid and d == 0) else []
            return RouteLiveResponse(route_id=r_id, direction=d, count=len(vehs), timestamp="t", vehicles=vehs)

        def fake_tb_fetcher(station_ids, plates, direction=0, timeout=3):
            queried.extend(plates)
            return {}, len(station_ids), 0, None

        poller = SpeedLayerPoller(
            speed_svc,
            poll_interval_sec=45.0,
            stagger_delay_sec=0.0,
            route_fetcher=fake_route_fetcher,
            timbus_fetcher=fake_tb_fetcher,
            incident_fetcher=lambda: (None, None),
            now_fn=lambda: now_ts + 20.0,
            view_store=speed_store,
        )
        poller._service = types.SimpleNamespace(
            get_poller_route_ids=lambda: [rid],
            get_timbus_anchors=speed_svc.get_timbus_anchors,
            get_recent_timbus_plates=speed_svc.get_recent_timbus_plates,
            ingest_speed_layer_vehicles=speed_svc.ingest_speed_layer_vehicles,
            ingest_speed_layer_timbus_hit=speed_svc.ingest_speed_layer_timbus_hit,
            get_route_endpoint_s=speed_svc.get_route_endpoint_s,
            sweep_stale_state=speed_svc.sweep_stale_state,
        )

        # At t+20s (<45s lease): Speed Layer MUST skip 29B77777
        poller.run_once(now_epoch=now_ts + 20.0)
        assert "29B77777" not in queried

        # At t+50s (>45s lease expired): Speed Layer may query 29B77777
        poller.run_once(now_epoch=now_ts + 50.0)
        assert "29B77777" in queried
    finally:
        serving_store.close()
        speed_store.close()


def test_dod4_and_dod5_timestamp_merge_bootstrap_and_session_reset(tmp_path):
    """DoD-4 & DoD-5: Preserve fresher 5s hit, replay into CausalFeatures/MacroSpeed, reset on new session."""
    db_path = tmp_path / "speed_view.db"
    now_ts = datetime(2026, 11, 28, 12, 0, tzinfo=TZ_HANOI).timestamp()

    store_writer = SpeedViewStore(db_path, create_if_missing=True)
    probe_svc = BusMapServingService(load_model=False)
    rid, _, lat, lng = _pick_route_and_point(probe_svc)
    shape = probe_svc.get_route_shape(rid, 0)
    p1_lat, p1_lng = float(shape.coordinates[1][0]), float(shape.coordinates[1][1])
    p2_lat, p2_lng = float(shape.coordinates[2][0]), float(shape.coordinates[2][1])

    store_reader = SpeedViewStore(db_path, create_if_missing=False)
    restarted_svc = BusMapServingService(load_model=False, speed_view_store=store_reader)
    try:
        # Cycle 1 & Cycle 2 written by Speed Worker session A
        v1 = _make_live_dto("29B-555.55", now_ts, age_sec=5.0, lat=p1_lat, lng=p1_lng, route_id=rid)
        v2 = _make_live_dto("29B-555.55", now_ts + 45.0, age_sec=5.0, lat=p2_lat, lng=p2_lng, route_id=rid)
        store_writer.append_busmap_batch("sess-A", rid, 0, now_ts, [v1])
        store_writer.append_busmap_batch("sess-A", rid, 0, now_ts + 45.0, [v2])
        store_writer.save_incidents(
            {"fetched_at": "2026-11-28T12:00:00+07:00", "count": 1, "incidents": [{"incident_id": "i1"}]},
            now_ts + 45.0,
        )
        store_writer.save_health("sess-A", 1234, {"status": "running", "cycle_count": 2}, now_ts + 45.0)

        # Simulate Serving already holding fresher 5s hit at t=now_ts+30 (distinct vehicle id)
        fresh_dto = _make_live_dto(
            "29B-888.88", now_ts + 30.0, age_sec=0.0, lat=lat, lng=lng, route_id=rid, vid=102
        )
        tb_old = types.SimpleNamespace(
            plate="29B88888", route="", latitude=lat, longitude=lng, speed_kmh=30.0, fetch_timestamp=now_ts + 10.0
        )
        tb_fresh = types.SimpleNamespace(
            plate="29B88888", route="", latitude=lat, longitude=lng, speed_kmh=35.0, fetch_timestamp=now_ts + 30.0
        )
        restarted_svc.ingest_speed_layer_timbus_hit(rid, 0, fresh_dto, tb_fresh, now_ts + 30.0)
        store_writer.append_timbus_hit("sess-A", rid, 0, fresh_dto, tb_old, now_ts + 10.0)

        # Anti-cold-start bootstrap via sync_from_speed_view
        replayed = restarted_svc.sync_from_speed_view(now_epoch=now_ts + 60.0)
        assert replayed == 3
        assert restarted_svc._speed_view_last_seq == 3
        assert restarted_svc._speed_view_session_id == "sess-A"
        assert len(restarted_svc._live_incidents_raw) == 1
        assert (rid, "29B55555") in restarted_svc._causal._states
        assert len(restarted_svc._causal._states[(rid, "29B55555")].observations) >= 2
        assert len(restarted_svc._causal._states[(rid, "29B55555")].matcher.best_path) >= 2
        assert (rid, 0) in restarted_svc._causal._snapshots
        # Timestamp merge guard: older t+10 Speed hit did NOT overwrite fresher t+30 hit
        kept_ts, _, kept_dto = restarted_svc._tb_last_valid[(rid, 0, "29B88888")]
        assert kept_ts == now_ts + 30.0
        assert kept_dto.speed_kmh == 35.0

        # Normal Speed Worker restart on EXISTING DB (new session_id, monotonic seq=4):
        # MUST NOT re-replay seq 1..3!
        v3 = _make_live_dto("29B-555.55", now_ts + 70.0, age_sec=5.0, lat=p2_lat, lng=p2_lng, route_id=rid)
        store_writer.save_health("sess-A2", 1235, {"status": "running", "cycle_count": 1}, now_ts + 70.0)
        store_writer.append_busmap_batch("sess-A2", rid, 0, now_ts + 70.0, [v3])
        replayed_a2 = restarted_svc.sync_from_speed_view(now_epoch=now_ts + 75.0)
        assert replayed_a2 == 1
        assert restarted_svc._speed_view_last_seq == 4
        assert restarted_svc._speed_view_session_id == "sess-A2"

        # New DB replacement where new seq catches up / exceeds old cursor (last_seq=4, new DB has 6 batches):
        # db_lifecycle_id mismatch MUST reset cursor to 0 and replay ALL 6 batches (not only [5, 6])!
        prev_db_id = restarted_svc._speed_view_db_id
        assert prev_db_id is not None
        store_writer.close()
        store_reader.close()
        for ext in ("", "-wal", "-shm"):
            p = db_path.with_name(db_path.name + ext)
            if p.exists():
                p.unlink()

        store_writer_b = SpeedViewStore(db_path, create_if_missing=True)
        store_writer_b.save_health("sess-B", 2345, {"status": "running", "cycle_count": 6}, now_ts + 96.0)
        for idx in range(6):
            pt = shape.coordinates[min(idx + 1, len(shape.coordinates) - 1)]
            vx = _make_live_dto(
                "29B-666.66",
                now_ts + 90.0 + idx,
                age_sec=1.0,
                lat=float(pt[0]),
                lng=float(pt[1]),
                route_id=rid,
                vid=103,
            )
            store_writer_b.append_busmap_batch("sess-B", rid, 0, now_ts + 90.0 + idx, [vx])
        replayed_b = restarted_svc.sync_from_speed_view(now_epoch=now_ts + 100.0)
        assert replayed_b == 6
        assert restarted_svc._speed_view_last_seq == 6
        assert restarted_svc._speed_view_session_id == "sess-B"
        assert restarted_svc._speed_view_db_id != prev_db_id
        store_writer_b.close()
    finally:
        store_writer.close()
        store_reader.close()


def test_dod6_external_mode_graceful_degradation_and_stale_health(tmp_path, monkeypatch):
    """DoD-6: External mode works cleanly without speed_view.db and marks stale heartbeats."""
    missing_view = tmp_path / "nonexistent_speed_view.db"
    monkeypatch.setenv("SPEED_LAYER_MODE", "external")
    monkeypatch.delenv("DISABLE_SPEED_POLLER", raising=False)
    monkeypatch.setenv("SPEED_VIEW_DB_PATH", str(missing_view))

    from modules.eta.web_demo import app as web_app

    importlib.reload(web_app)
    try:
        with TestClient(web_app.app) as client:
            r = client.get("/api/health")
            assert r.status_code == 200
            body = r.json()
            assert body["poller"]["mode"] == "external"
            assert body["poller"]["status"] == "waiting_external"
            assert web_app.speed_poller._thread is None

        # Verify stale detection during operating hours
        day_ts = datetime(2026, 11, 28, 12, 0, tzinfo=TZ_HANOI).timestamp()
        writer = SpeedViewStore(missing_view, create_if_missing=True)
        writer.save_health("sess-stale", 999, {"status": "running", "cycle_count": 4}, day_ts - 200.0)
        writer.close()
        health_snap = web_app.speed_view_store.load_health(day_ts, stale_after_sec=120.0)
        assert health_snap["status"] == "stale"
    finally:
        if getattr(web_app, "speed_view_store", None) is not None:
            web_app.speed_view_store.close()
        monkeypatch.delenv("SPEED_LAYER_MODE", raising=False)
        monkeypatch.delenv("SPEED_VIEW_DB_PATH", raising=False)
        importlib.reload(web_app)


def test_p1_snapshot_monotonicity_blocks_older_replay(tmp_path):
    """P1: Older Speed replay at t must never overwrite newer live snapshot at t+5."""
    db_path = tmp_path / "speed_view.db"
    now_ts = datetime(2026, 11, 28, 12, 0, tzinfo=TZ_HANOI).timestamp()
    writer = SpeedViewStore(db_path, create_if_missing=True)
    reader = SpeedViewStore(db_path, create_if_missing=False)
    svc = BusMapServingService(load_model=False, speed_view_store=reader)
    try:
        rid, _, _, _ = _pick_route_and_point(svc)
        shape = svc.get_route_shape(rid, 0)
        p1, p2 = shape.coordinates[1], shape.coordinates[2]

        live_new = _make_live_dto("29B-NEW.02", now_ts + 5.0, age_sec=0.0, lat=float(p2[0]), lng=float(p2[1]), route_id=rid, vid=202)
        svc.ingest_speed_layer_vehicles(rid, 0, [live_new], now_ts + 5.0)
        assert svc._causal._snapshots[(rid, 0)] == (now_ts + 5.0, frozenset({"29BNEW02"}), True)

        old_replay = _make_live_dto("29B-OLD.01", now_ts, age_sec=0.0, lat=float(p1[0]), lng=float(p1[1]), route_id=rid, vid=201)
        writer.append_busmap_batch("sess-snap", rid, 0, now_ts, [old_replay])
        replayed = svc.sync_from_speed_view(now_epoch=now_ts + 10.0)
        assert replayed == 1
        assert svc._causal._snapshots[(rid, 0)] == (now_ts + 5.0, frozenset({"29BNEW02"}), True)
    finally:
        reader.close()
        writer.close()


def test_p1_macro_speed_warm_immediately_after_bootstrap(tmp_path):
    """P1: Replaying 5 batches spaced 45s apart warms MacroSpeedTracker immediately on bootstrap."""
    db_path = tmp_path / "speed_view.db"
    now_ts = datetime(2026, 11, 28, 12, 0, tzinfo=TZ_HANOI).timestamp()
    writer = SpeedViewStore(db_path, create_if_missing=True)
    reader = SpeedViewStore(db_path, create_if_missing=False)
    svc = BusMapServingService(load_model=False, speed_view_store=reader)
    try:
        import math

        rid, _, _, _ = _pick_route_and_point(svc)
        shape = svc.get_route_shape(rid, 0)
        coords = shape.coordinates
        pts = [coords[1]]
        idx = 1
        while len(pts) < 5 and idx + 1 < len(coords):
            a, b = pts[-1], coords[idx + 1]
            d = math.hypot((b[0] - a[0]) * 111320.0, (b[1] - a[1]) * 111320.0 * math.cos(math.radians(a[0])))
            if d < 180.0:
                idx += 1
            elif d > 400.0:
                frac = 250.0 / d
                pts.append((a[0] + frac * (b[0] - a[0]), a[1] + frac * (b[1] - a[1])))
            else:
                pts.append(b)
                idx += 1
        assert len(pts) == 5
        for i, pt in enumerate(pts):
            obs_t = now_ts + i * 45.0
            dto = _make_live_dto("29B-454.54", obs_t, age_sec=0.0, lat=float(pt[0]), lng=float(pt[1]), speed_kmh=22.0, route_id=rid, vid=301)
            writer.append_busmap_batch("sess-macro", rid, 0, obs_t, [dto])

        replayed = svc.sync_from_speed_view(now_epoch=now_ts + 200.0)
        assert replayed == 5
        hist = svc._speed_tracker._history.get((rid, 0, "29B45454"))
        assert hist is not None and len(hist) == 5
        assert (rid, 0, "29B45454") in svc._speed_tracker._ema
        assert svc._speed_tracker._last_win_dt[(rid, 0, "29B45454")] >= 120.0
    finally:
        reader.close()
        writer.close()


def test_p2_overnight_dead_off_hours_worker_reports_stale_at_noon(tmp_path):
    """P2: Worker that stopped with status='off_hours' 10h earlier reports status='stale' at noon."""
    db_path = tmp_path / "speed_view.db"
    noon_ts = datetime(2026, 11, 28, 12, 0, tzinfo=TZ_HANOI).timestamp()
    writer = SpeedViewStore(db_path, create_if_missing=True)
    try:
        writer.save_health("sess-night", 444, {"status": "off_hours", "cycle_count": 10}, noon_ts - 36000.0)
        health = writer.load_health(noon_ts, stale_after_sec=120.0)
        assert health["operating_hours"] is True
        assert health["status"] == "stale"
    finally:
        writer.close()


def test_p2_syncer_runs_periodic_sweep_stale_state(tmp_path):
    """P2: SpeedViewSyncer periodically invokes service.sweep_stale_state during sync loop."""
    import threading
    import time

    db_path = tmp_path / "speed_view.db"
    store = SpeedViewStore(db_path, create_if_missing=False)
    swept_event = threading.Event()
    sweep_epochs = []

    class _DummyService:
        def sync_from_speed_view(self):
            return 0

        def sweep_stale_state(self, now_epoch):
            sweep_epochs.append(now_epoch)
            swept_event.set()
            return 0

    syncer = SpeedViewSyncer(_DummyService(), store, poll_interval_sec=0.2, sweep_interval_sec=1.0)
    # Trigger sweep on the next sync tick without waiting 60s
    syncer._last_sweep_mono = time.monotonic() - 2.0
    syncer.start()
    try:
        assert swept_event.wait(timeout=3.0)
        assert len(sweep_epochs) >= 1
    finally:
        syncer.stop(timeout=0.5)
        store.close()


def test_p2_db_replacement_resets_stale_incidents_even_when_older_or_empty(tmp_path):
    """P2: Replacing DB A with DB B containing an older (or empty) incidents snapshot updates Serving."""
    db_path = tmp_path / "speed_view.db"
    now_ts = datetime(2026, 11, 28, 12, 0, tzinfo=TZ_HANOI).timestamp()
    writer_a = SpeedViewStore(db_path, create_if_missing=True)
    reader = SpeedViewStore(db_path, create_if_missing=False)
    svc = BusMapServingService(load_model=False, speed_view_store=reader)
    try:
        rid, _, _, _ = _pick_route_and_point(svc)
        pt = svc.get_route_shape(rid, 0).coordinates[1]
        v_a = _make_live_dto("29B-100.01", now_ts + 10.0, age_sec=1.0, lat=float(pt[0]), lng=float(pt[1]), route_id=rid, vid=401)
        writer_a.append_busmap_batch("sess-A", rid, 0, now_ts + 10.0, [v_a])
        writer_a.save_incidents(
            {"fetched_at": "2026-11-28T12:00:10+07:00", "count": 1, "incidents": [{"incident_id": "inc-A"}]},
            now_ts + 10.0,
        )
        assert svc.sync_from_speed_view(now_epoch=now_ts + 12.0) == 1
        assert [i["incident_id"] for i in svc._live_incidents_raw] == ["inc-A"]

        # Replace DB A with DB B having an earlier incident timestamp (t+9 < t+10)
        writer_a.close()
        reader.close()
        for ext in ("", "-wal", "-shm"):
            p = db_path.with_name(db_path.name + ext)
            if p.exists():
                p.unlink()

        writer_b = SpeedViewStore(db_path, create_if_missing=True)
        writer_b.append_busmap_batch("sess-B", rid, 0, now_ts + 20.0, [v_a])
        writer_b.save_incidents(
            {"fetched_at": "2026-11-28T12:00:09+07:00", "count": 1, "incidents": [{"incident_id": "inc-B"}]},
            now_ts + 9.0,
        )
        assert svc.sync_from_speed_view(now_epoch=now_ts + 25.0) == 1
        assert [i["incident_id"] for i in svc._live_incidents_raw] == ["inc-B"]

        # Replace DB B with DB C that has NO incident snapshot at all -> Serving clears stale DB B incidents
        writer_b.close()
        reader.close()
        for ext in ("", "-wal", "-shm"):
            p = db_path.with_name(db_path.name + ext)
            if p.exists():
                p.unlink()

        writer_c = SpeedViewStore(db_path, create_if_missing=True)
        writer_c.append_busmap_batch("sess-C", rid, 0, now_ts + 30.0, [v_a])
        assert svc.sync_from_speed_view(now_epoch=now_ts + 35.0) == 1
        assert svc._live_incidents_raw == []
        writer_c.close()
    finally:
        writer_a.close()
        reader.close()


def test_p2_reader_handles_legacy_schema_without_store_meta(tmp_path):
    """P2: External reader reads valid batches cleanly from an older speed_view.db missing store_meta."""
    import json

    db_path = tmp_path / "legacy_speed_view.db"
    now_ts = datetime(2026, 11, 28, 12, 0, tzinfo=TZ_HANOI).timestamp()

    # Build a legacy DB containing only the 4 original tables (no store_meta)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        PRAGMA journal_mode = WAL;
        CREATE TABLE speed_batches (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            writer_session_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            route_id INTEGER NOT NULL,
            dir_int INTEGER NOT NULL,
            observed_epoch REAL NOT NULL,
            payload_json TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE TABLE recent_timbus_focus (
            route_id INTEGER NOT NULL,
            dir_int INTEGER NOT NULL,
            plate_norm TEXT NOT NULL,
            tb_ts REAL NOT NULL,
            PRIMARY KEY (route_id, dir_int, plate_norm)
        );
        CREATE TABLE live_incidents_snapshot (
            singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
            payload_json TEXT NOT NULL,
            fetched_at TEXT,
            updated_epoch REAL NOT NULL
        );
        CREATE TABLE poller_health (
            singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
            writer_session_id TEXT NOT NULL,
            pid INTEGER NOT NULL,
            heartbeat_epoch REAL NOT NULL,
            snapshot_json TEXT NOT NULL
        );
        """
    )
    probe = BusMapServingService(load_model=False)
    rid, _, _, _ = _pick_route_and_point(probe)
    pt = probe.get_route_shape(rid, 0).coordinates[1]
    dto = _make_live_dto("29B-202.02", now_ts, age_sec=1.0, lat=float(pt[0]), lng=float(pt[1]), route_id=rid, vid=402)
    conn.execute(
        """
        INSERT INTO speed_batches (writer_session_id, kind, route_id, dir_int, observed_epoch, payload_json, created_at)
        VALUES (?, 'busmap_route', ?, 0, ?, ?, ?)
        """,
        ("legacy-sess", rid, now_ts, json.dumps([dto.model_dump(mode="json")]), now_ts),
    )
    conn.commit()
    conn.close()

    reader = SpeedViewStore(db_path, create_if_missing=False)
    svc = BusMapServingService(load_model=False, speed_view_store=reader)
    try:
        replayed = svc.sync_from_speed_view(now_epoch=now_ts + 5.0)
        assert replayed == 1
        assert svc._speed_view_last_seq == 1
        assert (rid, "29B20202") in svc._causal._states
    finally:
        reader.close()
