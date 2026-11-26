"""Unit tests for config/hardware_guard.py and projection optimizations (Part 2)."""

import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from config import hardware_guard as hg
from config.system_config import DEFAULT_DB_PATH, MAX_CORRIDOR_CROSS_TRACK_M
from module_1_data_ingestion_and_preprocessing.step_1_4_frenet_spatial_projection.projection_boundary import (
    ProjectableEvent,
    project_route_events,
)
from module_1_data_ingestion_and_preprocessing.step_1_4_frenet_spatial_projection.route_matcher import (
    Match,
    RouteHMM,
    ShapeProjectionModel,
)


def test_hardware_guard_caps_workers_on_low_ram(monkeypatch):
    monkeypatch.setattr(
        hg,
        "inspect_hardware",
        lambda path=".": {
            "cpu_physical": 8,
            "cpu_logical": 12,
            "ram_total_gb": 16.0,
            "ram_avail_gb": 3.5,
            "disk_free_gb": 50.0,
            "gpu": None,
        },
    )
    capped = hg.recommend_workers(6, per_worker_ram_gb=0.9, min_free_ram_gb=2.0, max_cpu_frac=0.6)
    # ram_budget = 1.5 GB -> int(1.5 // 0.9) = 1
    assert capped == 1

    capped2 = hg.recommend_workers(6, per_worker_ram_gb=0.5, min_free_ram_gb=1.5, max_cpu_frac=0.5)
    # cpu_cap = 4, ram_budget = 2.0 -> 4
    assert capped2 == 4


def test_hardware_guard_aborts_below_critical_ram(monkeypatch):
    fake_psutil = SimpleNamespace(virtual_memory=lambda: SimpleNamespace(available=int(0.6 * 1e9)))
    monkeypatch.setattr(hg, "psutil", fake_psutil)
    with pytest.raises(MemoryError, match="HW-ABORT"):
        hg.check_memory_pressure(min_free_ram_gb=1.5, abort_ram_gb=0.85, label="test_oom")


def test_hardware_guard_gpu_low_vram_recommends_cpu(monkeypatch):
    monkeypatch.setattr(
        hg,
        "_query_gpu",
        lambda: {"name": "RTX 3050", "vram_total_mb": 6144, "vram_free_mb": 1200, "temp_c": 52},
    )
    res = hg.check_gpu_thermal_and_vram(min_free_vram_mb=2200)
    assert res["use_cuda"] is False
    assert "low_vram" in res["reason"]
    assert res["overheated"] is False


def test_route_hmm_candidates_bbox_matches_bruteforce_route01():
    db_path = ROOT / DEFAULT_DB_PATH
    if not db_path.is_file():
        pytest.skip("canonical SQLite catalog not present")
    with sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True) as conn:
        pts = conn.execute(
            """
            SELECT s.point_order, s.lat, s.lon, s.cum_distance_m
            FROM canonical_shape_master s
            JOIN canonical_route_master r ON r.route_id = s.route_id
            WHERE r.route_code = '01' AND s.direction = 'go'
            ORDER BY s.point_order
            """
        ).fetchall()
    if len(pts) < 10:
        pytest.skip("route 01 go shape missing")

    sh = ShapeProjectionModel.build(pts)
    hmm = RouteHMM(sh)
    rng = np.random.default_rng(42)

    sample_idx = np.linspace(0, len(pts) - 1, 250, dtype=int)
    for k, idx in enumerate(sample_idx):
        _, lat0, lon0, _ = pts[int(idx)]
        lat = float(lat0 + rng.normal(0.0, 0.00018))
        lng = float(lon0 + rng.normal(0.0, 0.00018))
        epoch = 1760000000.0 + k * 15.0

        fast = hmm.candidates(epoch, lat, lng, k)

        # Brute-force reference
        px = lng * sh.kx
        py = lat * sh.ky
        u = np.clip(((px - sh._x1) * sh._dx + (py - sh._y1) * sh._dy) / sh._safe_lens_sq, 0.0, 1.0)
        d = np.hypot(px - sh._x1 - u * sh._dx, py - sh._y1 - u * sh._dy)
        s = sh._cum_starts + u * sh._seg_lens
        brute = []
        for i in np.argsort(d, kind="mergesort"):
            if d[i] > MAX_CORRIDOR_CROSS_TRACK_M:
                break
            if any(abs(s[i] - p.s) < 10 for p in brute):
                continue
            brute.append(Match(epoch, round(float(s[i]), 1), round(float(d[i]), 1), int(i), k))
            if len(brute) >= hmm.max_candidates:
                break

        assert fast == brute


def test_project_route_events_multivehicle_multidir_preserving():
    shape_go = [
        (0, 21.0000, 105.8000, 0.0),
        (1, 21.0000, 105.8050, 520.0),
        (2, 21.0000, 105.8100, 1040.0),
    ]
    shape_re = [
        (0, 21.0000, 105.8100, 0.0),
        (1, 21.0000, 105.8050, 520.0),
        (2, 21.0000, 105.8000, 1040.0),
    ]
    events = [
        ProjectableEvent("e1", 1, 1, "01", 101, "29B001", "2026-11-18 08:00:00", 1000.0, "go", None, 21.0000, 105.8010),
        ProjectableEvent("e2", 2, 1, "01", 101, "29B001", "2026-11-18 08:00:30", 1030.0, "go", None, 21.0000, 105.8040),
        ProjectableEvent("e3", 3, 1, "01", 102, "29B002", "2026-11-18 08:00:10", 1010.0, "re", None, 21.0000, 105.8090),
        ProjectableEvent("e4", 4, 1, "01", 102, "29B002", "2026-11-18 08:00:40", 1040.0, "re", None, 21.0000, 105.8060),
    ]
    projected, diag = project_route_events(events, {"go": shape_go, "re": shape_re}, {})
    assert diag == {}
    assert [p.event_id for p in projected] == ["e1", "e2", "e3", "e4"]
    assert projected[1].derived_speed_kmh is not None and projected[1].derived_speed_kmh > 20.0
    assert projected[3].derived_speed_kmh is not None and projected[3].derived_speed_kmh > 20.0


def test_causal_features_speed_handles_missing_observation_epoch():
    from module_3_bus_eta_prediction.step_3_2_feature_store_extractor.causal_eta import CausalFeatures

    fake_state = SimpleNamespace(
        started=1000.0,
        observations={
            1180.0: SimpleNamespace(source="busmap"),
        },
        matcher=SimpleNamespace(
            best_path=[
                Match(1000.0, 100.0, 2.0, 0, 0),
                Match(1090.0, 500.0, 2.0, 1, 1),
                Match(1180.0, 900.0, 2.0, 2, 2),
            ]
        ),
    )
    assert CausalFeatures.speed(fake_state, 180) is None

