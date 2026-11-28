from __future__ import annotations

from modules.lakehouse.pipeline.baseline import (
    GOLD_BASELINE_COLUMNS,
    build_reference_lookup,
    compute_route_baseline,
    aggregate_route_baseline,
    extract_partition_samples,
)

build_route_baseline_spark = compute_route_baseline


from modules.lakehouse.pipeline.spec import (
    FEATURE_START, FORECAST_SECONDS, MAX_SESSION_EVENTS, logic_version, run_pipeline, stage_manifest, validate_counts,
)
from modules.lakehouse.hdfs.spark_adapter import SparkAdapter, cli_spec
from config.system_config import BASELINE_FIT_END_DATE, TEST_SPLIT_START_DATE, TEST_SPLIT_END_DATE


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, help="Published 64-hex Silver snapshot ID")
    parser.add_argument("--fit-end-date", default=BASELINE_FIT_END_DATE)
    parser.add_argument("--routes", nargs="+", help="Optional subset of route_code values")
    parser.add_argument("--partitions", type=int, default=16)
    parser.add_argument("--all-routes", action="store_true")
    args = parser.parse_args()
    stages = ("baseline",)
    return run_pipeline(cli_spec(args, stages), SparkAdapter(args))


def execute(spec, args, source):
    """PySpark entrypoint: HDFS Silver Parquet -> HDFS Gold Baseline Matrix."""
    from datetime import date, datetime, timezone
    import json
    from pathlib import Path
    import sys
    import time
    from uuid import uuid4

    from pyspark.sql import SparkSession, functions as F
    from modules.lakehouse.hdfs.spark_schema import spark_schema
    from modules.lakehouse.pipeline.schema import BASELINE

    root = Path(__file__).resolve().parents[3]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from config.system_config import BASELINE_FIT_END_DATE, TEST_SPLIT_START_DATE, TRAIN_SPLIT_END_DATE
    from modules.lakehouse.hdfs.hf_bronze import digest, encoded
    from modules.lakehouse.hdfs.gold_publication import publish_gold

    hdfs_root = "hdfs://namenode:8020/bus-eta/v1"
    publications = hdfs_root + "/_published/history_snapshots"
    gold_root_prefix = hdfs_root + "/gold/agg_segment_travel_times"


    if len(args.snapshot) != 64 or any(c not in "0123456789abcdef" for c in args.snapshot):
        raise ValueError("invalid snapshot ID")
    date.fromisoformat(args.fit_end_date)
    if args.fit_end_date > TRAIN_SPLIT_END_DATE:
        raise ValueError("fit-end-date must not extend past TRAIN_SPLIT_END_DATE")
    if args.partitions < 1:
        raise ValueError("partitions must be positive")

    started = time.monotonic()
    spark = (
        SparkSession.builder.appName("bus-eta-gold-baseline")
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
        shape_len_map, stations_map = build_reference_lookup(reference)

        silver_df = spark.read.parquet(source["silver_path"])
        if spec.routes is not None:
            silver_df = silver_df.filter(F.col("route_code").isin(list(spec.routes)))

        active_routes = sorted(
            r.route_code
            for r in silver_df.select("route_code").distinct().collect()
            if r.route_code is not None
        )
        if not active_routes:
            raise ValueError("no active routes in Silver selection")

        fit_df = silver_df.filter(spec.includes_fit(F.col("dt"))).select(
            "route_code",
            "direction",
            "vehicle_id",
            "device_epoch_s",
            "s_bus_m",
            "derived_speed_kmh",
            "dt",
        )

        sc = spark.sparkContext
        engines = {name: sc.accumulator(0) for name in ("cpp_native", "python")}
        bc_shapes = sc.broadcast(shape_len_map)
        bc_stations = sc.broadcast(stations_map)
        fit_end = args.fit_end_date

        by_route = fit_df.rdd.map(
            lambda r: (
                str(r["route_code"]),
                (
                    int(r["vehicle_id"]),
                    str(r["direction"]),
                    float(r["device_epoch_s"]),
                    float(r["s_bus_m"]),
                    str(r["dt"]),
                ),
            )
        )
        route_markers = sc.parallelize(active_routes, min(len(active_routes), args.partitions)).map(
            lambda r: (r, None)
        )
        matrix_rdd = (
            by_route.union(route_markers)
            .groupByKey(min(len(active_routes), args.partitions))
            .flatMap(
                lambda pair: build_route_baseline_spark(
                    pair[0],
                    (x for x in pair[1] if x is not None),
                    bc_shapes.value,
                    bc_stations.value,
                    fit_end, lambda name: engines[name].add(1),
                )
            )
        )

        gold_schema = spark_schema(BASELINE)

        gold_root = f"{gold_root_prefix}/snapshot={args.snapshot}"
        build_id = uuid4().hex
        gold_data_path = f"{gold_root}/builds/{build_id}/data"
        gold_df = spark.createDataFrame(matrix_rdd, gold_schema)
        gold_df.coalesce(min(4, args.partitions)).write.mode("errorifexists").parquet(gold_data_path)

        written_df = spark.read.parquet(gold_data_path)
        row_count = written_df.count()
        tier_rows = written_df.groupBy("quality_tier").count().collect()
        tier_counts = {int(r["quality_tier"]): int(r["count"]) for r in tier_rows}

        validate_counts(tier_counts, row_count, range(4))

        manifest = {
            "schema_version": "gold-baseline.v1",
            "snapshot_id": args.snapshot,
            "build_id": build_id,
            "reference_sha256": source["reference_sha256"],
            "fit_end_date": args.fit_end_date,
            "train_end_date": TRAIN_SPLIT_END_DATE,
            "test_start_date": TEST_SPLIT_START_DATE,
            "routes": active_routes,
            "row_count": row_count,
            "tier_counts": tier_counts,
            "gold_data_path": gold_data_path,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "published_at": datetime.now(timezone.utc).isoformat(),
        }
        manifest = stage_manifest("baseline", spec, [k for k, counter in engines.items() if counter.value], **manifest)
        publish_gold(spark, gold_root, build_id, encoded(manifest))
        print("GOLD_RESULT=" + json.dumps(manifest), flush=True)
        return manifest
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
