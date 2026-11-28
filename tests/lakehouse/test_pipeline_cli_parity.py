"""Exercise the real CLIs. BUS_PIPELINE_TEST_PROJECT enables a disposable HDFS namespace."""
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
import sqlite3
import subprocess
import sys

import pyarrow.parquet as pq
import pytest

from modules.ingestion.gtfs import ingest_busmap_canonical as gtfs
from modules.lakehouse.hdfs.hf_bronze import descriptor
from modules.lakehouse.hdfs.reference_export import load_reference
from modules.lakehouse.pipeline.spec import digest, encoded


def command(*args, **kwargs):
    res = subprocess.run(args, capture_output=True, timeout=360, **kwargs)
    assert res.returncode == 0, res.stderr.decode(errors="replace")[-6000:]
    return res.stdout


@pytest.fixture(scope="module")
def sample(tmp_path_factory):
    root = tmp_path_factory.mktemp("raw-parity")
    db = root / "ref.db"
    gtfs.main(db)
    reference = load_reference(db)
    raw = root / "raw"
    for day in ("2026-10-21", "2026-10-22"):
        for category in ("bus", "incidents"):
            (raw / day / category).mkdir(parents=True)
    # Route 01 occurs only during fitting. Route 02 must keep index 1 in features.
    route_ids = {code: rid for rid, code in reference["routes"].items()}
    records = []
    for rc in ("01", "02"):
        rid = route_ids[rc]
        points = reference["shapes"][rid]["go"]
        selected = [points[0]]
        for pt in points[1:]:
            if pt[3] - selected[-1][3] >= 90:
                selected.append(pt)
        start = datetime.fromisoformat("2026-10-21T20:00:00+07:00" if rc == "01" else "2026-10-21T23:59:30+07:00")
        for i, (_, lat, lon, _) in enumerate(selected):
            stamp = (start + timedelta(seconds=i * 20)).isoformat()
            record = dict(route_id=int(rid), vehicle_id=100, plate="fixture-"+rc, lat=lat, lon=lon,
                          device_update_time=stamp, crawled_at=stamp, direction=0)
            records.append(record)
            with (raw / stamp[:10] / "bus" / "part.jsonl").open("ab") as f:
                f.write(encoded(record) + b"\n")
        if rc == "02":
            inc_pts = selected[8:18]
            incident = dict(incident_id="cross-midnight", timestamp="2026-10-21T23:59:55+07:00",
                            geometry_type="LineString",
                            coordinates=[[p[2], p[1]] for p in inc_pts],
                            length_meters=round(inc_pts[-1][3] - inc_pts[0][3], 1),
                            delay_seconds=200, magnitude_of_delay=2)
            (raw / "2026-10-21/incidents/capture.jsonl").write_bytes(encoded(incident) + b"\n")
    (raw / "2026-10-22/bus/retry.jsonl").write_bytes(encoded(records[0]) + b"\n{}\n")
    return root, raw, reference


@pytest.fixture(scope="module")
def local(sample):
    root, raw, _ = sample
    out = command(sys.executable, "scripts/run_local_batch_pipeline.py", "--raw-dir", str(raw),
                  "--workspace", str(root / "local"), "--export-features", "--dataset", "fixture",
                  "--train-to-day", "2026-10-22", "--feature-routes", "02", "--workers", "1").decode("utf-8", errors="replace")
    out = out.replace("\r\n", "\n")
    return json.loads(out[out.index('{\n  "mode"'):])


def test_local_pipeline(local):
    silver, baseline, features = local["silver"], local["gold_baseline"], local["causal_features"]
    assert silver["raw_bus_rows"] == silver["unique_bus_events"] + 2
    assert silver["rejected_bus_normalize"] == 1
    assert features["baseline_build_id"] == baseline["build_id"]
    assert features["row_count"] > 0
    assert features["routes"] == ["02"]
    table = pq.ParquetFile(Path(features["data_path"]) / "02.parquet").read()
    assert set(table["route_id_idx"].to_pylist()) == {1}
    assert max(table["inc_ahead_total_delay_sec"].to_pylist()) > 0
    with sqlite3.connect(local["serving_db_path"]) as db:
        assert db.execute("select source,snapshot_id,build_id from eta_baseline_manifest").fetchone() == (
            "local", silver["snapshot_id"], baseline["build_id"])


def parquet_rows(path, partitioned=False):
    rows = []
    for part in Path(path).rglob("*.parquet"):
        partition = {p.split("=",1)[0]: p.split("=",1)[1] for p in part.relative_to(path).parts[:-1] if "=" in p}
        for row in pq.ParquetFile(part).read().to_pylist():
            rows.append(dict(row, **partition) if partitioned else row)
    return rows


def test_fallback_and_rebatched_input(sample, local, monkeypatch):
    from core_cpp import native_bridge
    from modules.lakehouse.local_batch import run_local_batch_pipeline

    root, raw, _ = sample
    other = root / "rebatched"
    for category in ("bus", "incidents"):
        lines = [line for p in sorted(raw.glob(f"*/{category}/*.jsonl")) for line in p.read_bytes().splitlines()]
        folder = other / "2026-10-22" / category
        folder.mkdir(parents=True)
        for i in range(3):
            (folder / f"{i}.jsonl").write_bytes(b"".join(line+b"\n" for line in reversed(lines[i::3])))
    monkeypatch.setattr(native_bridge, "_LIB", None)
    monkeypatch.setattr(native_bridge, "_LOAD_TRIED", True)
    result = run_local_batch_pipeline(raw_dir=other, workspace=root / "fallback", export_features=True,
                                     train_to_day="2026-10-22", feature_routes=["02"], dataset="fixture", workers=1)
    for key, path, columns in (
        ("silver", "silver_path", ["event_id"]),
        ("gold_baseline", "gold_data_path", ["route_code","direction","from_station_order","to_station_order","day_type","hour_slot"]),
        ("causal_features", "data_path", ["route","vehicle","journey","target","as_of","direction_id"]),
    ):
        assert result[key]["engines"] == ["python"]
        compare_rows(local[key][path], result[key][path], columns)


def compare_rows(left_path, right_path, keys):
    sort_key = lambda row: tuple(row[k] for k in keys)
    left = sorted(parquet_rows(left_path, True), key=sort_key)
    right = sorted(parquet_rows(right_path, True), key=sort_key)
    assert len(left) == len(right) > 0
    for a, b in zip(left, right):
        assert a.keys() == b.keys()
        for key in a:
            if key in ("s_bus_m","cross_track_m"):
                assert a[key] == pytest.approx(b[key], abs=1e-5, rel=0)
            elif key.startswith("tt_"):
                assert a[key] == pytest.approx(b[key], abs=0.05, rel=0)
            else:
                assert a[key] == b[key], key


@pytest.mark.skipif(not os.environ.get("BUS_PIPELINE_TEST_PROJECT"), reason="requires dedicated Docker/HDFS test project")
def test_docker_pipeline_matches_local(sample, local):
    root, raw, reference = sample
    project = os.environ["BUS_PIPELINE_TEST_PROJECT"]
    assert project.startswith("bus-ssot-test-"), "use a disposable test cluster"
    nn = project + "-namenode-1"
    master = project + "-spark-master-1"
    ns = "/bus-eta/v1"
    staging = root / "v1"
    ref = encoded(reference)
    ref_path = f"reference/history/sha256={digest(ref)}/reference.json"
    batch_ids = []

    def put(name, content):
        path = staging / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    put(ref_path, ref)
    for path in raw.glob("*/*/*.jsonl"):
        content = path.read_bytes()
        desc = descriptor("fixture", "1"*40, "raw_data/"+path.relative_to(raw).as_posix(), content)
        batch_ids.append(desc["batch_id"])
        put(desc["hdfs_raw_path"][len(ns)+1:], content)
        put("_received/hf_batch/"+desc["batch_id"]+"/manifest.json", encoded(desc))
    command("docker", "cp", str(staging), nn+":/tmp/parity-input")
    command("docker", "exec", nn, "hdfs", "dfs", "-mkdir", "-p", "/bus-eta")
    # Deliberately require an empty namespace; never overwrite an existing cluster.
    command("docker", "exec", nn, "hdfs", "dfs", "-test", "-d", "/bus-eta")
    if subprocess.run(["docker", "exec", nn, "hdfs", "dfs", "-test", "-e", ns]).returncode == 0:
        pytest.fail("integration fixture requires a fresh disposable namespace")
    command("docker", "exec", nn, "hdfs", "dfs", "-put", "/tmp/parity-input", ns)
    command("docker", "exec", nn, "hdfs", "dfs", "-chmod", "777", ns)
    cmd = ["docker", "exec", "-e", "PYTHONPATH=/workspace", master, "/opt/spark/bin/spark-submit",
           "--master", "spark://spark-master:7077", "--driver-memory", "512m", "--executor-memory", "512m",
           "--total-executor-cores", "1", "--conf", "spark.executorEnv.PYTHONPATH=/workspace",
           "--conf", "spark.ui.enabled=false", "/workspace/scripts/hdfs_build_history_snapshot.py",
           "--reference", "hdfs://namenode:8020"+ns+"/"+ref_path, "--batch-id", *batch_ids,
           "--partitions", "2", "--export-features", "--to-day", "2026-10-22", "--feature-routes", "02"]
    res = subprocess.run(cmd, capture_output=True, timeout=360)
    assert res.returncode == 0, res.stderr.decode(errors="replace")[-9000:]
    results = dict(line.split("=",1) for line in res.stdout.decode().splitlines() if "_RESULT=" in line)
    def get(remote, name):
        command("docker", "exec", nn, "hdfs", "dfs", "-get", remote, "/tmp/"+name)
        command("docker", "cp", nn+":/tmp/"+name, str(root/name))
        return root/name

    for marker, label, path_key, keys in (
        ("U3_RESULT", "silver", "silver_path", ["event_id"]),
        ("GOLD_RESULT", "gold_baseline", "gold_data_path", ["route_code","direction","from_station_order","to_station_order","day_type","hour_slot"]),
        ("GOLD_FEATURES_RESULT", "causal_features", "data_path", ["route","vehicle","journey","target","as_of","direction_id"]),
    ):
        actual = json.loads(results[marker])
        expected = local[label]
        assert actual["engines"] == expected["engines"]
        assert actual["logic_version"] == expected["logic_version"]
        compare_rows(expected[path_key], get(actual[path_key], label), keys)


def test_new_pipeline_features_match_canonical_lakehouse_route02():
    from modules.ingestion.projection.tomtom_incident_projector import SILVER_INCIDENT_COLUMNS
    from modules.lakehouse.local_adapter import part_rows
    from modules.lakehouse.pipeline import features as pf, spec as pspec

    root = Path(__file__).resolve().parents[2]
    lake = root / "data" / "lakehouse"
    db_path = root / "data" / "serving_bus_system.db"
    orig_pq = lake / "gold" / "causal_features" / "features" / "02.parquet"
    silver_parts = [
        lake / "silver" / "route_projected_telemetry" / "route_code=02" / "dt=2026-11-12" / "part-2026-11-12.snappy.parquet",
        lake / "silver" / "route_projected_telemetry" / "route_code=02" / "dt=2026-11-13" / "part-2026-11-13.snappy.parquet",
    ]
    if not orig_pq.is_file() or not db_path.is_file() or not all(p.is_file() for p in silver_parts):
        pytest.skip("canonical real data/lakehouse + serving_bus_system.db not present")

    ref = load_reference(db_path)
    base_rows = list(part_rows(sorted((lake / "gold" / "agg_segment_travel_times").glob("*.parquet"))))
    catalog = sorted({r["route_code"] for r in base_rows})
    meta = pf.build_route_feature_metadata(ref, ["02"], base_rows, catalog)
    _, start, end = pf.incident_window("2026-11-12", "2026-11-13")
    by_dir = {0: [], 1: []}
    for rec in part_rows(sorted((lake / "silver" / "fact_route_tomtom_incidents" / "route_code=02").glob("*.parquet"))):
        rec["route_code"] = "02"
        fact = tuple(rec[c] for c in SILVER_INCIDENT_COLUMNS)
        for _, (d_int, iv) in pf.window_interval(fact, start, end):
            by_dir[d_int].append(iv)

    new_rows = list(pf.compute_route_features(
        "02", part_rows(silver_parts), by_dir, meta, fit_end_date="2026-10-21",
        validation_epoch=pspec.split_epoch("2026-11-13"), test_epoch=pspec.split_epoch("2026-11-13"), cadence_sec=120.0,
    ))
    cols = list(pf.GOLD_CAUSAL_FEATURE_COLUMNS)
    eta_idx = cols.index("eta_seconds")
    inc_idx = cols.index("inc_ahead_total_delay_sec")
    key_idx = (cols.index("vehicle"), cols.index("target"), cols.index("as_of"), cols.index("direction_id"))
    new_map = {tuple(r[k] for k in key_idx): r for r in new_rows}

    orig_table = pq.ParquetFile(orig_pq).read()
    orig_rows = [r for r in orig_table.to_pylist() if start <= r["as_of"] < end]
    assert len(new_rows) == len(orig_rows) > 1000
    assert sum(1 for r in new_rows if (r[inc_idx] or 0.0) > 0.0) == sum(1 for r in orig_rows if (r["inc_ahead_total_delay_sec"] or 0.0) > 0.0)
    for o in orig_rows:
        n = new_map[(o["vehicle"], o["target"], o["as_of"], o["direction_id"])]
        assert n[eta_idx] == pytest.approx(o["eta_seconds"], abs=1e-6, rel=0)
        assert n[inc_idx] == pytest.approx(o["inc_ahead_total_delay_sec"], abs=1e-6, rel=0)
