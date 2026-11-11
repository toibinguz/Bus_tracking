"""Independent readback for the closed-fixture staging evidence run."""

from __future__ import annotations

import json

from pyspark.sql import SparkSession, functions as F


JOB_KEY = "2a86ec9d93685ebb66d71872847796156ba1c87475e140905e3294d7e38facb3"
ROOT = "hdfs://namenode:8020/bus-eta/v1"
SILVER = (
    f"{ROOT}/silver/route_projected_telemetry/provenance=replayed_observed/"
    f"dt=2026-10-08/hr=13/_runs/job={JOB_KEY}"
)
GOLD = f"{ROOT}/gold/route_speed_hourly/provenance=replayed_observed/dt=2026-10-08/_runs/job={JOB_KEY}"


spark = SparkSession.builder.appName("bus-eta-hdfs-p2-staged-readback").getOrCreate()
try:
    silver = spark.read.parquet(SILVER)
    gold = spark.read.parquet(GOLD)
    silver_summary = silver.agg(
        F.count(F.lit(1)).alias("silver_rows"),
        F.countDistinct("event_id").alias("distinct_event_ids"),
        F.sum(F.when(F.col("cross_track_m") <= 35, 1).otherwise(0)).alias("within_corridor"),
        F.min("derived_speed_kmh").alias("min_speed_kmh"),
    ).first().asDict()
    from_silver = [
        row.asDict(recursive=True)
        for row in silver.groupBy("route_code").agg(
            F.count(F.lit(1)).alias("ping_count"),
            F.count("derived_speed_kmh").alias("speed_sample_count"),
            F.round(F.avg("derived_speed_kmh"), 2).alias("avg_speed_kmh"),
        ).orderBy("route_code").collect()
    ]
    print(json.dumps({"silver_schema": silver.schema.jsonValue()}, sort_keys=True))
    print(json.dumps({"silver_summary": silver_summary}, sort_keys=True))
    print(json.dumps({"from_silver": from_silver}, sort_keys=True))
    print(json.dumps({"gold_rows": [row.asDict(recursive=True) for row in gold.orderBy("route_code").collect()]}, sort_keys=True))
finally:
    spark.stop()
