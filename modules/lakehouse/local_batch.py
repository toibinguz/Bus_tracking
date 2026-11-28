"""Run the shared historical pipeline directly against local files."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from config.system_config import (BASELINE_FIT_END_DATE, CONFIG_FILE, DEFAULT_DB_PATH, HF_DATASET_ID,
                                  LOCAL_LAKEHOUSE_ROOT, TEST_SPLIT_END_DATE, TEST_SPLIT_START_DATE)
from modules.ingestion.gtfs import ingest_busmap_canonical as gtfs
from modules.lakehouse.hdfs.reference_export import load_reference
from modules.lakehouse.local_adapter import LocalAdapter
from modules.lakehouse.pipeline.spec import FEATURE_START, FORECAST_SECONDS, PipelineSpec, resolve_routes, run_pipeline

ROOT = Path(__file__).resolve().parents[2]


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
    train_from_day: str = FEATURE_START,
    train_to_day: str = TEST_SPLIT_END_DATE,
    test_start: str = TEST_SPLIT_START_DATE,
    forecast_every: float = FORECAST_SECONDS,
    workers: int = 6,
    routes=None,
    feature_routes=None, validation_start=None, max_route_events=None,
    dataset=HF_DATASET_ID, stage=None,
) -> dict:
    raw_dir = Path(raw_dir).resolve()
    root = (Path(workspace) / "lakehouse" if workspace else Path(lakehouse_dir or ROOT / LOCAL_LAKEHOUSE_ROOT)).resolve()
    serving = (Path(workspace) / "serving.db" if workspace else Path(db_path or ROOT / DEFAULT_DB_PATH)).resolve()
    catalog = json.loads((ROOT / CONFIG_FILE).read_text(encoding="utf-8"))
    selected = resolve_routes(routes, not active_routes_only, catalog)
    stages = ("silver", "baseline", "features", "serving") if export_features else ("silver", "baseline", "serving")
    if stage:
        stages = (stage,)
    spec = PipelineSpec(stages, selected, fit_end_date, train_from_day, train_to_day, test_start,
                        forecast_every=forecast_every, validation_start=validation_start,
                        feature_routes=tuple(sorted(set(feature_routes))) if feature_routes else None)
    root.mkdir(parents=True, exist_ok=True)
    # Each run writes immutable builds. Older builds can still be pinned by readers.
    with TemporaryDirectory(dir=root) as tmp:
        static_db = Path(tmp) / "catalog.sqlite"
        gtfs.main(static_db)
        adapter = LocalAdapter(raw_dir, root, load_reference(static_db), static_db, serving, dataset, workers, max_route_events)
        result = run_pipeline(spec, adapter)
    if stage:
        return result[stage]
    silver = result["silver"]
    return dict(mode="local", lakehouse_dir=str(root), serving_db_path=str(serving),
                days_processed=len({m["path"].split("/")[1] for m in silver["source_manifests"] if m["category"] == "bus"}),
                active_routes_only=active_routes_only, raw_bus_lines=silver["raw_bus_rows"],
                unique_bus_events=silver["unique_bus_events"], rejected_bus_normalize=silver["rejected_bus_normalize"],
                silver_bus_rows=silver["accepted_bus_rows"], silver=silver, gold_baseline=result["baseline"],
                causal_features=result.get("features"), serving_db=result["serving"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--lakehouse-dir", type=Path, default=ROOT / LOCAL_LAKEHOUSE_ROOT)
    parser.add_argument("--db-path", type=Path, default=ROOT / DEFAULT_DB_PATH)
    parser.add_argument("--workspace", type=Path, default=None, help="Optional isolated workspace dir overriding --lakehouse-dir/--db-path")
    parser.add_argument("--fit-end-date", default=BASELINE_FIT_END_DATE)
    parser.add_argument("--all-routes", action="store_true", help="Include discontinued routes outside CONFIG_FILE")
    parser.add_argument("--no-clean", action="store_true", help="Compatibility flag; versioned builds always retain prior publications")
    parser.add_argument("--export-features", action="store_true")
    parser.add_argument("--train-from-day", default=FEATURE_START)
    parser.add_argument("--train-to-day", default=TEST_SPLIT_END_DATE)
    parser.add_argument("--test-start", default=TEST_SPLIT_START_DATE)
    parser.add_argument("--forecast-every", type=float, default=FORECAST_SECONDS)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--routes", nargs="+", help="Explicit Silver route codes")
    parser.add_argument("--stage", choices=("silver", "baseline", "features", "serving"), help="Run one stage against published inputs")
    parser.add_argument("--feature-routes", nargs="+")
    parser.add_argument("--validation-start")
    parser.add_argument("--max-route-events", type=int, help="Fail before loading a larger route into a local Gold worker")
    parser.add_argument("--dataset", default=HF_DATASET_ID, help="Logical dataset ID used by the Bronze ledger")
    args = parser.parse_args()
    result = run_local_batch_pipeline(
        raw_dir=args.raw_dir,
        lakehouse_dir=args.lakehouse_dir,
        db_path=args.db_path,
        workspace=args.workspace,
        fit_end_date=args.fit_end_date,
        active_routes_only=not args.all_routes,
        clean=not args.no_clean, feature_routes=args.feature_routes, validation_start=args.validation_start,
        max_route_events=args.max_route_events,
        export_features=args.export_features,
        train_from_day=args.train_from_day,
        train_to_day=args.train_to_day,
        test_start=args.test_start,
        forecast_every=args.forecast_every,
        workers=args.workers, routes=args.routes, dataset=args.dataset, stage=args.stage,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
