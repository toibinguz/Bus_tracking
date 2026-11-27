"""1-to-1 C++17 native kernel vs Python SSOT parity verification across all 3 batch stages."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
import sqlite3

import numpy as np
import pytest

from config.system_config import TZ_HANOI
from core_cpp.native_bridge import (
    build_route_baseline_native,
    extract_route_causal_features_native,
    is_native_available,
    project_route_pings_native,
)
from modules.ingestion.projection.projection_boundary import (
    ProjectableEvent,
    project_route_events,
)
from modules.eta.baseline.baseline_core import (
    build_route_baseline_rows,
    extract_fit_segment_samples,
)
from modules.eta.features.causal_eta import (
    FEATURES,
    CausalFeatures,
    Observation,
)
from modules.eta.training.causal_eta_training import (
    TrainingReplay,
    baseline_cutoff_epoch,
)
from modules.eta.training.silver_replay_trainer import (
    load_incident_timeline,
    replay_silver,
    select_partitions,
    silver_rows,
)
from modules.eta.serving.data_access import DataAccess


def test_native_kernel_is_loaded():
    assert is_native_available(), "Expected compiled C++17 bus_native_core binary to load cleanly"


def test_cpp_vs_python_silver_projection_parity():
    shapes = {
        "go": [(0, 21.0000, 105.8000, 0.0), (1, 21.0045, 105.8000, 500.0), (2, 21.0090, 105.8000, 1000.0)],
        "re": [],
    }
    st_dir = {(2, 10): "go", (2, 11): "go"}
    pings = [
        (1, 501, "29B-001", "2026-10-18T08:00:00+07:00", 1760749200.0, 0, 21.0005, 105.8000, 10),
        (2, 501, "29B-001", "2026-10-18T08:00:30+07:00", 1760749230.0, 0, 21.0020, 105.8000, 10),
        (3, 501, "29B-001", "2026-10-18T08:01:00+07:00", 1760749260.0, 0, 21.0040, 105.8000, 11),
        (4, 501, "29B-001", "2026-10-18T08:01:30+07:00", 1760749290.0, 0, 21.0065, 105.8000, 11),
        (5, 501, "29B-001", "2026-10-18T08:02:00+07:00", 1760749320.0, 0, 21.0085, 105.8000, 11),
    ]
    cpp_rows = project_route_pings_native(2, "02", pings, shapes, st_dir)
    assert cpp_rows is not None and len(cpp_rows) == 5

    py_events = [
        ProjectableEvent(
            event_id=f"ev-{r[0]}",
            legacy_ping_id=r[0],
            route_id=2,
            route_code="02",
            vehicle_id=r[1],
            plate=r[2],
            device_update_time=r[3],
            device_epoch_s=r[4],
            direction_hint="go",
            current_station_id=r[8],
            lat=r[6],
            lon=r[7],
        )
        for r in pings
    ]
    py_rows, _ = project_route_events(py_events, shapes, st_dir)
    assert len(py_rows) == len(cpp_rows)
    for c_row, p_row in zip(cpp_rows, py_rows):
        assert c_row[7] == p_row.direction
        assert c_row[10] == pytest.approx(p_row.s_bus_m, abs=1e-6)
        assert c_row[11] == pytest.approx(p_row.cross_track_m, abs=1e-6)
        if p_row.derived_speed_kmh is None:
            assert c_row[12] is None
        else:
            assert c_row[12] == pytest.approx(p_row.derived_speed_kmh, abs=1e-6)


def test_cpp_vs_python_gold_baseline_parity():
    stations_go = [(0, 10, "S0", 0.0), (1, 11, "S1", 250.0), (2, 12, "S2", 550.0), (3, 13, "S3", 850.0), (4, 14, "S4", 1100.0)]
    base_ep = datetime(2026, 10, 15, 8, 0, tzinfo=TZ_HANOI).timestamp()
    pings_py = []
    veh_ids, dir_ints, epochs, s_vals = [], [], [], []
    for trip in range(12):
        t0 = base_ep + trip * 1800.0
        for step in range(9):
            ep = t0 + step * 25.0
            s = 100.0 + step * 110.0
            dt_str = datetime.fromtimestamp(ep, tz=TZ_HANOI).strftime("%Y-%m-%d")
            pings_py.append((dt_str, ep, s, 15.8))
            veh_ids.append(100)
            dir_ints.append(0)
            epochs.append(ep)
            s_vals.append(s)

    samples = extract_fit_segment_samples(pings_py, 1100.0, stations_go, "2026-10-21")
    py_rows, _ = build_route_baseline_rows("02", {"go": stations_go, "re": []}, {"go": samples, "re": []})

    cpp_cells = build_route_baseline_native(
        1100.0,
        stations_go,
        0.0,
        [],
        np.array(veh_ids, dtype=np.int32),
        np.array(dir_ints, dtype=np.int32),
        np.array(epochs, dtype=np.float64),
        np.array(s_vals, dtype=np.float64),
        fit_end_date="2026-10-21",
        train_end_date="2026-11-12",
    )
    assert cpp_cells is not None and len(cpp_cells) == len(py_rows)
    py_map = {(r[1], r[2], r[3], r[9], r[10]): r for r in py_rows}
    for c in cpp_cells:
        key = (c["direction"], c["from_station_order"], c["to_station_order"], c["day_type"], c["hour_slot"])
        pr = py_map[key]
        assert c["sample_count"] == pr[11]
        assert c["quality_tier"] == pr[12]
        assert c["tt_p10_sec"] == pytest.approx(pr[13], abs=0.05)
        assert c["tt_p50_sec"] == pytest.approx(pr[14], abs=0.05)
        assert c["tt_p90_sec"] == pytest.approx(pr[15], abs=0.05)
        assert c["tt_mean_sec"] == pytest.approx(pr[16], abs=0.05)
        assert c["tt_std_sec"] == pytest.approx(pr[17], abs=0.05)


def test_cpp_vs_python_causal_features_parity_on_real_route02():
    root = Path(__file__).resolve().parents[2]
    silver_dir = root / "data" / "lakehouse" / "silver" / "route_projected_telemetry"
    inc_dir = root / "data" / "lakehouse" / "silver" / "fact_route_tomtom_incidents"
    db_path = root / "data" / "serving_bus_system.db"
    if not (silver_dir / "route_code=02").is_dir() or not db_path.is_file():
        pytest.skip("real canonical data/lakehouse + serving_bus_system.db not present")

    data = DataAccess(db_path=str(db_path))
    partitions = select_partitions(silver_dir, date(2026, 11, 12), date(2026, 11, 13), ["02"])
    inc_timeline = load_incident_timeline(inc_dir, data, route_codes=["02"])
    cutoff = baseline_cutoff_epoch("2026-10-21")
    val_ep = datetime(2026, 11, 13, tzinfo=TZ_HANOI).timestamp()
    test_ep = val_ep

    replay = TrainingReplay(CausalFeatures(data))
    replay_silver(replay, partitions, cutoff, 120.0, inc_timeline)
    py_rows = list(replay.labeled(val_ep, test_ep))
    assert len(py_rows) > 100

    route_id = data.resolve_route_id("02")
    route_idx = data.get_route_idx(route_id)
    obs_all = [
        (float(o.epoch), int(o.direction), o.vehicle, float(o.s_bus_m), o.lat, o.lng)
        for day in sorted(partitions)
        for o in silver_rows(partitions[day])
        if o.s_bus_m is not None
    ]
    obs_all.sort(key=lambda x: (x[0], x[1], x[2], x[4], x[5]))
    corridors_by_dir = {d: data.get_corridor_stations(route_id, ("go", "re")[d]) for d in (0, 1)}
    rlen_d, bspd_d, spac_d = {}, {}, {}
    for d in (0, 1):
        bspd, spac, rlen = data.get_route_profile(route_id, ("go", "re")[d])
        bspd_d[d] = bspd
        spac_d[d] = spac
        rlen_d[d] = rlen
    inc_by_dir = {
        d: [(iv.s_min_m, iv.s_max_m, iv.delay_seconds, iv.crawled_epoch, iv.expires_epoch) for iv in inc_timeline.get((route_id, d), ())]
        for d in (0, 1)
    }
    veh_names = sorted({x[2] for x in obs_all})
    vmap = {n: i for i, n in enumerate(veh_names)}
    arrs, _ = extract_route_causal_features_native(
        route_id_idx=route_idx,
        route_len_by_dir=rlen_d,
        route_base_speed_by_dir=bspd_d,
        route_spacing_by_dir=spac_d,
        corridors_by_dir=corridors_by_dir,
        baseline_lookup=data,
        route_id_for_lookup=route_id,
        incidents_by_dir=inc_by_dir,
        n_vehicles=len(veh_names),
        obs_epoch=np.array([x[0] for x in obs_all], dtype=np.float64),
        obs_dir=np.array([x[1] for x in obs_all], dtype=np.int32),
        obs_veh_idx=np.array([vmap[x[2]] for x in obs_all], dtype=np.int32),
        obs_s_bus=np.array([x[3] for x in obs_all], dtype=np.float64),
        baseline_cutoff_epoch=cutoff,
        validation_epoch=val_ep,
        test_epoch=test_ep,
        cadence_sec=120.0,
    )
    split_names = ("train", "validation", "test")
    cpp_rows_all = [
        (
            int(arrs["features"][i, 1]),
            float(arrs["as_of"][i]),
            veh_names[int(arrs["veh_idx"][i])],
            int(arrs["target"][i]),
            split_names[int(arrs["split"][i])],
            float(arrs["eta_seconds"][i]),
            arrs["features"][i],
        )
        for i in range(len(arrs["eta_seconds"]))
    ]

    assert len(cpp_rows_all) == len(py_rows)
    py_keyed = {
        (int(r["features"]["direction_id"]), float(r["as_of"]), r["vehicle"], int(r["target"])): r
        for r in py_rows
    }
    assert len(py_keyed) == len(py_rows)

    for d_int, as_of, veh, tgt, spl, eta, c_feats in cpp_rows_all:
        pr = py_keyed[(d_int, as_of, veh, tgt)]
        assert spl == pr["split"]
        assert eta == pytest.approx(pr["eta_seconds"], abs=1e-4)
        p_feats = np.array(
            [np.nan if pr["features"][f] is None else float(pr["features"][f]) for f in FEATURES],
            dtype=np.float32,
        )
        np.testing.assert_array_equal(np.isnan(c_feats), np.isnan(p_feats))
        valid_mask = ~np.isnan(p_feats)
        np.testing.assert_allclose(c_feats[valid_mask], p_feats[valid_mask], rtol=1e-5, atol=1e-3)
