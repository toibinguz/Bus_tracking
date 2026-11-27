"""Pure Python + NumPy PySpark helpers for HDFS Silver -> Gold Baseline."""

from __future__ import annotations

from collections import defaultdict
from itertools import groupby
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

import numpy as np

from config.system_config import TRAIN_SPLIT_END_DATE
from core_cpp.native_bridge import (
    build_route_baseline_native,
    is_native_available,
)
from modules.eta.baseline.baseline_core import (
    GOLD_BASELINE_COLUMNS,
    SampleTuple,
    StationTuple,
    build_route_baseline_rows,
    extract_fit_segment_samples,
)

__all__ = [
    "GOLD_BASELINE_COLUMNS",
    "aggregate_route_baseline",
    "build_reference_lookup",
    "build_route_baseline_spark",
    "extract_partition_samples",
]


def build_reference_lookup(
    reference: Mapping[str, Any],
) -> Tuple[Dict[Tuple[str, str], float], Dict[Tuple[str, str], List[StationTuple]]]:
    """Build (shape_len_map, stations_map) keyed by (route_code, direction) from reference.json."""
    routes: Dict[str, str] = {str(k): str(v) for k, v in reference["routes"].items()}
    shape_len_map: Dict[Tuple[str, str], float] = {}
    for route_id_str, dirs in reference["shapes"].items():
        r_code = routes.get(str(route_id_str))
        if not r_code:
            continue
        for direction, points in dirs.items():
            shape_len_map[(r_code, str(direction))] = max(
                (float(pt[3]) for pt in points), default=0.0
            )

    raw_stations: Dict[Tuple[str, str], List[StationTuple]] = defaultdict(list)
    for st in reference["stations"]:
        r_code = str(st.get("route_code") or routes.get(str(st["route_id"]), ""))
        if not r_code:
            continue
        raw_stations[(r_code, str(st["direction"]))].append(
            (
                int(st["station_order"]),
                int(st["station_id"]),
                str(st["station_name"]),
                float(st["cum_distance_m"]),
            )
        )
    stations_map = {
        key: sorted(items, key=lambda item: item[0])
        for key, items in raw_stations.items()
    }
    return shape_len_map, stations_map


def extract_partition_samples(
    sorted_rows: Iterable[Tuple[Tuple[str, str, int, float], Mapping[str, Any]]],
    shape_len_map: Mapping[Tuple[str, str], float],
    stations_map: Mapping[Tuple[str, str], List[StationTuple]],
    fit_end_date: str,
) -> Iterable[Tuple[str, Tuple[Any, ...]]]:
    """Run SSOT trip segmentation & bracketed crossing on sorted (route_code, direction, vehicle_id) groups."""
    for (route_code, direction, _vehicle_id), group in groupby(
        sorted_rows, key=lambda pair: pair[0][:3]
    ):
        full_st_list = stations_map.get((route_code, direction), [])
        if not full_st_list:
            continue
        shape_len_m = float(shape_len_map.get((route_code, direction), 0.0))
        pings_tuples = [
            (
                str(row["dt"]),
                float(row["device_epoch_s"]),
                float(row["s_bus_m"]),
                row.get("derived_speed_kmh"),
            )
            for _, row in group
        ]
        samples = extract_fit_segment_samples(
            pings_tuples, shape_len_m, full_st_list, fit_end_date
        )
        for ord_a, ord_b, day_type, hr_slot, tt, seg_dist in samples:
            yield (
                route_code,
                (direction, ord_a, ord_b, day_type, hr_slot, tt, seg_dist),
            )


def aggregate_route_baseline(
    route_code: str,
    sample_iter: Iterable[Optional[Tuple[Any, ...]]],
    stations_map: Mapping[Tuple[str, str], List[StationTuple]],
) -> List[Tuple[Any, ...]]:
    """Group executor samples by direction and emit 4-tier Gold baseline matrix rows."""
    samples_by_dir: Dict[str, List[SampleTuple]] = defaultdict(list)
    for item in sample_iter:
        if item is None:
            continue
        d_str, ord_a, ord_b, day_type, hr_slot, tt, seg_dist = item
        samples_by_dir[str(d_str)].append(
            (int(ord_a), int(ord_b), int(day_type), int(hr_slot), float(tt), float(seg_dist))
        )
    stations_by_dir = {
        d_str: stations_map.get((route_code, d_str), [])
        for d_str in ("go", "re")
    }
    rows, _ = build_route_baseline_rows(route_code, stations_by_dir, samples_by_dir)
    return rows


def build_route_baseline_spark(
    route_code: str,
    rows_iter: Iterable[Tuple[int, str, float, float, str]],
    shape_len_map: Mapping[Tuple[str, str], float],
    stations_map: Mapping[Tuple[str, str], List[StationTuple]],
    fit_end_date: str,
) -> List[Tuple[Any, ...]]:
    """Compute Gold baseline rows for 1 route using C++17 native kernel with Python SSOT fallback."""
    raw_rows = list(rows_iter)
    st_go = stations_map.get((route_code, "go"), [])
    st_re = stations_map.get((route_code, "re"), [])
    if is_native_available() and raw_rows:
        raw_rows.sort(key=lambda x: (x[0], 0 if x[1] == "go" else 1, x[2]))
        v_ids = np.array([r[0] for r in raw_rows], dtype=np.int32)
        d_ints = np.array([0 if r[1] == "go" else 1 for r in raw_rows], dtype=np.int32)
        epochs = np.array([r[2] for r in raw_rows], dtype=np.float64)
        s_vals = np.array([r[3] for r in raw_rows], dtype=np.float64)
        cells = build_route_baseline_native(
            float(shape_len_map.get((route_code, "go"), 0.0)),
            st_go,
            float(shape_len_map.get((route_code, "re"), 0.0)),
            st_re,
            v_ids,
            d_ints,
            epochs,
            s_vals,
            fit_end_date=fit_end_date,
            train_end_date=TRAIN_SPLIT_END_DATE,
        )
        if cells is not None:
            return [
                (
                    route_code,
                    c["direction"],
                    c["from_station_order"],
                    c["to_station_order"],
                    c["from_station_id"],
                    c["to_station_id"],
                    c["from_station_name"],
                    c["to_station_name"],
                    c["segment_length_m"],
                    c["day_type"],
                    c["hour_slot"],
                    c["sample_count"],
                    c["quality_tier"],
                    c["tt_p10_sec"],
                    c["tt_p50_sec"],
                    c["tt_p90_sec"],
                    c["tt_mean_sec"],
                    c["tt_std_sec"],
                )
                for c in cells
            ]

    samples_by_dir: Dict[str, List[SampleTuple]] = defaultdict(list)
    by_vd: Dict[Tuple[int, str], List[Tuple[str, float, float, None]]] = defaultdict(list)
    for vid, d_str, ep, s_m, dt_str in raw_rows:
        by_vd[(int(vid), str(d_str))].append((str(dt_str), float(ep), float(s_m), None))
    for (_vid, d_str), pings in by_vd.items():
        pings.sort(key=lambda p: p[1])
        full_st = stations_map.get((route_code, d_str), [])
        if not full_st:
            continue
        samples_by_dir[d_str].extend(
            extract_fit_segment_samples(
                pings, float(shape_len_map.get((route_code, d_str), 0.0)), full_st, fit_end_date
            )
        )
    rows, _ = build_route_baseline_rows(
        route_code, {"go": st_go, "re": st_re}, samples_by_dir
    )
    return rows


def main():
    """PySpark entrypoint: HDFS Silver Parquet -> HDFS Gold Baseline Matrix."""
    import argparse
    from datetime import date, datetime, timezone
    import json
    from pathlib import Path
    import sys
    import time
    from uuid import uuid4

    from pyspark.sql import SparkSession, functions as F
    from pyspark.sql.types import DoubleType, IntegerType, StringType, StructField, StructType

    root = Path(__file__).resolve().parents[3]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from config.system_config import BASELINE_FIT_END_DATE, TEST_SPLIT_START_DATE, TRAIN_SPLIT_END_DATE
    from modules.lakehouse.hdfs.hf_bronze import digest, encoded

    hdfs_root = "hdfs://namenode:8020/bus-eta/v1"
    publications = hdfs_root + "/_published/history_snapshots"
    gold_root_prefix = hdfs_root + "/gold/agg_segment_travel_times"

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, help="Published 64-hex Silver snapshot ID")
    parser.add_argument("--fit-end-date", default=BASELINE_FIT_END_DATE)
    parser.add_argument("--routes", nargs="+", help="Optional subset of route_code values")
    parser.add_argument("--partitions", type=int, default=16)
    args = parser.parse_args()

    if len(args.snapshot) != 64 or any(c not in "0123456789abcdef" for c in args.snapshot):
        parser.error("invalid snapshot ID")
    date.fromisoformat(args.fit_end_date)
    if args.fit_end_date > TRAIN_SPLIT_END_DATE:
        parser.error("fit-end-date must not extend past TRAIN_SPLIT_END_DATE")
    if args.partitions < 1:
        parser.error("partitions must be positive")

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

    def write_atomic(path: str, content: bytes) -> None:
        fs.mkdirs(jpath(path.rsplit("/", 1)[0]))
        temp = path + ".tmp-" + str(uuid4())
        stream = fs.create(jpath(temp), True)
        try:
            stream.write(bytearray(content))
        finally:
            stream.close()
        if fs.exists(jpath(path)):
            fs.delete(jpath(path), False)
        if not fs.rename(jpath(temp), jpath(path)):
            raise RuntimeError("failed to rename atomic HDFS file: " + path)

    try:
        pub_path = f"{publications}/{args.snapshot}.json"
        if not fs.exists(jpath(pub_path)):
            raise ValueError("published snapshot not found: " + pub_path)
        source = json.loads(read_bytes(pub_path))
        if source.get("snapshot_id") != args.snapshot:
            raise ValueError("snapshot ID mismatch in publication metadata")
        ref_raw = read_bytes(source["reference_path"])
        if digest(ref_raw) != source["reference_sha256"]:
            raise ValueError("reference content hash mismatch")
        reference = json.loads(ref_raw)
        shape_len_map, stations_map = build_reference_lookup(reference)

        silver_df = spark.read.parquet(source["silver_path"])
        if args.routes:
            silver_df = silver_df.filter(F.col("route_code").isin(args.routes))

        active_routes = sorted(
            r.route_code
            for r in silver_df.select("route_code").distinct().collect()
            if r.route_code is not None
        )
        if not active_routes:
            raise ValueError("no active routes in Silver selection")

        fit_df = silver_df.filter(F.col("dt") <= args.fit_end_date).select(
            "route_code",
            "direction",
            "vehicle_id",
            "device_epoch_s",
            "s_bus_m",
            "derived_speed_kmh",
            "dt",
        )

        sc = spark.sparkContext
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
                    fit_end,
                )
            )
        )

        gold_schema = StructType(
            [
                StructField("route_code", StringType(), False),
                StructField("direction", StringType(), False),
                StructField("from_station_order", IntegerType(), False),
                StructField("to_station_order", IntegerType(), False),
                StructField("from_station_id", IntegerType(), False),
                StructField("to_station_id", IntegerType(), False),
                StructField("from_station_name", StringType(), True),
                StructField("to_station_name", StringType(), True),
                StructField("segment_length_m", DoubleType(), False),
                StructField("day_type", IntegerType(), False),
                StructField("hour_slot", IntegerType(), False),
                StructField("sample_count", IntegerType(), False),
                StructField("quality_tier", IntegerType(), False),
                StructField("tt_p10_sec", DoubleType(), False),
                StructField("tt_p50_sec", DoubleType(), False),
                StructField("tt_p90_sec", DoubleType(), False),
                StructField("tt_mean_sec", DoubleType(), False),
                StructField("tt_std_sec", DoubleType(), False),
            ]
        )

        gold_root = f"{gold_root_prefix}/snapshot={args.snapshot}"
        gold_data_path = f"{gold_root}/data"
        gold_df = spark.createDataFrame(matrix_rdd, gold_schema)
        gold_df.coalesce(min(4, args.partitions)).write.mode("overwrite").parquet(gold_data_path)

        written_df = spark.read.parquet(gold_data_path)
        row_count = written_df.count()
        tier_rows = written_df.groupBy("quality_tier").count().collect()
        tier_counts = {int(r["quality_tier"]): int(r["count"]) for r in tier_rows}

        manifest = {
            "schema_version": "gold-baseline.v1",
            "snapshot_id": args.snapshot,
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
        write_atomic(f"{gold_root}/manifest.json", encoded(manifest))
        print("GOLD_RESULT=" + json.dumps(manifest), flush=True)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
