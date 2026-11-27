"""Phi-Docker end-to-end local batch pipeline: Raw Bus & TomTom JSONL -> data/lakehouse Parquet -> 5-table Serving DB (+ optional Causal Feature Extraction)."""

from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from contextlib import contextmanager
import gc
import json
from pathlib import Path
import shutil
import sqlite3
import sys

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from config.hardware_guard import check_memory_pressure, recommend_workers, set_process_below_normal_priority
from config.system_config import (
    BASELINE_FIT_END_DATE,
    CANONICAL_START_DATE,
    CONFIG_FILE,
    DEFAULT_DB_PATH,
    LOCAL_LAKEHOUSE_ROOT,
    STALE_DELTA_T_MAX_SEC,
    TEST_SPLIT_END_DATE,
    TEST_SPLIT_START_DATE,
    TZ_HANOI,
)
from modules.ingestion.projection import (
    tomtom_incident_projector as inc_proj,
)
from modules.ingestion.gtfs import (
    ingest_busmap_canonical as gtfs_ingest,
)
from modules.lakehouse.hdfs.history_snapshot import (
    merge_event,
    normalize_bus,
    project_group,
)
from modules.eta.baseline import (
    baseline_matrix_builder as local_baseline,
)
from modules.eta.training import (
    silver_replay_trainer,
)
from modules.eta.serving.serving_service import (
    BusMapServingService,
)
from modules.lakehouse.serving_sync import sync_gold_to_serving_db


@contextmanager
def _patched_attrs(obj, **attrs):
    prev = {k: getattr(obj, k) for k in attrs}
    try:
        for k, v in attrs.items():
            setattr(obj, k, v)
        yield
    finally:
        for k, v in prev.items():
            setattr(obj, k, v)


def _load_active_route_codes(config_path: Path) -> set[str]:
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    routes = payload.get("routes", [])
    return {
        str(item["route_no"])
        for item in routes
        if isinstance(item, dict) and item.get("route_no") is not None
    }


def _export_reference_from_db(db_path: Path) -> dict:
    conn = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        conn.row_factory = sqlite3.Row
        routes = {
            str(r["route_id"]): r["route_code"]
            for r in conn.execute("SELECT route_id, route_code FROM canonical_route_master ORDER BY route_id")
        }
        stations = [
            dict(r)
            for r in conn.execute(
                "SELECT route_id, route_code, direction, station_id, station_order, station_name, cum_distance_m "
                "FROM canonical_station_master ORDER BY route_id, direction, station_order"
            )
        ]
        shapes = {}
        for r in conn.execute(
            "SELECT route_id, direction, point_order, lat, lon, cum_distance_m "
            "FROM canonical_shape_master ORDER BY route_id, direction, point_order"
        ):
            shapes.setdefault(str(r["route_id"]), {}).setdefault(r["direction"], []).append(
                [r["point_order"], r["lat"], r["lon"], r["cum_distance_m"]]
            )
    finally:
        conn.close()
    return {"schema_version": "history-reference.v1", "routes": routes, "stations": stations, "shapes": shapes}


def _project_day_bus_to_silver(
    day_dir: Path,
    silver_tel_dir: Path,
    reference: dict,
    active_route_codes: set[str] | None = None,
) -> tuple[int, int, int, int]:
    """Process one YYYY-MM-DD/bus directory into partitioned Silver Parquet with bounded RAM."""
    bus_files = sorted((day_dir / "bus").glob("*.jsonl"))
    events_by_id = defaultdict(list)
    raw_lines = 0
    rejected = 0

    for fpath in bus_files:
        batch_id = f"{day_dir.name}/{fpath.name}"
        with fpath.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                raw_lines += 1
                kind, row = normalize_bus(line, batch_id, reference)
                if kind == "event":
                    events_by_id[row["event_id"]].append(row)
                else:
                    rejected += 1

    unique_events = [merge_event((eid, obs)) for eid, obs in events_by_id.items()]
    del events_by_id

    by_route_vehicle = defaultdict(list)
    for row in unique_events:
        by_route_vehicle[(row["route_id"], row["vehicle_id"])].append(row)

    projected_rows = []
    for (route_id, _vehicle_id), v_rows in sorted(by_route_vehicle.items()):
        v_rows.sort(key=lambda r: (r["observed_ms"], r["event_id"]))
        session = []
        for row in v_rows:
            if session and row["observed_ms"] - session[-1]["observed_ms"] > STALE_DELTA_T_MAX_SEC * 1000:
                projected_rows.extend(project_group((route_id, session), reference)["rows"])
                session = []
            session.append(row)
        if session:
            projected_rows.extend(project_group((route_id, session), reference)["rows"])

    silver_rows = 0
    if projected_rows:
        df_sil = pd.DataFrame(projected_rows)
        df_sil["dt"] = (
            pd.to_datetime(df_sil["device_epoch_s"], unit="s", utc=True)
            .dt.tz_convert(TZ_HANOI)
            .dt.strftime("%Y-%m-%d")
        )
        df_sil = df_sil[df_sil["dt"] >= CANONICAL_START_DATE]
        if active_route_codes is not None:
            df_sil = df_sil[df_sil["route_code"].isin(active_route_codes)]
        part_name = f"part-{day_dir.name}.snappy.parquet"
        for (rc, dt_str), grp in df_sil.groupby(["route_code", "dt"], sort=True):
            part_dir = silver_tel_dir / f"route_code={rc}" / f"dt={dt_str}"
            part_dir.mkdir(parents=True, exist_ok=True)
            table = pa.Table.from_pandas(grp.drop(columns=["route_code", "dt"]), preserve_index=False)
            pq.write_table(table, part_dir / part_name, compression="snappy")
            silver_rows += len(grp)
        del df_sil

    unique_count = len(unique_events)
    del unique_events, by_route_vehicle, projected_rows
    gc.collect()
    return raw_lines, unique_count, rejected, silver_rows


_WORKER_REFERENCE: dict | None = None
_WORKER_SILVER_DIR: str | None = None
_WORKER_ACTIVE_CODES: set[str] | None = None


def _init_day_worker(reference: dict, silver_tel_dir: str, active_codes: set[str] | None):
    global _WORKER_REFERENCE, _WORKER_SILVER_DIR, _WORKER_ACTIVE_CODES
    set_process_below_normal_priority()
    _WORKER_REFERENCE = reference
    _WORKER_SILVER_DIR = silver_tel_dir
    _WORKER_ACTIVE_CODES = active_codes


def _project_day_worker(day_dir_str: str) -> tuple[str, int, int, int, int]:
    day_dir = Path(day_dir_str)
    stats = _project_day_bus_to_silver(
        day_dir,
        Path(_WORKER_SILVER_DIR),
        _WORKER_REFERENCE,
        active_route_codes=_WORKER_ACTIVE_CODES,
    )
    return (day_dir.name, *stats)


def run_local_batch_pipeline(
    *,
    raw_dir: Path,
    lakehouse_dir: Path | None = None,
    db_path: Path | None = None,
    workspace: Path | None = None,
    fit_end_date: str = BASELINE_FIT_END_DATE,
    active_routes_only: bool = True,
    clean: bool = True,
    export_features: bool = False,
    train_from_day: str = "2026-10-22",
    train_to_day: str = TEST_SPLIT_END_DATE,
    test_start: str = TEST_SPLIT_START_DATE,
    forecast_every: float = 120.0,
    workers: int = 6,
) -> dict:
    raw_dir = Path(raw_dir).resolve()
    if workspace is not None:
        ws = Path(workspace).resolve()
        if clean and ws.exists():
            shutil.rmtree(ws)
        ws.mkdir(parents=True, exist_ok=True)
        resolved_lakehouse = ws / "lakehouse"
        serving_db = ws / "serving.db"
    else:
        resolved_lakehouse = Path(lakehouse_dir or (ROOT / LOCAL_LAKEHOUSE_ROOT)).resolve()
        serving_db = Path(db_path or (ROOT / DEFAULT_DB_PATH)).resolve()
        if clean and resolved_lakehouse.exists():
            shutil.rmtree(resolved_lakehouse)
        resolved_lakehouse.mkdir(parents=True, exist_ok=True)
        serving_db.parent.mkdir(parents=True, exist_ok=True)

    silver_tel_dir = resolved_lakehouse / "silver" / "route_projected_telemetry"
    silver_inc_dir = resolved_lakehouse / "silver" / "fact_route_tomtom_incidents"
    gold_dir = resolved_lakehouse / "gold" / "agg_segment_travel_times"
    features_root = resolved_lakehouse / "gold" / "causal_features"

    active_codes = _load_active_route_codes(ROOT / CONFIG_FILE) if active_routes_only else None

    # 1. GTFS Canonical Ingestion -> serving.db (3 static tables)
    with _patched_attrs(gtfs_ingest, DB_PATH=serving_db):
        gtfs_ingest.main()
    reference = _export_reference_from_db(serving_db)

    # 2. Raw Bus JSONL -> Silver Frenet Parquet (day-by-day streaming for bounded RAM)
    day_dirs = sorted(p for p in raw_dir.iterdir() if p.is_dir() and (p / "bus").is_dir())
    if not day_dirs or not any((d / "bus").glob("*.jsonl") for d in day_dirs):
        raise FileNotFoundError(f"No bus JSONL files found under {raw_dir}")

    raw_bus_lines = 0
    unique_bus_events = 0
    rejected_bus = 0
    silver_bus_rows = 0
    bus_workers = recommend_workers(workers, per_worker_ram_gb=0.5, min_free_ram_gb=1.5, max_cpu_frac=0.75)
    if bus_workers <= 1 or len(day_dirs) <= 1:
        for idx, day_dir in enumerate(day_dirs, 1):
            d_raw, d_uniq, d_rej, d_sil = _project_day_bus_to_silver(
                day_dir, silver_tel_dir, reference, active_route_codes=active_codes
            )
            raw_bus_lines += d_raw
            unique_bus_events += d_uniq
            rejected_bus += d_rej
            silver_bus_rows += d_sil
            print(
                f"[Silver Bus {idx}/{len(day_dirs)}] {day_dir.name}: "
                f"raw={d_raw:,} unique={d_uniq:,} rejected={d_rej:,} silver={d_sil:,}",
                flush=True,
            )
            check_memory_pressure(label=f"local_silver_{day_dir.name}")
    else:
        with ProcessPoolExecutor(
            max_workers=bus_workers,
            initializer=_init_day_worker,
            initargs=(reference, str(silver_tel_dir), active_codes),
        ) as pool:
            day_iter = iter(day_dirs)
            in_flight = set()
            for _ in range(min(bus_workers, len(day_dirs))):
                dd = next(day_iter, None)
                if dd is None:
                    break
                in_flight.add(pool.submit(_project_day_worker, str(dd)))
            done_count = 0
            while in_flight:
                done, in_flight = wait(in_flight, return_when=FIRST_COMPLETED)
                for fut in done:
                    nxt = next(day_iter, None)
                    if nxt is not None:
                        in_flight.add(pool.submit(_project_day_worker, str(nxt)))
                    day_name, d_raw, d_uniq, d_rej, d_sil = fut.result()
                    done_count += 1
                    raw_bus_lines += d_raw
                    unique_bus_events += d_uniq
                    rejected_bus += d_rej
                    silver_bus_rows += d_sil
                    print(
                        f"[Silver Bus {done_count}/{len(day_dirs)}] {day_name}: "
                        f"raw={d_raw:,} unique={d_uniq:,} rejected={d_rej:,} silver={d_sil:,}",
                        flush=True,
                    )
                    check_memory_pressure(label=f"local_silver_{day_name}")

    # 3. Raw TomTom Incidents JSONL -> Silver Incidents Parquet (NO SQLite write)
    inc_files = sorted(raw_dir.glob("*/incidents/*.jsonl"))
    if not inc_files:
        raise FileNotFoundError(f"No incident JSONL files found under {raw_dir}")
    inc_stats = inc_proj.main(
        [
            "--db-path",
            str(serving_db),
            "--silver-tel-dir",
            str(silver_tel_dir),
            "--incidents-glob",
            str(raw_dir / "*" / "incidents" / "*.jsonl"),
            "--output-dir",
            str(silver_inc_dir),
        ]
    )

    # 4. Gold Baseline Matrix -> Gold Parquet
    baseline_stats = local_baseline.build_and_evaluate_baseline_matrix(
        fit_end_date=fit_end_date,
        db_path=str(serving_db),
        silver_tel_dir=str(silver_tel_dir),
        gold_baseline_dir=str(gold_dir),
    )

    # 5. Sync 5-table Serving DB (1-way)
    sync_stats = sync_gold_to_serving_db(
        source_db=serving_db,
        output_db=serving_db,
        gold_parquet_dir=gold_dir,
        fit_end_date=fit_end_date,
    )

    # 6. Verify Silver Incidents Parquet readability + Serving Layer without Docker
    inc_parquet_rows = 0
    inc_routes_loaded = 0
    for route_dir in sorted(silver_inc_dir.glob("route_code=*")):
        if not route_dir.is_dir():
            continue
        route_rows = sum(pq.ParquetFile(pf).metadata.num_rows for pf in route_dir.glob("*.parquet"))
        if route_rows > 0:
            inc_routes_loaded += 1
            inc_parquet_rows += route_rows
    if inc_parquet_rows != int(inc_stats["fact_rows"]):
        raise RuntimeError(
            f"Silver incident Parquet row mismatch: expected {inc_stats['fact_rows']}, got {inc_parquet_rows}"
        )

    svc = BusMapServingService(db_path=str(serving_db))

    # 7. Optional: Causal Feature Extraction to per-route Parquet checkpoints (NO XGBoost retrain)
    feature_summary = None
    if export_features:
        feat_args = argparse.Namespace(
            silver=silver_tel_dir,
            hdfs_snapshot=None,
            compose_file=ROOT / "docker-compose.hdfs.yml",
            db_path=serving_db,
            from_day=train_from_day,
            to_day=train_to_day,
            validation_start=None,
            test_start=test_start,
            no_valid=True,
            reference_model=None,
            output=None,
            export_checkpoints_dir=features_root,
            workers=workers,
            route=None,
            rounds=1200,
            max_depth=6,
            forecast_every=forecast_every,
            incidents=silver_inc_dir,
        )
        silver_replay_trainer.run(feat_args)
        ckpt_dir = features_root / "features"
        meta_files = sorted(ckpt_dir.glob("*.json"))
        total_feat_rows = sum(
            int(json.loads(mf.read_text(encoding="utf-8")).get("rows", 0))
            for mf in meta_files
        )
        feature_summary = {
            "checkpoints_dir": str(ckpt_dir),
            "routes_exported": len(meta_files),
            "total_rows": total_feat_rows,
            "from_day": train_from_day,
            "to_day": train_to_day,
            "test_start": test_start,
            "forecast_every": forecast_every,
        }

    return {
        "mode": "phi-docker-local",
        "lakehouse_dir": str(resolved_lakehouse),
        "serving_db_path": str(serving_db),
        "active_routes_only": active_routes_only,
        "days_processed": len(day_dirs),
        "raw_bus_lines": raw_bus_lines,
        "unique_bus_events": unique_bus_events,
        "rejected_bus_normalize": rejected_bus,
        "silver_bus_rows": silver_bus_rows,
        "silver_incidents": inc_stats,
        "gold_baseline": {
            "total_cells": baseline_stats["total_cells"],
            "fit_trips": baseline_stats["fit_trips"],
            "tier_counts": baseline_stats["tier_counts"],
        },
        "serving_db": sync_stats,
        "serving_check": {
            "routes": len(svc.get_routes()),
            "baseline_routes": len(svc.source_info["baseline_routes"]),
            "model_available": svc._runtime.available,
            "incident_routes_loaded": inc_routes_loaded,
        },
        "causal_features": feature_summary,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--lakehouse-dir", type=Path, default=ROOT / LOCAL_LAKEHOUSE_ROOT)
    parser.add_argument("--db-path", type=Path, default=ROOT / DEFAULT_DB_PATH)
    parser.add_argument("--workspace", type=Path, default=None, help="Optional isolated workspace dir overriding --lakehouse-dir/--db-path")
    parser.add_argument("--fit-end-date", default=BASELINE_FIT_END_DATE)
    parser.add_argument("--all-routes", action="store_true", help="Include discontinued routes outside CONFIG_FILE")
    parser.add_argument("--no-clean", action="store_true")
    parser.add_argument("--export-features", action="store_true")
    parser.add_argument("--train-from-day", default="2026-10-22")
    parser.add_argument("--train-to-day", default=TEST_SPLIT_END_DATE)
    parser.add_argument("--test-start", default=TEST_SPLIT_START_DATE)
    parser.add_argument("--forecast-every", type=float, default=120.0)
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    result = run_local_batch_pipeline(
        raw_dir=args.raw_dir,
        lakehouse_dir=args.lakehouse_dir,
        db_path=args.db_path,
        workspace=args.workspace,
        fit_end_date=args.fit_end_date,
        active_routes_only=not args.all_routes,
        clean=not args.no_clean,
        export_features=args.export_features,
        train_from_day=args.train_from_day,
        train_to_day=args.train_to_day,
        test_start=args.test_start,
        forecast_every=args.forecast_every,
        workers=args.workers,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
