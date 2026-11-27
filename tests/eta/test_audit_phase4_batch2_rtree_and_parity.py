"""Phase B regression & R-Tree benchmark tests (STRtree parity, multi-run split, <20m slice, direction & per-route lock)."""

from datetime import datetime
import sqlite3
import threading
from types import SimpleNamespace

import numpy as np

from config.system_config import DEFAULT_DB_PATH, TZ_HANOI
from modules.ingestion.sanitizer.telemetry_sanitizer import (
    sanitize_and_validate_telemetry,
)
from modules.ingestion.projection.route_matcher import (
    ShapeProjectionModel,
)
from modules.eta.features.causal_eta import (
    CausalFeatures,
    RouteIncidentInterval,
)
from modules.eta.serving.serving_service import (
    BusMapServingService,
)


def test_rtree_batch_matches_single_point_exact_on_real_route01():
    """R-Tree STRtree project_directed_points_batch cho kết quả 100% giống project_directed_point trên tuyến 01 thật."""
    con = sqlite3.connect(f"file:{DEFAULT_DB_PATH}?mode=ro", uri=True)
    pts = con.execute(
        """
        SELECT point_order, lat, lon, cum_distance_m
        FROM canonical_shape_master
        WHERE route_code = '01' AND direction = 'go'
        ORDER BY point_order
        """
    ).fetchall()
    con.close()
    assert len(pts) >= 50
    shape = ShapeProjectionModel.build(pts)

    rng = np.random.default_rng(42)
    sample_idx = rng.integers(0, len(shape._x1), size=400)
    lats = np.array([pts[i][1] + float(rng.normal(0.0, 0.00012)) for i in sample_idx])
    lons = np.array([pts[i][2] + float(rng.normal(0.0, 0.00012)) for i in sample_idx])
    uxs = shape._unit_dx[sample_idx]
    uys = shape._unit_dy[sample_idx]

    batch_out = shape.project_directed_points_batch(lats, lons, uxs, uys, min_cos_theta=0.5, max_d_perp_m=35.0)
    brute_out = []
    for idx in range(len(lats)):
        res = shape.project_directed_point(float(lats[idx]), float(lons[idx]), float(uxs[idx]), float(uys[idx]), 0.5, 35.0)
        if res is not None:
            brute_out.append((idx, res[0], res[1], res[2]))

    assert len(batch_out) > 200
    assert batch_out == brute_out


def test_live_incidents_preserve_disjoint_runs_instead_of_collapsing():
    """AUD-P1-03: Hai đoạn run tách rời trên cùng tuyến chữ U phải xuất thành 2 RouteIncidentDTO riêng biệt."""
    # Tuyến hình chữ U đi lên bắc 0..1000m (lat 0->1, lon 0), rẽ ngang 200m (lon 0->0.2), đi xuống nam (lat 1->0, lon 0.2)
    shape_pts = [
        (0, 0.0, 0.0, 0.0),
        (1, 0.5, 0.0, 55270.0),
        (2, 1.0, 0.0, 110540.0),
        (3, 1.0, 0.01, 111600.0),
        (4, 0.0, 0.01, 222140.0),
    ]
    shape = ShapeProjectionModel.build(shape_pts)

    svc = BusMapServingService.__new__(BusMapServingService)
    svc._incident_lock = threading.Lock()
    svc._live_incidents_gen = 1
    svc._live_incidents_fetched_at = "2026-11-26T10:00:00+07:00"
    svc._live_incidents_epoch = 1000.0
    svc._live_incidents_by_route = {}
    svc._get_shape_model = lambda rid, dstr: shape

    # 2 đoạn rời nhau cách xa trên đoạn đi lên Bắc (s ~ 11km và s ~ 77km)
    svc._live_incidents_raw = [
        {
            "incident_id": "inc_u",
            "description": "Đoạn A & B",
            "icon_category": 6,
            "magnitude_of_delay": 2,
            "delay_seconds": 180.0,
            "length_meters": 5000.0,
            "geometry_type": "MultiLineString",
            "coordinates": [
                [[0.0, 0.10], [0.0, 0.11]],
                [[0.0, 0.70], [0.0, 0.71]],
            ],
        }
    ]
    dtos, _ = svc.get_live_incidents_for_route(1, 0, now_epoch=1100.0)
    assert len(dtos) == 2
    assert dtos[0].s_max_m < dtos[1].s_min_m


def test_incident_slice_under_20m_retains_full_delay_when_ahead():
    """AUD-P1-03: Bỏ ngưỡng floor 20.0m ở CausalFeatures._incident_features để đoạn <20m không mất delay."""
    engine = CausalFeatures(SimpleNamespace())
    engine.observe_incidents(
        1,
        0,
        [RouteIncidentInterval(s_min_m=500.0, s_max_m=510.0, delay_seconds=100.0, crawled_epoch=900.0, expires_epoch=1800.0)],
    )
    delay, near, jam, age = engine._incident_features(1, 0, s_cur=100.0, s_target=1000.0, now=1000.0)
    assert delay == 100.0
    assert near == 400.0
    assert jam == 10.0
    assert age == 100.0


def test_telemetry_sanitizer_direction_0_not_depot_and_per_route_lock():
    """AUD-P0-02 & AUD-P1-07: direction=0 speed=0 là ACTIVE_VALID; direction=-1 speed=0 là IDLE_DEPOT; per-route lock."""
    raw_go_stopped = {
        "Lat": 105.85,
        "Lng": 21.02,
        "Speed": 0.0,
        "direction": 0,
        "RouteId": 2,
        "lastUpdateTime": "2026-11-26T10:00:00+07:00",
    }
    res_go = sanitize_and_validate_telemetry(raw_go_stopped, vid=10, target_route_ids={2}, kinematic_cache={})
    assert res_go["quality_status"] == "ACTIVE_VALID"

    raw_depot = {
        "Lat": 105.85,
        "Lng": 21.02,
        "Speed": 0.0,
        "direction": -1,
        "RouteId": 2,
        "lastUpdateTime": "2026-11-26T10:00:00+07:00",
    }
    res_depot = sanitize_and_validate_telemetry(raw_depot, vid=11, target_route_ids={2}, kinematic_cache={})
    assert res_depot["quality_status"] == "IDLE_DEPOT"

    svc = BusMapServingService.__new__(BusMapServingService)
    svc._causal_lock = threading.Lock()
    svc._causal_locks = {}
    svc._causal_locks_guard = threading.Lock()
    assert svc._get_causal_lock(1) is svc._get_causal_lock(1)
    assert svc._get_causal_lock(1) is not svc._get_causal_lock(2)
