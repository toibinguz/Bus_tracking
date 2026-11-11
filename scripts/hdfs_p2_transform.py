"""Run the bounded SPEC-35 Spark Bronze-to-Silver/Gold slice on HDFS."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from module_2_big_data_storage_and_lakehouse.step_2_4_hdfs_history.p2_transform import (
    canonical_json_bytes,
    p2_job_key,
    project_distinct_envelopes,
    sha256_hex,
    validate_envelope,
)


HDFS_ROOT = "hdfs://namenode:8020/bus-eta/v1"


def hdfs_bytes(spark: Any, path: str) -> bytes:
    rows = spark.read.format("binaryFile").load(path).select("content").collect()
    if len(rows) != 1:
        raise ValueError(f"expected exactly one HDFS file at {path}, found {len(rows)}")
    return bytes(rows[0]["content"])


def hdfs_text(spark: Any, path: str) -> str:
    return hdfs_bytes(spark, path).decode("utf-8")


def hdfs_exists(spark: Any, path: str) -> bool:
    jvm = spark.sparkContext._jvm
    filesystem = jvm.org.apache.hadoop.fs.FileSystem.get(spark.sparkContext._jsc.hadoopConfiguration())
    return bool(filesystem.exists(jvm.org.apache.hadoop.fs.Path(path)))


def hdfs_write_once(spark: Any, path: str, content: bytes) -> None:
    jvm = spark.sparkContext._jvm
    filesystem = jvm.org.apache.hadoop.fs.FileSystem.get(spark.sparkContext._jsc.hadoopConfiguration())
    target = jvm.org.apache.hadoop.fs.Path(path)
    if filesystem.exists(target):
        raise RuntimeError(f"immutable HDFS output already exists: {path}")
    stream = filesystem.create(target, False)
    try:
        stream.write(bytearray(content))
    finally:
        stream.close()


def read_json_lines(spark: Any, path: str) -> list[dict[str, Any]]:
    return [json.loads(row["value"]) for row in spark.read.text(path).collect()]


def hdfs_file_sha256(spark: Any, path: str) -> str:
    return sha256_hex(hdfs_bytes(spark, path))


def checkpoint_noop_or_raise(spark: Any, checkpoint_path: str) -> bool:
    if not hdfs_exists(spark, checkpoint_path):
        return False
    try:
        checkpoint = json.loads(hdfs_text(spark, checkpoint_path))
        for key in ("silver_path", "gold_path", "job_key"):
            if not checkpoint[key]:
                raise ValueError(key)
        spark.read.parquet(checkpoint["silver_path"]).limit(1).collect()
        spark.read.parquet(checkpoint["gold_path"]).limit(1).collect()
    except Exception as error:
        raise RuntimeError(f"checkpoint is invalid or output unreadable: {checkpoint_path}") from error
    print(json.dumps({"event": "p2_checkpoint_noop", "job_key": checkpoint["job_key"]}, sort_keys=True))
    return True


def silver_schema():
    from pyspark.sql.types import DoubleType, LongType, StringType, StructField, StructType

    return StructType(
        [
            StructField("event_id", StringType(), False),
            StructField("legacy_ping_id", LongType(), True),
            StructField("route_code", StringType(), False),
            StructField("route_id", LongType(), False),
            StructField("vehicle_id", LongType(), False),
            StructField("plate", StringType(), True),
            StructField("device_update_time", StringType(), False),
            StructField("device_epoch_s", DoubleType(), False),
            StructField("direction", StringType(), False),
            StructField("lat", DoubleType(), False),
            StructField("lon", DoubleType(), False),
            StructField("s_bus_m", DoubleType(), False),
            StructField("cross_track_m", DoubleType(), False),
            StructField("derived_speed_kmh", DoubleType(), True),
            StructField("source_window_id", StringType(), False),
            StructField("provenance", StringType(), False),
            StructField("device_epoch_ms", LongType(), False),
            StructField("ingested_at_epoch_ms", LongType(), False),
        ]
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    from pyspark.sql import SparkSession, functions as F

    spark = SparkSession.builder.appName("bus-eta-hdfs-p2").getOrCreate()
    try:
        bronze_bytes = hdfs_bytes(spark, args.bronze_path)
        reference_bytes = hdfs_bytes(spark, args.reference_path)
        fixture_manifest = json.loads(hdfs_text(spark, args.fixture_manifest_path))
        bronze_sha256 = sha256_hex(bronze_bytes)
        reference_sha256 = sha256_hex(reference_bytes)
        if bronze_sha256 != fixture_manifest["bronze_sha256"]:
            raise RuntimeError("Bronze hash does not match committed P2 fixture")
        if reference_sha256 != fixture_manifest["reference_sha256"]:
            raise RuntimeError("reference hash does not match committed P2 fixture")
        source_revision_sha256 = sha256(Path(__file__).read_bytes()).hexdigest()
        job_key = p2_job_key(
            bronze_path=args.bronze_path,
            bronze_sha256=bronze_sha256,
            source_window_id=fixture_manifest["source_window_id"],
            reference_sha256=reference_sha256,
            source_revision_sha256=source_revision_sha256,
        )
        checkpoint_path = f"{HDFS_ROOT}/_checkpoints/bronze_to_silver/{job_key}.json"
        if checkpoint_noop_or_raise(spark, checkpoint_path):
            return {"job_key": job_key, "noop": True}

        raw_values = read_json_lines(spark, args.bronze_path)
        envelopes = [validate_envelope(value) for value in raw_values]
        if len(envelopes) != int(fixture_manifest["raw_row_count"]):
            raise RuntimeError("Bronze row count does not match fixture")
        if {envelope.source_window_id for envelope in envelopes} != {fixture_manifest["source_window_id"]}:
            raise RuntimeError("Bronze source window differs from fixture")
        if {envelope.provenance for envelope in envelopes} != {"replayed_observed"}:
            raise RuntimeError("P2 requires replayed_observed Bronze fixture")

        duplicate_event_id = fixture_manifest["duplicate_event_id"]
        if sum(envelope.event_id == duplicate_event_id for envelope in envelopes) != 2:
            raise RuntimeError("fixture duplicate identity is absent")
        reference = json.loads(reference_bytes.decode("utf-8"))
        silver_rows, projection_diagnostics = project_distinct_envelopes(envelopes, reference)
        distinct_count = len({envelope.event_id for envelope in envelopes})
        if distinct_count != int(fixture_manifest["distinct_event_count"]):
            raise RuntimeError("distinct identity count does not match fixture")
        if len(silver_rows) != int(fixture_manifest["accepted_row_count"]):
            raise RuntimeError("projection accepted count does not match fixture")
        projected_by_id = {row["event_id"]: row for row in silver_rows}
        for expected in fixture_manifest["expected_projection"]:
            actual = projected_by_id.get(expected["event_id"])
            if actual is None or any(actual[field] != value for field, value in expected.items()):
                raise RuntimeError("projection differs from accepted P2 fixture")
        if any(row["cross_track_m"] > args.max_cross_track_m for row in silver_rows):
            raise RuntimeError("projection emitted out-of-corridor row")
        if any(row["derived_speed_kmh"] is not None and row["derived_speed_kmh"] < 0 for row in silver_rows):
            raise RuntimeError("projection emitted negative speed")

        dt, hr = fixture_manifest["dt"], fixture_manifest["hr"]
        provenance = "replayed_observed"
        silver_path = (
            f"{HDFS_ROOT}/silver/route_projected_telemetry/provenance={provenance}/"
            f"dt={dt}/hr={hr}/_runs/job={job_key}"
        )
        gold_path = f"{HDFS_ROOT}/gold/route_speed_hourly/provenance={provenance}/dt={dt}/_runs/job={job_key}"
        silver_df = spark.createDataFrame(silver_rows, schema=silver_schema())
        silver_df.write.mode("errorifexists").parquet(silver_path)
        validated_silver = spark.read.parquet(silver_path)
        accepted_count = validated_silver.count()
        if accepted_count != len(silver_rows):
            raise RuntimeError("Silver read-back count differs from write")
        gold_df = (
            validated_silver.withColumn("dt", F.lit(dt))
            .withColumn("hr", F.lit(hr))
            .groupBy("route_code", "dt", "hr", "provenance")
            .agg(
                F.count(F.lit(1)).alias("ping_count"),
                F.count("derived_speed_kmh").alias("speed_sample_count"),
                F.avg("derived_speed_kmh").alias("avg_speed_kmh"),
            )
        )
        gold_df.write.mode("errorifexists").parquet(gold_path)
        validated_gold = spark.read.parquet(gold_path)
        aggregate_rows = [row.asDict(recursive=True) for row in validated_gold.collect()]
        if len(aggregate_rows) != 1 or aggregate_rows[0]["ping_count"] != accepted_count:
            raise RuntimeError("Gold read-back aggregate differs from Silver")

        diagnostics = {"duplicate_event_id": len(envelopes) - distinct_count, **projection_diagnostics}
        checkpoint = {
            "accepted_row_count": accepted_count,
            "bronze_path": args.bronze_path,
            "bronze_sha256": bronze_sha256,
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
            "diagnostic_counts": diagnostics,
            "distinct_event_count": distinct_count,
            "fixture_manifest_path": args.fixture_manifest_path,
            "gold_path": gold_path,
            "gold_rows": aggregate_rows,
            "job_key": job_key,
            "raw_row_count": len(envelopes),
            "reference_path": args.reference_path,
            "reference_sha256": reference_sha256,
            "silver_path": silver_path,
            "source_revision_sha256": source_revision_sha256,
            "source_window_id": fixture_manifest["source_window_id"],
        }
        hdfs_write_once(spark, checkpoint_path, canonical_json_bytes(checkpoint))
        publish_path = f"{HDFS_ROOT}/_published/bronze_to_silver/{job_key}.json"
        hdfs_write_once(
            spark,
            publish_path,
            canonical_json_bytes({"checkpoint_path": checkpoint_path, "job_key": job_key}),
        )
        print(json.dumps({"event": "p2_completed", **checkpoint}, sort_keys=True))
        return checkpoint
    finally:
        spark.stop()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bronze-path", required=True)
    parser.add_argument("--reference-path", required=True)
    parser.add_argument("--fixture-manifest-path", required=True)
    parser.add_argument("--max-cross-track-m", type=float, required=True)
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
