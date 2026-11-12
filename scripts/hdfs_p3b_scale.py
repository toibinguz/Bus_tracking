"""Bounded, isolated HDFS scale/replay mechanics experiment (SPEC-42)."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import socket
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from module_2_big_data_storage_and_lakehouse.step_2_4_hdfs_history.contract import canonical_event_id

ROOT = "hdfs://namenode:8020/bus-eta/v1/experiments/p3b/"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def synthetic_event(source, tile, seed, run):
    value = dict(source)
    # Every vehicle tile retains the original time differences and GPS values.
    value.update(provenance="synthetic_scale", source_window_id=f"{run}-tile-{tile}",
                 vehicle_id=seed * 10**12 + tile * 10**8 + int(source["vehicle_id"]), plate="SYNTHETIC")
    value["event_id"] = canonical_event_id(
        source_name=f"synthetic_scale:{run}:{seed}", source_record_id=source["event_id"],
        route_id=value["route_id"], vehicle_id=value["vehicle_id"],
        observed_at_epoch_ms=value["observed_at_epoch_ms"], lat=value["lat"], lon=value["lon"])
    value["payload"] = {**source["payload"], "simulation_source_event_id": source["event_id"]}
    return value


def partition_summary(values):
    count, latitude_sum = 0, 0
    for line in values:
        row = json.loads(line)
        count += 1
        latitude_sum += float(row["lat"])
    yield (socket.gethostname(), count, latitude_sum)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="one recorded Bronze JSONL on HDFS")
    parser.add_argument("--run", required=True)
    parser.add_argument("--multiplier", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", args.run) or args.multiplier < 1 or args.seed < 1:
        parser.error("invalid run, multiplier or seed")
    if not args.source.startswith("hdfs://namenode:8020/bus-eta/v1/bronze/"):
        parser.error("source must be recorded HDFS Bronze")
    from pyspark.sql import SparkSession
    spark = (SparkSession.builder.appName("bus-eta-p3b-scale")
             .config("spark.hadoop.dfs.blocksize", 1048576).getOrCreate())
    started = time.monotonic()
    try:
        fs = spark._jvm.org.apache.hadoop.fs.FileSystem.get(spark._jsc.hadoopConfiguration())
        path = spark._jvm.org.apache.hadoop.fs.Path
        output = ROOT + args.run
        if fs.exists(path(output)):
            raise ValueError("immutable experiment run already exists")
        raw = bytes(spark.read.format("binaryFile").load(args.source).first().content)
        original = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line]
        unique = {row["event_id"]: row for row in original}
        if not unique or any(row["provenance"] not in ("observed", "replayed_observed") for row in original):
            raise ValueError("source must contain recorded observations")
        sources = [unique[key] for key in sorted(unique)]
        lines = [canonical(synthetic_event(row, tile, args.seed, args.run))
                 for tile in range(args.multiplier) for row in sources]
        encoded = ("\n".join(lines) + "\n").encode("utf-8")
        synthetic_path = output + "/provenance=synthetic_scale/bronze"
        spark.sparkContext.parallelize(lines, 2).coalesce(1).saveAsTextFile(synthetic_path)
        # A barrier stage needs two simultaneously occupied one-core executors.
        summaries = spark.sparkContext.textFile(synthetic_path, minPartitions=2).repartition(2).barrier().mapPartitions(partition_summary).collect()
        hosts = sorted({host for host, count, _ in summaries if count})
        if len(hosts) < 2 or sum(row[1] for row in summaries) != len(lines):
            raise RuntimeError("two-executor/count acceptance failed")
        actual_lat_sum = sum(row[2] for row in summaries)
        expected_lat_sum = sum(float(row["lat"]) for row in sources) * args.multiplier
        if abs(actual_lat_sum - expected_lat_sum) > 1e-5:
            raise RuntimeError("independent latitude checksum mismatch")
        replay_times = []
        replay_lines = [canonical({**row, "provenance": "replayed_observed"}) for row in original]
        for batch in range(3):
            if batch:
                time.sleep(0.1)
            replay_times.append(time.monotonic() - started)
            spark.sparkContext.parallelize(replay_lines, 1).saveAsTextFile(
                output + f"/provenance=replayed_observed/batch={batch}")
        replay = spark.read.json(output + "/provenance=replayed_observed/batch=*")
        replay_count, replay_distinct = replay.count(), replay.select("event_id").distinct().count()
        if replay_count != len(original) * 3 or replay_distinct != len(unique):
            raise RuntimeError("replay identity/count mismatch")
        files = fs.listStatus(path(synthetic_path))
        blocks = []
        for status in files:
            if str(status.getPath().getName()).startswith("part-"):
                for block in fs.getFileBlockLocations(status, 0, status.getLen()):
                    blocks.append({"length": block.getLength(), "hosts": list(block.getHosts())})
        if len(blocks) < 3 or any(len(set(block["hosts"])) < 2 for block in blocks):
            raise RuntimeError("three-block/two-DataNode acceptance failed")
        report = dict(status="passed", run=args.run, source=args.source,
                      source_sha256=hashlib.sha256(raw).hexdigest(), seed=args.seed,
                      multiplier=args.multiplier, source_rows=len(original), source_unique_events=len(unique),
                      synthetic_rows=len(lines), synthetic_bytes=len(encoded),
                      synthetic_sha256=hashlib.sha256(encoded).hexdigest(), block_size_bytes=1048576,
                      blocks=blocks, executor_summaries=summaries, executor_hosts=hosts,
                      latitude_sum=actual_lat_sum, expected_latitude_sum=expected_lat_sum,
                      replay_rows=replay_count, replay_unique_events=replay_distinct,
                      replay_batches=3, replay_minimum_pause_seconds=0.1, replay_start_offsets_seconds=replay_times,
                      elapsed_seconds=time.monotonic()-started, output=output,
                      interpretation="storage mechanics only; synthetic excluded from ETA accuracy; replay adds no unique history")
        spark.sparkContext.parallelize([canonical(report)], 1).saveAsTextFile(output + "/report")
        print("P3B_RESULT=" + canonical(report), flush=True)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
