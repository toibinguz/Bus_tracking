"""Parity, dependency-boundary, and 1-way SQLite sync tests for PySpark Gold Baseline."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from modules.lakehouse.hdfs.gold_baseline_spark import (
    aggregate_route_baseline,
    build_reference_lookup,
    extract_partition_samples,
)
from modules.eta.baseline import (
    baseline_matrix_builder as local_builder,
)
from modules.eta.baseline.baseline_core import (
    GOLD_BASELINE_COLUMNS,
)
from modules.eta.serving.data_access import DataAccess
from modules.lakehouse.serving_sync import SERVING_TABLES, sync_gold_to_serving_db


def _build_fixture_db_and_reference(db_path: Path):
    stations = [
        (0, 100, "Origin", 0.0),
        (1, 101, "Stop A", 200.0),
        (2, 102, "Stop B", 500.0),
        (3, 103, "Stop C", 800.0),
        (4, 104, "Dest", 1000.0),
    ]
    shapes = [
        (0, 21.000, 105.800, 0.0),
        (1, 21.005, 105.800, 500.0),
        (2, 21.010, 105.800, 1000.0),
    ]
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE canonical_route_master (route_id INTEGER PRIMARY KEY, route_code TEXT NOT NULL, route_name TEXT NOT NULL)"
        )
        conn.execute("INSERT INTO canonical_route_master VALUES (2, '02', 'Route 02')")
        conn.execute(
            "CREATE TABLE canonical_shape_master (route_id INTEGER NOT NULL, route_code TEXT NOT NULL, direction TEXT NOT NULL, point_order INTEGER NOT NULL, lat REAL NOT NULL, lon REAL NOT NULL, cum_distance_m REAL NOT NULL, PRIMARY KEY (route_id, direction, point_order))"
        )
        for d in ("go", "re"):
            for pt_ord, lat, lon, cum_d in shapes:
                conn.execute(
                    "INSERT INTO canonical_shape_master VALUES (2, '02', ?, ?, ?, ?, ?)",
                    (d, pt_ord, lat, lon, cum_d),
                )
        conn.execute(
            "CREATE TABLE canonical_station_master (station_id INTEGER NOT NULL, route_id INTEGER NOT NULL, route_code TEXT NOT NULL, direction TEXT NOT NULL, station_order INTEGER NOT NULL, station_name TEXT NOT NULL, address TEXT, lat REAL NOT NULL, lon REAL NOT NULL, cum_distance_m REAL NOT NULL, snap_dist_m REAL NOT NULL, PRIMARY KEY (route_id, direction, station_order))"
        )
        for d in ("go", "re"):
            for st_ord, st_id, st_name, cum_d in stations:
                conn.execute(
                    "INSERT INTO canonical_station_master VALUES (?, 2, '02', ?, ?, ?, '', 21.0, 105.8, ?, 0.0)",
                    (st_id, d, st_ord, st_name, cum_d),
                )
        # Heavy tables that MUST NOT be copied by sync_gold_to_serving_db
        conn.execute("CREATE TABLE vehicle_unique_pings (id INTEGER)")
        conn.execute("CREATE TABLE route_projected_telemetry (id INTEGER)")
        conn.execute("CREATE TABLE fact_route_tomtom_incidents (id INTEGER)")

    reference = {
        "schema_version": "history-reference.v1",
        "routes": {"2": "02"},
        "stations": [
            {
                "route_id": 2,
                "route_code": "02",
                "direction": d,
                "station_id": st_id,
                "station_order": st_ord,
                "station_name": st_name,
                "cum_distance_m": cum_d,
            }
            for d in ("go", "re")
            for st_ord, st_id, st_name, cum_d in stations
        ],
        "shapes": {
            "2": {
                d: [list(pt) for pt in shapes]
                for d in ("go", "re")
            }
        },
    }
    return reference


def test_gold_baseline_spark_has_no_pandas_pyarrow_dependency():
    probe = """
import json, sys
import modules.lakehouse.hdfs.gold_baseline_spark
print(json.dumps({
    "pandas": "pandas" in sys.modules,
    "pyarrow": "pyarrow" in sys.modules,
}))
"""
    res = subprocess.run([sys.executable, "-c", probe], check=True, capture_output=True, text=True)
    assert json.loads(res.stdout) == {"pandas": False, "pyarrow": False}


def test_gold_baseline_spark_matches_local_builder_exactly(tmp_path, monkeypatch):
    db_path = tmp_path / "source.db"
    silver_dir = tmp_path / "silver" / "route_projected_telemetry"
    gold_dir = tmp_path / "gold" / "agg_segment_travel_times"
    reference = _build_fixture_db_and_reference(db_path)

    # Create weekday (2026-10-27), Saturday (2026-10-31), and test day (2026-11-01) Silver data
    silver_rows = []
    for day_str, vid_base in (("2026-10-27", 10), ("2026-10-31", 20), ("2026-11-01", 30)):
        day_dir = silver_dir / "route_code=02" / f"dt={day_str}"
        day_dir.mkdir(parents=True, exist_ok=True)
        day_records = []
        for trip_idx in range(3):
            vid = vid_base + trip_idx
            t0 = datetime.fromisoformat(f"{day_str}T08:{trip_idx * 10:02d}:00+07:00")
            for step_i, s_val in enumerate((150.0, 250.0, 450.0, 550.0, 750.0, 850.0)):
                ep = t0.timestamp() + step_i * 25.0
                rec = {
                    "route_code": "02",
                    "dt": day_str,
                    "vehicle_id": vid,
                    "device_epoch": ep,
                    "device_epoch_s": ep,
                    "direction": "go",
                    "s_bus_m": s_val,
                    "derived_speed_kmh": 20.0,
                }
                day_records.append(rec)
                silver_rows.append(rec)
        pd.DataFrame(
            [{k: r[k] for k in ("vehicle_id", "device_epoch", "direction", "s_bus_m", "derived_speed_kmh")} for r in day_records]
        ).to_parquet(day_dir / "part.parquet", index=False)

    monkeypatch.setattr(local_builder, "DB_PATH", str(db_path))
    monkeypatch.setattr(local_builder, "SILVER_TEL_DIR", str(silver_dir))
    monkeypatch.setattr(local_builder, "GOLD_BASELINE_DIR", str(gold_dir))
    local_builder.build_and_evaluate_baseline_matrix(fit_end_date="2026-10-31")

    with sqlite3.connect(db_path) as conn:
        expected_rows = conn.execute(
            f"SELECT {', '.join(GOLD_BASELINE_COLUMNS)} FROM agg_segment_travel_times "
            "ORDER BY route_code, direction, from_station_order, to_station_order, day_type, hour_slot"
        ).fetchall()

    # Run Spark helper pipeline on the exact same Silver rows
    shape_len_map, stations_map = build_reference_lookup(reference)
    fit_keyed = sorted(
        (
            ((r["route_code"], r["direction"], r["vehicle_id"], r["device_epoch_s"]), r)
            for r in silver_rows
            if r["dt"] <= "2026-10-31"
        ),
        key=lambda pair: pair[0],
    )
    extracted = list(extract_partition_samples(fit_keyed, shape_len_map, stations_map, "2026-10-31"))
    spark_rows = sorted(
        aggregate_route_baseline("02", [item for _, item in extracted], stations_map),
        key=lambda row: (row[0], row[1], row[2], row[3], row[9], row[10]),
    )

    assert len(spark_rows) == len(expected_rows) > 0
    assert spark_rows == expected_rows


def test_sync_gold_to_serving_db_produces_5_tables_and_loads_in_data_access(tmp_path):
    source_db = tmp_path / "source.db"
    output_db = tmp_path / "serving.db"
    gold_dir = tmp_path / "gold_data"
    gold_dir.mkdir(parents=True)
    reference = _build_fixture_db_and_reference(source_db)
    _, stations_map = build_reference_lookup(reference)
    rows = aggregate_route_baseline("02", [], stations_map)

    cols_data = {col: [r[idx] for r in rows] for idx, col in enumerate(GOLD_BASELINE_COLUMNS)}
    pq.write_table(pa.table(cols_data), gold_dir / "part-00000.parquet")

    summary = sync_gold_to_serving_db(
        source_db=source_db,
        output_db=output_db,
        gold_parquet_dir=gold_dir,
        fit_end_date="2026-10-23",
    )
    assert tuple(sorted(summary["tables"])) == tuple(sorted(SERVING_TABLES))
    assert summary["baseline_rows"] == len(rows)

    with sqlite3.connect(output_db) as conn:
        tables = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        }
        assert tables == set(SERVING_TABLES)
        assert conn.execute("SELECT fit_end_date FROM eta_baseline_manifest").fetchone()[0] == "2026-10-23"

    da = DataAccess(db_path=str(output_db))
    assert "02" in da.route_idx_by_code
    assert len(da.get_routes()) == 1
    assert da.get_route_shape(2, "go") is not None
    assert da.get_route_stations(2, "go") is not None
