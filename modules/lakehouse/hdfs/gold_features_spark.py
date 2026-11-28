from __future__ import annotations

from modules.lakehouse.pipeline.features import (
    FEATURES,
    SPLIT_NAMES,
    GOLD_CAUSAL_FEATURE_COLUMNS,
    RouteReferenceLookup,
    build_route_feature_metadata,
    extract_route_causal_features_partition,
    compute_route_features,
    project_window_intervals, incident_window,
    _date_epoch,
)

from datetime import datetime
from config.system_config import TZ_HANOI


from modules.lakehouse.pipeline.spec import (
    FEATURE_START, FORECAST_SECONDS, MAX_SESSION_EVENTS, logic_version, run_pipeline, stage_manifest, validate_counts,
)
from modules.lakehouse.hdfs.spark_adapter import SparkAdapter, cli_spec
from config.system_config import BASELINE_FIT_END_DATE, TEST_SPLIT_START_DATE, TEST_SPLIT_END_DATE


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, help="Published 64-hex Silver/Gold snapshot ID")
    parser.add_argument("--from-day", default=FEATURE_START)
    parser.add_argument("--to-day", default=TEST_SPLIT_END_DATE)
    parser.add_argument("--validation-start", default=None)
    parser.add_argument("--test-start", default=TEST_SPLIT_START_DATE)
    parser.add_argument("--no-valid", action="store_true")
    parser.add_argument("--forecast-every", type=float, default=FORECAST_SECONDS)
    parser.add_argument("--routes", nargs="+", help="Optional subset of route_code values")
    parser.add_argument("--partitions", type=int, default=16)
    parser.add_argument("--baseline-build-id", help="Pin an immutable Gold baseline build")
    parser.add_argument("--feature-routes", nargs="+")
    parser.add_argument("--all-routes", action="store_true")
    args = parser.parse_args()
    stages = ("features",)
    return run_pipeline(cli_spec(args, stages), SparkAdapter(args))


def execute(spec, args, source, baseline_manifest):
    """PySpark entrypoint: HDFS Silver + Gold Baseline -> HDFS Gold Causal Features (C++17 + fallback)."""
    from datetime import date, timedelta, timezone
    import gc
    import json
    from pathlib import Path
    import sys
    import time
    from uuid import uuid4

    resource = None
    if sys.platform != "win32":
        import resource as _resource
        resource = _resource

    from pyspark.sql import SparkSession, functions as F
    from modules.lakehouse.hdfs.spark_schema import spark_schema
    from modules.lakehouse.pipeline.schema import CAUSAL

    root = Path(__file__).resolve().parents[3]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from config.system_config import BASELINE_FIT_END_DATE, TEST_SPLIT_END_DATE, TEST_SPLIT_START_DATE
    from modules.lakehouse.hdfs.hf_bronze import digest, encoded
    from modules.lakehouse.hdfs.gold_publication import publish_gold

    hdfs_root = "hdfs://namenode:8020/bus-eta/v1"
    publications = hdfs_root + "/_published/history_snapshots"
    gold_baseline_root_prefix = hdfs_root + "/gold/agg_segment_travel_times"
    gold_features_root_prefix = hdfs_root + "/gold/causal_features"


    if len(args.snapshot) != 64 or any(c not in "0123456789abcdef" for c in args.snapshot):
        raise ValueError("invalid snapshot ID")
    first_day = date.fromisoformat(args.from_day)
    last_day = date.fromisoformat(args.to_day)
    if first_day > last_day or args.forecast_every <= 0 or args.partitions < 1:
        raise ValueError("invalid date window or positive settings")

    started = time.monotonic()
    spark = (
        SparkSession.builder.appName("bus-eta-gold-causal-features")
        # HDFS DataNodes and executors live in separate containers.
        .config("spark.locality.wait", "0s")
        .config("spark.sql.session.timeZone", "Asia/Ho_Chi_Minh")
        .config("spark.sql.sources.partitionColumnTypeInference.enabled", "false")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")
    spark.conf.set("spark.sql.shuffle.partitions", str(args.partitions))
    fs = spark._jvm.org.apache.hadoop.fs.FileSystem.get(spark._jsc.hadoopConfiguration())
    jpath = spark._jvm.org.apache.hadoop.fs.Path

    def read_bytes(path: str) -> bytes:
        return bytes(spark.read.format("binaryFile").load(path).first().content)

    try:
        ref_raw = read_bytes(source["reference_path"])
        if digest(ref_raw) != source["reference_sha256"]:
            raise ValueError("reference content hash mismatch")
        reference = json.loads(ref_raw)

        gold_baseline_root = f"{gold_baseline_root_prefix}/snapshot={args.snapshot}"
        fit_end_date = baseline_manifest.get("fit_end_date", BASELINE_FIT_END_DATE)
        validation_day = spec.validation_start or spec.test_start
        validation_epoch, test_epoch = spec.validation_epoch, spec.test_epoch
        if date.fromisoformat(fit_end_date) >= first_day:
            raise ValueError("baseline fit overlaps causal feature extraction window")

        silver_df = spark.read.parquet(source["silver_path"]).filter(
            spec.includes_features(F.col("dt"))
        )
        if spec.selected_features is not None:
            silver_df = silver_df.filter(F.col("route_code").isin(list(spec.selected_features)))

        active_routes = sorted(
            r.route_code
            for r in silver_df.select("route_code").distinct().collect()
            if r.route_code is not None
        )
        if not active_routes:
            raise ValueError("no Silver routes in chosen feature window")

        baseline_cols = [
            "route_code",
            "direction",
            "from_station_order",
            "to_station_order",
            "day_type",
            "hour_slot",
            "quality_tier",
            "segment_length_m",
            "tt_p10_sec",
            "tt_p50_sec",
            "tt_p90_sec",
            "tt_mean_sec",
            "tt_std_sec",
        ]
        baseline_df = spark.read.parquet(baseline_manifest.get("gold_data_path", f"{gold_baseline_root}/data"))
        baseline_codes = sorted(r.route_code for r in baseline_df.select("route_code").distinct().collect())
        baseline_rows = [
            row.asDict()
            for row in baseline_df
            .filter(F.col("route_code").isin(active_routes))
            .select(*baseline_cols)
            .toLocalIterator()
        ]

        meta = build_route_feature_metadata(reference, active_routes, baseline_rows, baseline_codes)
        # Local DataAccess derives feature indices from the complete baseline catalog.
        if set(active_routes).difference(meta["route_idx_by_code"]):
            raise ValueError("requested routes missing from published baseline")
        del reference, baseline_rows
        gc.collect()

        sc = spark.sparkContext
        engines = {name: sc.accumulator(0) for name in ("cpp_native", "python")}
        bc_meta = sc.broadcast(meta)
        cadence_sec = float(args.forecast_every)
        telemetry = silver_df.select(
            "route_code", "direction", "vehicle_id", "plate", "device_epoch_s", "s_bus_m", "lat", "lon"
        ).rdd.map(lambda row: (row.route_code, row.asDict()))

        inc_obs_path = source["snapshot_path"].rstrip("/") + "/incident_observations"
        intervals = sc.emptyRDD()
        if source.get("incident_observations") and fs.exists(jpath(inc_obs_path)):
            from modules.ingestion.projection.tomtom_incident_projector import DEFAULT_TTL_SEC, MAX_BATCH_GAP_SEC

            observations = spark.read.parquet(inc_obs_path).withColumn(
                "incident_id", F.get_json_object("raw_json", "$.incident_id")
            )
            earliest, window_start, window_end = incident_window(args.from_day, args.to_day)
            candidates = observations.filter(
                F.col("dt").between(earliest, args.to_day)
            ).select("incident_id").distinct()
            # Keep the full history of each candidate: first geometry and successive
            # observations determine the projected intervals across date boundaries.
            relevant = observations.join(candidates, "incident_id", "left_semi")
            intervals = relevant.repartition(args.partitions, "incident_id").select("raw_json").rdd.mapPartitions(
                lambda rows: project_window_intervals(rows, bc_meta.value, window_start, window_end)
            )

        def extract(pair):
            route, (observations, facts) = pair
            by_direction = {0: [], 1: []}
            for direction, interval in facts:
                by_direction[direction].append(interval)
            started_route = time.monotonic()
            rows = compute_route_features(
                route, observations, by_direction, bc_meta.value, fit_end_date=fit_end_date,
                validation_epoch=validation_epoch, test_epoch=test_epoch, cadence_sec=cadence_sec, record_engine=lambda name: engines[name].add(1),
            )
            count = 0
            for row in rows:
                count += 1
                yield row
            print("FEATURE_ROUTE=" + json.dumps(dict(
                route=route, rows=count, seconds=round(time.monotonic()-started_route, 3),
                worker_peak_rss_kib=(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss if resource is not None else None),
            )), flush=True)

        rows_rdd = telemetry.cogroup(intervals, args.partitions).flatMap(extract)

        schema = spark_schema(CAUSAL)

        out_root = f"{gold_features_root_prefix}/snapshot={args.snapshot}"
        build_id = uuid4().hex
        out_data = f"{out_root}/builds/{build_id}/data"
        feat_df = spark.createDataFrame(rows_rdd, schema)
        # cogroup already places every row of a route in one partition.
        feat_df.write.mode("errorifexists").partitionBy("route").parquet(out_data)

        written = spark.read.schema(schema).parquet(out_data)
        total_rows = written.count()
        split_counts = {str(r["split"]): int(r["count"]) for r in written.groupBy("split").count().collect()}

        validate_counts(split_counts, total_rows, SPLIT_NAMES)

        manifest = {
            "schema_version": "gold-causal-features.v1",
            "snapshot_id": args.snapshot,
            "build_id": build_id,
            "baseline_build_id": baseline_manifest.get("build_id"),
            "validation_start": validation_day,
            "fit_end_date": fit_end_date,
            "from_day": args.from_day,
            "to_day": args.to_day,
            "test_start": args.test_start,
            "no_valid": bool(args.no_valid),
            "forecast_every": cadence_sec,
            "routes": active_routes,
            "row_count": total_rows,
            "split_counts": split_counts,
            "python_driver_peak_rss_kib": (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss if resource is not None else None),
            "columns": list(GOLD_CAUSAL_FEATURE_COLUMNS),
            "data_path": out_data,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "published_at": datetime.now(timezone.utc).isoformat(),
        }
        manifest = stage_manifest("features", spec, [k for k, counter in engines.items() if counter.value], **manifest)
        publish_gold(spark, out_root, build_id, encoded(manifest))
        print("GOLD_FEATURES_RESULT=" + json.dumps(manifest), flush=True)
        return manifest
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
