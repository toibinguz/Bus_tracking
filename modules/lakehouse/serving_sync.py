"""1-way sync: static GTFS tables + HDFS/local Gold Baseline -> lightweight 5-table SQLite serving DB."""

from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from config.system_config import BASELINE_FIT_END_DATE, DEFAULT_DB_PATH, TEST_SPLIT_START_DATE, TRAIN_SPLIT_END_DATE
from modules.lakehouse.hdfs.hf_bronze import DockerHdfs
from modules.eta.baseline.baseline_core import (
    GOLD_BASELINE_COLUMNS,
)

STATIC_GTFS_TABLES = (
    "canonical_route_master",
    "canonical_shape_master",
    "canonical_station_master",
)
SERVING_TABLES = STATIC_GTFS_TABLES + (
    "agg_segment_travel_times",
    "eta_baseline_manifest",
)
HDFS_GOLD_ROOT = "/bus-eta/v1/gold/agg_segment_travel_times"

AGG_BASELINE_DDL = """
CREATE TABLE agg_segment_travel_times (
    route_code TEXT NOT NULL,
    direction TEXT NOT NULL,
    from_station_order INTEGER NOT NULL,
    to_station_order INTEGER NOT NULL,
    from_station_id INTEGER NOT NULL,
    to_station_id INTEGER NOT NULL,
    from_station_name TEXT,
    to_station_name TEXT,
    segment_length_m REAL NOT NULL,
    day_type INTEGER NOT NULL,
    hour_slot INTEGER NOT NULL,
    sample_count INTEGER NOT NULL,
    quality_tier INTEGER NOT NULL,
    tt_p10_sec REAL NOT NULL,
    tt_p50_sec REAL NOT NULL,
    tt_p90_sec REAL NOT NULL,
    tt_mean_sec REAL NOT NULL,
    tt_std_sec REAL NOT NULL,
    PRIMARY KEY (route_code, direction, from_station_order, to_station_order, day_type, hour_slot)
)
"""


def _read_gold_from_hdfs(snapshot_id: str, compose_file: Path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    if len(snapshot_id) != 64 or any(c not in "0123456789abcdef" for c in snapshot_id):
        raise ValueError("invalid snapshot ID")
    hdfs = DockerHdfs(compose_file)
    gold_root = f"{HDFS_GOLD_ROOT}/snapshot={snapshot_id}"
    manifest = json.loads(hdfs.read(f"{gold_root}/manifest.json"))
    if manifest.get("snapshot_id") != snapshot_id:
        raise ValueError("Gold manifest snapshot mismatch")

    listing = hdfs.call("-ls", f"{gold_root}/data").decode("utf-8", errors="replace")
    parts = sorted(
        line.split()[-1]
        for line in listing.splitlines()
        if line.split() and line.split()[-1].endswith(".parquet")
    )
    if not parts:
        raise ValueError("no Gold Parquet parts found in HDFS: " + gold_root)

    tables = [pq.read_table(io.BytesIO(hdfs.read(part))) for part in parts]
    combined = pa.concat_tables(tables)
    if combined.num_rows != int(manifest["row_count"]):
        raise ValueError(
            f"Gold row count mismatch: expected {manifest['row_count']}, got {combined.num_rows}"
        )
    return combined, manifest


def _read_gold_from_local(gold_dir: Path, fit_end_date: str):
    import pyarrow.dataset as ds

    if not gold_dir.exists():
        raise FileNotFoundError(f"Gold Parquet directory not found: {gold_dir}")
    table = ds.dataset(gold_dir, format="parquet").to_table()
    manifest_file = gold_dir.parent / "manifest.json"
    if manifest_file.is_file():
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    else:
        manifest = {
            "fit_end_date": fit_end_date,
            "train_end_date": TRAIN_SPLIT_END_DATE,
            "test_start_date": TEST_SPLIT_START_DATE,
        }
    return table, manifest


def sync_gold_to_serving_db(
    *,
    source_db: Path,
    output_db: Path,
    snapshot_id: str | None = None,
    gold_parquet_dir: Path | None = None,
    fit_end_date: str = BASELINE_FIT_END_DATE,
    compose_file: Path = ROOT / "docker-compose.hdfs.yml",
) -> dict:
    if bool(snapshot_id) == bool(gold_parquet_dir):
        raise ValueError("specify exactly one of snapshot_id or gold_parquet_dir")

    source_db = Path(source_db).resolve()
    output_db = Path(output_db).resolve()
    if not source_db.is_file():
        raise FileNotFoundError(f"Source DB not found: {source_db}")

    if snapshot_id:
        table, manifest = _read_gold_from_hdfs(snapshot_id, compose_file)
    else:
        table, manifest = _read_gold_from_local(Path(gold_parquet_dir).resolve(), fit_end_date)

    rows_dict = table.select(list(GOLD_BASELINE_COLUMNS)).to_pydict()
    num_rows = table.num_rows
    baseline_rows = list(zip(*(rows_dict[col] for col in GOLD_BASELINE_COLUMNS)))

    output_db.parent.mkdir(parents=True, exist_ok=True)
    tmp_db = output_db.with_name(f"{output_db.name}.{uuid4()}.tmp")

    try:
        src = sqlite3.connect(source_db.as_uri() + "?mode=ro", uri=True)
        dst = sqlite3.connect(tmp_db)
        try:
            with dst:
                for tbl_name in STATIC_GTFS_TABLES:
                    ddl_row = src.execute(
                        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                        (tbl_name,),
                    ).fetchone()
                    if not ddl_row or not ddl_row[0]:
                        raise ValueError(f"Missing static GTFS table in source DB: {tbl_name}")
                    dst.execute(ddl_row[0])

                    src_rows = src.execute(f'SELECT * FROM "{tbl_name}"').fetchall()
                    if src_rows:
                        placeholders = ",".join(["?"] * len(src_rows[0]))
                        dst.executemany(f'INSERT INTO "{tbl_name}" VALUES ({placeholders})', src_rows)

                    for (idx_sql,) in src.execute(
                        "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL",
                        (tbl_name,),
                    ):
                        dst.execute(idx_sql)

                dst.execute(AGG_BASELINE_DDL)
                if baseline_rows:
                    placeholders = ",".join(["?"] * len(GOLD_BASELINE_COLUMNS))
                    dst.executemany(
                        f"INSERT INTO agg_segment_travel_times VALUES ({placeholders})",
                        baseline_rows,
                    )

                dst.execute(
                    "CREATE TABLE eta_baseline_manifest(fit_end_date TEXT, train_end_date TEXT, test_start_date TEXT)"
                )
                dst.execute(
                    "INSERT INTO eta_baseline_manifest VALUES (?, ?, ?)",
                    (
                        str(manifest.get("fit_end_date") or fit_end_date),
                        str(manifest.get("train_end_date") or TRAIN_SPLIT_END_DATE),
                        str(manifest.get("test_start_date") or TEST_SPLIT_START_DATE),
                    ),
                )

            dst.execute("VACUUM")
            created_tables = tuple(
                sorted(
                    r[0]
                    for r in dst.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                    ).fetchall()
                )
            )
            if created_tables != tuple(sorted(SERVING_TABLES)):
                raise RuntimeError(f"Unexpected table set in serving DB: {created_tables}")
        finally:
            src.close()
            dst.close()

        os.replace(tmp_db, output_db)
    except Exception:
        if tmp_db.exists():
            tmp_db.unlink()
        raise

    return {
        "output_db": str(output_db),
        "size_mb": round(output_db.stat().st_size / (1024 * 1024), 2),
        "tables": list(created_tables),
        "baseline_rows": num_rows,
        "fit_end_date": str(manifest.get("fit_end_date") or fit_end_date),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", type=Path, default=ROOT / DEFAULT_DB_PATH)
    parser.add_argument("--output-db", type=Path, default=ROOT / DEFAULT_DB_PATH)
    src_group = parser.add_mutually_exclusive_group(required=True)
    src_group.add_argument("--snapshot", help="64-hex HDFS snapshot ID to pull Gold Baseline from")
    src_group.add_argument("--gold-parquet", type=Path, help="Local Gold Parquet directory")
    parser.add_argument("--fit-end-date", default=BASELINE_FIT_END_DATE)
    args = parser.parse_args()

    result = sync_gold_to_serving_db(
        source_db=args.source_db,
        output_db=args.output_db,
        snapshot_id=args.snapshot,
        gold_parquet_dir=args.gold_parquet,
        fit_end_date=args.fit_end_date,
    )
    print("SYNC_RESULT=" + json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
