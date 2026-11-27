"""Unit tests for TomTom incident projector -> Silver Parquet (no SQLite writes)."""

from __future__ import annotations

from pathlib import Path
import sqlite3

import pyarrow.parquet as pq

from modules.ingestion.projection.tomtom_incident_projector import (
    main as tomtom_main,
    project_incidents_to_route_facts,
    write_silver_incidents_parquet,
)


def test_tomtom_projector_writes_silver_parquet_without_modifying_sqlite(tmp_path):
    db_path = tmp_path / "serving.db"
    lake_dir = tmp_path / "lakehouse"
    inc_out = lake_dir / "silver" / "fact_route_tomtom_incidents"
    raw_dir = tmp_path / "raw" / "2026-10-18" / "incidents"
    raw_dir.mkdir(parents=True)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE canonical_route_master (route_id INTEGER PRIMARY KEY, route_code TEXT NOT NULL, route_name TEXT NOT NULL)"
        )
        conn.execute("INSERT INTO canonical_route_master VALUES (2, '02', 'Route 02')")
        conn.execute(
            "CREATE TABLE canonical_shape_master (route_id INTEGER NOT NULL, route_code TEXT NOT NULL, direction TEXT NOT NULL, point_order INTEGER NOT NULL, lat REAL NOT NULL, lon REAL NOT NULL, cum_distance_m REAL NOT NULL)"
        )
        conn.executemany(
            "INSERT INTO canonical_shape_master VALUES (2, '02', 'go', ?, ?, 105.8000, ?)",
            [(0, 21.0000, 0.0), (1, 21.0045, 500.0), (2, 21.0090, 1000.0)],
        )
        conn.execute(
            "CREATE TABLE canonical_station_master (station_id INTEGER NOT NULL, route_id INTEGER NOT NULL, route_code TEXT NOT NULL, direction TEXT NOT NULL, station_order INTEGER NOT NULL, station_name TEXT NOT NULL, cum_distance_m REAL NOT NULL)"
        )
        conn.executemany(
            "INSERT INTO canonical_station_master VALUES (?, 2, '02', 'go', ?, ?, ?)",
            [(10, 0, "S0", 0.0), (11, 1, "S1", 500.0), (12, 2, "S2", 1000.0)],
        )
    conn.close()

    inc_file = raw_dir / "batch_080000.jsonl"
    inc_file.write_text(
        '{"incident_id":"inc-1","timestamp":"2026-10-18T08:00:00+07:00","icon_category":6,"magnitude_of_delay":3,"delay_seconds":180,"length_meters":300.0,"description":"Slow traffic","coordinates":[[105.8000,21.0010],[105.8000,21.0035]]}\n',
        encoding="utf-8",
    )

    stats = tomtom_main(
        [
            "--db-path",
            str(db_path),
            "--incidents-glob",
            str(tmp_path / "raw" / "*" / "incidents" / "*.jsonl"),
            "--output-dir",
            str(inc_out),
        ]
    )
    assert stats["fact_rows"] > 0
    assert (inc_out / "route_code=02" / "part-00000.snappy.parquet").is_file()

    # Verify SQLite remained 3 static tables only (never created fact_route_tomtom_incidents)
    with sqlite3.connect(db_path) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert "fact_route_tomtom_incidents" not in tables

    # Verify generated Silver Parquet contains all projected incident rows
    table = pq.read_table(inc_out / "route_code=02" / "part-00000.snappy.parquet")
    assert table.num_rows == stats["fact_rows"]


def test_tomtom_projection_is_deterministic_across_input_orders():
    route_shapes = {"02": {"go": [(0, 21.0000, 105.8000, 0.0), (1, 21.0045, 105.8000, 500.0), (2, 21.0090, 105.8000, 1000.0)], "re": []}}
    route_stations = {"02": {"go": [(0, "S0", 0.0), (1, "S1", 500.0), (2, "S2", 1000.0)], "re": []}}
    records = [
        {"incident_id": "inc-1", "timestamp": "2026-10-18T08:00:00+07:00", "icon_category": 6, "magnitude_of_delay": 3, "delay_seconds": 180, "length_meters": 300.0, "description": "Slow", "coordinates": [[105.8000, 21.0010], [105.8000, 21.0035]]},
        {"incident_id": "inc-1", "timestamp": "2026-10-18T08:10:00+07:00", "icon_category": 6, "magnitude_of_delay": 3, "delay_seconds": 180, "length_meters": 450.0, "description": "Slow", "coordinates": [[105.8000, 21.0010], [105.8000, 21.0055]]},
    ]
    rows_fwd, _ = project_incidents_to_route_facts(records, route_shapes, route_stations)
    rows_rev, _ = project_incidents_to_route_facts(list(reversed(records)), route_shapes, route_stations)
    assert rows_fwd == rows_rev and len(rows_fwd) > 0
