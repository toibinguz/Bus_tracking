"""Pure Python + NumPy + C++17 native PySpark helpers for HDFS Silver -> Gold Causal Features."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from config.system_config import DEFAULT_URBAN_BUS_SPEED_KMPH, TZ_HANOI
from core_cpp.native_bridge import (
    extract_route_causal_features_native,
    is_native_available,
)
from modules.ingestion.projection.tomtom_incident_projector import (
    project_incidents_to_route_facts,
)
from modules.eta.baseline.baseline_core import (
    get_active_corridor_stations,
)
from modules.eta.features.causal_eta import (
    FEATURES,
    MAX_POSITION_AGE,
    CausalFeatures,
    Observation,
    RouteIncidentInterval,
)

GOLD_CAUSAL_FEATURE_COLUMNS: Tuple[str, ...] = FEATURES + (
    "route",
    "vehicle",
    "journey",
    "target",
    "split",
    "as_of",
    "eta_seconds",
    "bracket_before",
    "bracket_after",
    "crossing_epoch",
    "history_seconds",
)

SPLIT_NAMES = ("train", "validation", "test")

__all__ = [
    "GOLD_CAUSAL_FEATURE_COLUMNS",
    "RouteReferenceLookup",
    "build_route_feature_metadata",
    "extract_route_causal_features_partition",
]


class RouteReferenceLookup:
    """In-memory adapter implementing CausalFeatures' DataAccess contract without SQLite."""

    def __init__(
        self,
        *,
        route_code: str,
        route_id: int,
        route_idx: int,
        shapes_by_dir: Mapping[str, Sequence[Tuple[int, float, float, float]]],
        stations_by_dir: Mapping[str, Sequence[Tuple[int, int, str, float]]],
        baseline_rows: Iterable[Mapping[str, Any]],
    ):
        self._route_code = str(route_code)
        self._route_id = int(route_id)
        self._route_idx = int(route_idx)
        self._shapes = {str(d): list(pts) for d, pts in shapes_by_dir.items()}
        self._corridors = {
            str(d): get_active_corridor_stations(list(sts))
            for d, sts in stations_by_dir.items()
        }
        self._baseline_matrix: Dict[Tuple[Any, int, int, int, int, int], Tuple[float, float, float, float, float, int, float]] = {}
        self._bm_agg: Dict[int, List[float]] = {0: [0.0, 0.0], 1: [0.0, 0.0]}
        for row in baseline_rows:
            dir_int = 0 if str(row["direction"]).strip().lower() == "go" else 1
            val = (
                float(row["tt_p10_sec"]),
                float(row["tt_p50_sec"]),
                float(row["tt_p90_sec"]),
                float(row["tt_mean_sec"]),
                float(row["tt_std_sec"]),
                int(row["quality_tier"]),
                float(row["segment_length_m"]),
            )
            self._baseline_matrix[
                (
                    self._route_id,
                    dir_int,
                    int(row["from_station_order"]),
                    int(row["to_station_order"]),
                    int(row["day_type"]),
                    int(row["hour_slot"]),
                )
            ] = val
            self._bm_agg[dir_int][0] += float(row["segment_length_m"])
            self._bm_agg[dir_int][1] += float(row["tt_p50_sec"])

    def get_route_idx(self, route_id: int) -> Optional[int]:
        return self._route_idx if int(route_id) == self._route_id else None

    def get_shape_points(self, route_id: int, dir_str: str):
        return self._shapes.get(dir_str, []) if int(route_id) == self._route_id else []

    def get_corridor_stations(self, route_id: int, dir_str: str):
        return self._corridors.get(dir_str, []) if int(route_id) == self._route_id else []

    def get_route_profile(self, route_id: int, dir_str: str) -> Tuple[float, float, float]:
        dir_int = 0 if dir_str == "go" else 1
        corridor = self.get_corridor_stations(route_id, dir_str)
        if len(corridor) >= 2:
            corridor_len = max(100.0, corridor[-1][3] - corridor[0][3])
            spacing = round(corridor_len / max(1, len(corridor) - 1), 1)
        else:
            spacing = 0.0
        agg = self._bm_agg.get(dir_int)
        base_spd = round((agg[0] / agg[1]) * 3.6, 2) if agg and agg[1] > 0 else DEFAULT_URBAN_BUS_SPEED_KMPH
        pts = self.get_shape_points(route_id, dir_str)
        route_len = float(pts[-1][3]) if pts else 0.0
        return base_spd, spacing, route_len

    def get_baseline_cell(
        self, route_id: Any, dir_int: int, from_ord: int, to_ord: int, day_type: int, hour_slot: int
    ) -> Optional[Tuple[float, float, float, float, float, int, float]]:
        return self._baseline_matrix.get((self._route_id, dir_int, from_ord, to_ord, day_type, hour_slot))


def build_route_feature_metadata(
    reference: Mapping[str, Any],
    route_codes: Sequence[str],
    baseline_rows: Iterable[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Assemble serializable broadcast payload for Spark feature extraction executors."""
    code_to_id = {str(v): int(k) for k, v in reference["routes"].items()}
    route_idx_by_code = {rc: i for i, rc in enumerate(sorted(route_codes))}

    shapes_by_code: Dict[str, Dict[str, list]] = defaultdict(lambda: {"go": [], "re": []})
    for rid_str, dirs in reference["shapes"].items():
        rc = reference["routes"].get(str(rid_str))
        if rc not in route_idx_by_code:
            continue
        for d_str, pts in dirs.items():
            shapes_by_code[rc][str(d_str)] = [(int(p[0]), float(p[1]), float(p[2]), float(p[3])) for p in pts]

    stations_by_code: Dict[str, Dict[str, list]] = defaultdict(lambda: {"go": [], "re": []})
    for st in reference["stations"]:
        rc = str(st.get("route_code") or reference["routes"].get(str(st["route_id"]), ""))
        if rc not in route_idx_by_code:
            continue
        stations_by_code[rc][str(st["direction"])].append(
            (int(st["station_order"]), int(st["station_id"]), str(st["station_name"]), float(st["cum_distance_m"]))
        )
    for rc_dirs in stations_by_code.values():
        for d_str in rc_dirs:
            rc_dirs[d_str].sort(key=lambda item: item[0])

    baseline_by_code: Dict[str, list] = defaultdict(list)
    for row in baseline_rows:
        rc = str(row["route_code"]).strip()
        if rc in route_idx_by_code:
            baseline_by_code[rc].append(dict(row))

    return {
        "code_to_id": code_to_id,
        "route_idx_by_code": route_idx_by_code,
        "shapes_by_code": dict(shapes_by_code),
        "stations_by_code": dict(stations_by_code),
        "baseline_by_code": dict(baseline_by_code),
    }


def _baseline_cutoff_epoch(fit_end_date: str) -> float:
    d = datetime.fromisoformat(fit_end_date).replace(tzinfo=TZ_HANOI)
    return d.timestamp() + 86400.0


def extract_route_causal_features_partition(
    route_code: str,
    silver_rows: Iterable[Mapping[str, Any]],
    incident_intervals_by_dir: Mapping[int, Sequence[Tuple[float, float, float, float, float]]],
    meta: Mapping[str, Any],
    *,
    fit_end_date: str,
    validation_epoch: float,
    test_epoch: float,
    cadence_sec: float,
) -> List[Tuple[Any, ...]]:
    """Extract labeled 40-feature causal rows for 1 route using C++17 native kernel (or Python fallback)."""
    route_id = meta["code_to_id"].get(route_code)
    route_idx = meta["route_idx_by_code"].get(route_code)
    if route_id is None or route_idx is None:
        return []

    lookup = RouteReferenceLookup(
        route_code=route_code,
        route_id=route_id,
        route_idx=route_idx,
        shapes_by_dir=meta["shapes_by_code"].get(route_code, {}),
        stations_by_dir=meta["stations_by_code"].get(route_code, {}),
        baseline_rows=meta["baseline_by_code"].get(route_code, ()),
    )

    cutoff_ep = _baseline_cutoff_epoch(fit_end_date)
    by_dir_raw: Dict[int, List[Tuple[float, str, float, float, float]]] = {0: [], 1: []}
    for row in silver_rows:
        d_str = row.get("direction")
        if d_str not in ("go", "re"):
            continue
        stamp = row.get("device_epoch_s")
        if stamp is None:
            stamp = row.get("device_epoch")
        s_bus = row.get("s_bus_m")
        vid = row.get("vehicle_id")
        lat = row.get("lat")
        lon = row.get("lon")
        if stamp is None or s_bus is None or vid is None or lat is None or lon is None:
            continue
        plate = "".join(c for c in (row.get("plate") or "").upper() if c.isalnum()) or f"id:{vid}"
        by_dir_raw[int(d_str == "re")].append((float(stamp), plate, float(s_bus), float(lat), float(lon)))

    if is_native_available():
        obs_all = [
            (float(stamp), 0 if d_int == 0 else 1, plate, float(s_bus), float(lat), float(lon))
            for d_int in (0, 1)
            for stamp, plate, s_bus, lat, lon in by_dir_raw[d_int]
        ]
        obs_all.sort(key=lambda item: (item[0], item[1], item[2], item[4], item[5]))
        if not obs_all:
            return []
        veh_names = sorted({item[2] for item in obs_all})
        vmap = {name: idx for idx, name in enumerate(veh_names)}
        corridors_by_dir = {d: lookup.get_corridor_stations(route_id, ("go", "re")[d]) for d in (0, 1)}
        route_len_by_dir, bspd_by_dir, spac_by_dir = {}, {}, {}
        for d in (0, 1):
            bspd, spac, rlen = lookup.get_route_profile(route_id, ("go", "re")[d])
            bspd_by_dir[d] = bspd
            spac_by_dir[d] = spac
            route_len_by_dir[d] = rlen
        inc_sorted_map = {
            d: sorted(incident_intervals_by_dir.get(d, ()), key=lambda iv: iv[3])
            for d in (0, 1)
        }
        res = extract_route_causal_features_native(
            route_id_idx=route_idx,
            route_len_by_dir=route_len_by_dir,
            route_base_speed_by_dir=bspd_by_dir,
            route_spacing_by_dir=spac_by_dir,
            corridors_by_dir=corridors_by_dir,
            baseline_lookup=lookup,
            route_id_for_lookup=route_id,
            incidents_by_dir=inc_sorted_map,
            n_vehicles=len(veh_names),
            obs_epoch=np.array([item[0] for item in obs_all], dtype=np.float64),
            obs_dir=np.array([item[1] for item in obs_all], dtype=np.int32),
            obs_veh_idx=np.array([vmap[item[2]] for item in obs_all], dtype=np.int32),
            obs_s_bus=np.array([item[3] for item in obs_all], dtype=np.float64),
            baseline_cutoff_epoch=cutoff_ep,
            validation_epoch=validation_epoch,
            test_epoch=test_epoch,
            cadence_sec=cadence_sec,
        )
        if res is not None:
            arrs, _ = res
            n_out = len(arrs["eta_seconds"])
            out_rows: List[Tuple[Any, ...]] = []
            feats = arrs["features"]
            vh_idx = arrs["veh_idx"]
            j_arr = arrs["journey"]
            tgt = arrs["target"]
            spl = arrs["split"]
            as_of = arrs["as_of"]
            eta = arrs["eta_seconds"]
            bb = arrs["bracket_before"]
            ba = arrs["bracket_after"]
            cr = arrs["crossing_epoch"]
            hs = arrs["history_seconds"]
            for i in range(n_out):
                f_vals = tuple(None if np.isnan(v) else float(v) for v in feats[i])
                out_rows.append(
                    f_vals
                    + (
                        route_code,
                        veh_names[int(vh_idx[i])],
                        int(j_arr[i]),
                        int(tgt[i]),
                        SPLIT_NAMES[int(spl[i])],
                        float(as_of[i]),
                        float(eta[i]),
                        float(bb[i]),
                        float(ba[i]),
                        float(cr[i]),
                        float(hs[i]),
                    )
                )
            return out_rows

    # Pure Python fallback when native shared library is unavailable
    from itertools import groupby
    from modules.eta.training.causal_eta_training import (
        TrainingReplay,
    )

    replay = TrainingReplay(CausalFeatures(lookup))
    obs_all: List[Observation] = []
    for dir_int in (0, 1):
        for stamp, plate, s_bus, lat, lon in by_dir_raw[dir_int]:
            obs_all.append(Observation(route_id, dir_int, plate, "busmap", stamp, stamp, lat, lon, "", s_bus_m=s_bus))
    obs_all.sort(key=lambda o: (o.epoch, o.route_id, o.direction, o.vehicle, o.lat, o.lng))

    members: Dict[Tuple[int, int], Dict[str, float]] = defaultdict(dict)
    next_forecast: Dict[Tuple[int, int], float] = {}
    inc_ptrs: Dict[int, int] = {0: 0, 1: 0}
    active_inc: Dict[int, List[RouteIncidentInterval]] = {0: [], 1: []}
    inc_sorted = {
        d: [
            RouteIncidentInterval(iv[0], iv[1], iv[2], iv[3], iv[4])
            for iv in sorted(incident_intervals_by_dir.get(d, ()), key=lambda x: x[3])
            if iv[2] > 0.0
        ]
        for d in (0, 1)
    }

    last_time = -float("inf")
    for (now, r_id, dir_int), grp in groupby(obs_all, key=lambda o: (o.epoch, o.route_id, o.direction)):
        if now < cutoff_ep or now < last_time:
            raise ValueError("Silver partition timestamps overlap baseline fitting or arrive out of order")
        last_time = now
        key = (r_id, dir_int)
        batch = list(grp)
        active = {plate: t for plate, t in members[key].items() if now - t <= MAX_POSITION_AGE}
        active.update((row.vehicle, now) for row in batch)
        members[key] = active
        replay.snapshot(r_id, dir_int, now, batch, active, fleet_valid=True)
        if now < next_forecast.get(key, 0.0):
            continue
        next_forecast[key] = now + cadence_sec
        d_inc = inc_sorted[dir_int]
        ptr = inc_ptrs[dir_int]
        cur_active = active_inc[dir_int]
        while ptr < len(d_inc) and d_inc[ptr].crawled_epoch <= now:
            if d_inc[ptr].expires_epoch >= now:
                cur_active.append(d_inc[ptr])
            ptr += 1
        inc_ptrs[dir_int] = ptr
        if cur_active:
            cur_active = [iv for iv in cur_active if iv.expires_epoch >= now]
            active_inc[dir_int] = cur_active
        replay.engine.observe_incidents(r_id, dir_int, cur_active)
        for vehicle in sorted(active):
            replay.forecast_all(r_id, dir_int, vehicle, now)

    out_rows = []
    for row in replay.labeled(validation_epoch, test_epoch):
        f_vals = tuple(None if row["features"][f] is None else float(row["features"][f]) for f in FEATURES)
        lbl = row["label"]
        ego5 = row["speeds"].get("ego5")
        out_rows.append(
            f_vals
            + (
                route_code,
                str(row["vehicle"]),
                int(row["journey"]),
                int(row["target"]),
                str(row["split"]),
                float(row["as_of"]),
                float(row["eta_seconds"]),
                float(lbl["before_epoch"]),
                float(lbl["after_epoch"]),
                float(lbl["epoch"]),
                float(ego5["seconds"]) if ego5 else 0.0,
            )
        )
    return out_rows


def _date_epoch(day_str: str) -> float:
    from datetime import date

    d = date.fromisoformat(day_str)
    return datetime(d.year, d.month, d.day, tzinfo=TZ_HANOI).timestamp()


def main():
    """PySpark entrypoint: HDFS Silver + Gold Baseline -> HDFS Gold Causal Features (C++17 + fallback)."""
    import argparse
    from datetime import date, timezone
    import gc
    import json
    from pathlib import Path
    import sys
    import time
    from uuid import uuid4

    from pyspark.sql import SparkSession, functions as F
    from pyspark.sql.types import DoubleType, FloatType, LongType, StringType, StructField, StructType

    root = Path(__file__).resolve().parents[3]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from config.system_config import BASELINE_FIT_END_DATE, TEST_SPLIT_END_DATE, TEST_SPLIT_START_DATE
    from modules.lakehouse.hdfs.hf_bronze import digest, encoded

    hdfs_root = "hdfs://namenode:8020/bus-eta/v1"
    publications = hdfs_root + "/_published/history_snapshots"
    gold_baseline_root_prefix = hdfs_root + "/gold/agg_segment_travel_times"
    gold_features_root_prefix = hdfs_root + "/gold/causal_features"

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, help="Published 64-hex Silver/Gold snapshot ID")
    parser.add_argument("--from-day", default="2026-10-22")
    parser.add_argument("--to-day", default=TEST_SPLIT_END_DATE)
    parser.add_argument("--validation-start", default=None)
    parser.add_argument("--test-start", default=TEST_SPLIT_START_DATE)
    parser.add_argument("--no-valid", action="store_true")
    parser.add_argument("--forecast-every", type=float, default=120.0)
    parser.add_argument("--routes", nargs="+", help="Optional subset of route_code values")
    parser.add_argument("--partitions", type=int, default=16)
    args = parser.parse_args()

    if len(args.snapshot) != 64 or any(c not in "0123456789abcdef" for c in args.snapshot):
        parser.error("invalid snapshot ID")
    first_day = date.fromisoformat(args.from_day)
    last_day = date.fromisoformat(args.to_day)
    if first_day > last_day or args.forecast_every <= 0 or args.partitions < 1:
        parser.error("invalid date window or positive settings")

    validation_day = args.test_start if args.no_valid or not args.validation_start else args.validation_start
    validation_epoch = _date_epoch(validation_day) if len(validation_day) == 10 else datetime.fromisoformat(validation_day).timestamp()
    test_epoch = _date_epoch(args.test_start) if len(args.test_start) == 10 else datetime.fromisoformat(args.test_start).timestamp()

    started = time.monotonic()
    spark = (
        SparkSession.builder.appName("bus-eta-gold-causal-features")
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
        ref_raw = read_bytes(source["reference_path"])
        if digest(ref_raw) != source["reference_sha256"]:
            raise ValueError("reference content hash mismatch")
        reference = json.loads(ref_raw)

        gold_baseline_root = f"{gold_baseline_root_prefix}/snapshot={args.snapshot}"
        baseline_manifest_path = f"{gold_baseline_root}/manifest.json"
        if not fs.exists(jpath(baseline_manifest_path)):
            raise ValueError("Gold baseline manifest missing; run hdfs_build_gold_baseline.py first")
        baseline_manifest = json.loads(read_bytes(baseline_manifest_path))
        fit_end_date = baseline_manifest.get("fit_end_date", BASELINE_FIT_END_DATE)
        if date.fromisoformat(fit_end_date) >= first_day:
            raise ValueError("baseline fit overlaps causal feature extraction window")

        silver_df = spark.read.parquet(source["silver_path"]).filter(
            (F.col("dt") >= args.from_day) & (F.col("dt") <= args.to_day)
        )
        if args.routes:
            silver_df = silver_df.filter(F.col("route_code").isin(args.routes))

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
        baseline_rows = [
            row.asDict()
            for row in spark.read.parquet(f"{gold_baseline_root}/data")
            .filter(F.col("route_code").isin(active_routes))
            .select(*baseline_cols)
            .toLocalIterator()
        ]

        meta = build_route_feature_metadata(reference, active_routes, baseline_rows)
        del reference, baseline_rows
        gc.collect()

        incidents_by_route_dir: Dict[str, Dict[int, list]] = defaultdict(lambda: {0: [], 1: []})
        inc_obs_path = source["snapshot_path"].rstrip("/") + "/incident_observations"
        if source.get("incident_observations") and fs.exists(jpath(inc_obs_path)):
            raw_inc = [
                json.loads(r.raw_json)
                for r in spark.read.parquet(inc_obs_path).select("raw_json").collect()
            ]
            if raw_inc:
                inc_stations = {
                    rc: {
                        d: [(st[0], st[2], st[3]) for st in dirs.get(d, ())]
                        for d in dirs
                    }
                    for rc, dirs in meta["stations_by_code"].items()
                }
                fact_rows, _ = project_incidents_to_route_facts(
                    raw_inc, meta["shapes_by_code"], inc_stations
                )
                for fr in fact_rows:
                    d_int = 0 if fr[3] == "go" else 1
                    delay = float(fr[17] or 0.0)
                    if delay > 0.0:
                        incidents_by_route_dir[str(fr[2])][d_int].append(
                            (
                                float(fr[8]),
                                float(fr[9]),
                                delay,
                                float(fr[11]),
                                float(fr[12]),
                            )
                        )

        sc = spark.sparkContext
        bc_meta = sc.broadcast(meta)
        bc_inc = sc.broadcast(dict(incidents_by_route_dir))
        cadence_sec = float(args.forecast_every)

        grouped = (
            silver_df.select(
                "route_code", "direction", "vehicle_id", "plate", "device_epoch_s", "s_bus_m", "lat", "lon"
            )
            .rdd.map(lambda r: (str(r["route_code"]), r.asDict()))
            .groupByKey(args.partitions)
        )

        rows_rdd = grouped.flatMap(
            lambda pair: extract_route_causal_features_partition(
                pair[0],
                pair[1],
                bc_inc.value.get(pair[0], {0: [], 1: []}),
                bc_meta.value,
                fit_end_date=fit_end_date,
                validation_epoch=validation_epoch,
                test_epoch=test_epoch,
                cadence_sec=cadence_sec,
            )
        )

        schema = StructType(
            [StructField(f, FloatType(), True) for f in FEATURES]
            + [
                StructField("route", StringType(), False),
                StructField("vehicle", StringType(), False),
                StructField("journey", LongType(), False),
                StructField("target", LongType(), False),
                StructField("split", StringType(), False),
                StructField("as_of", DoubleType(), False),
                StructField("eta_seconds", DoubleType(), False),
                StructField("bracket_before", DoubleType(), False),
                StructField("bracket_after", DoubleType(), False),
                StructField("crossing_epoch", DoubleType(), False),
                StructField("history_seconds", DoubleType(), False),
            ]
        )

        out_root = f"{gold_features_root_prefix}/snapshot={args.snapshot}"
        out_data = f"{out_root}/data"
        feat_df = spark.createDataFrame(rows_rdd, schema)
        feat_df.repartition(min(args.partitions, len(active_routes)), "route").write.mode("overwrite").partitionBy("route").parquet(out_data)

        written = spark.read.parquet(out_data)
        total_rows = written.count()
        split_counts = {str(r["split"]): int(r["count"]) for r in written.groupBy("split").count().collect()}

        manifest = {
            "schema_version": "gold-causal-features.v1",
            "snapshot_id": args.snapshot,
            "fit_end_date": fit_end_date,
            "from_day": args.from_day,
            "to_day": args.to_day,
            "test_start": args.test_start,
            "no_valid": bool(args.no_valid),
            "forecast_every": cadence_sec,
            "routes": active_routes,
            "row_count": total_rows,
            "split_counts": split_counts,
            "columns": list(GOLD_CAUSAL_FEATURE_COLUMNS),
            "data_path": out_data,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "published_at": datetime.now(timezone.utc).isoformat(),
        }
        write_atomic(f"{out_root}/manifest.json", encoded(manifest))
        print("GOLD_FEATURES_RESULT=" + json.dumps(manifest), flush=True)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
