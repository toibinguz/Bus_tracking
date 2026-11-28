"""Filesystem/Arrow implementation of the historical pipeline stages."""
from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from functools import reduce
from itertools import groupby, islice
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from uuid import uuid4

import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq

from config.hardware_guard import check_memory_pressure, recommend_workers, set_process_below_normal_priority
from modules.ingestion.projection.tomtom_incident_projector import SILVER_INCIDENT_COLUMNS, _silver_incident_arrow_schema
from modules.lakehouse.hdfs.hf_bronze import atomic_write
from modules.lakehouse.pipeline import baseline, features, schema, silver
from modules.lakehouse.pipeline.spec import (
    MAX_BATCH_BYTES, MAX_SESSION_EVENTS, batch_identity, digest, encoded, stage_manifest, validate_counts,
)
from modules.lakehouse.serving_sync import sync_gold_to_serving_db


def arrow_schema(fields):
    return pa.schema([pa.field(name, kind, nullable) for name, kind, nullable in fields])


def chunks(rows, size=8192):
    rows = iter(rows)
    while batch := list(islice(rows, size)):
        yield batch


def part_rows(paths, columns=None):
    for path in paths:
        for batch in pq.ParquetFile(path).iter_batches(batch_size=8192, columns=columns):
            yield from batch.to_pylist()


def write_feature_part(path, rows):
    fields = arrow_schema(schema.CAUSAL)
    splits = Counter()
    with pq.ParquetWriter(path, fields) as writer:
        for batch in chunks(rows):
            table = pa.Table.from_pylist([dict(zip(fields.names, row)) for row in batch], schema=fields)
            writer.write_table(table)
            splits.update(table["split"].to_pylist())
    return splits


def parquet_count(path):
    return sum(pq.ParquetFile(p).metadata.num_rows for p in path.rglob("*.parquet"))


def new_build(root):
    build = root / "builds" / uuid4().hex
    build.mkdir(parents=True)
    return build


def publish(build, manifest):
    content = encoded(manifest)
    atomic_write(build / "manifest.json", content)
    atomic_write(build.parent.parent / "manifest.json", content)
    return manifest


class LocalAdapter:
    def __init__(self, raw, lakehouse, reference, static_db, serving_db, dataset, workers, max_route_events=None):
        self.raw = raw
        self.root = lakehouse
        self.reference = reference
        self.static_db = static_db
        self.serving_db = serving_db
        self.dataset = dataset
        if max_route_events is not None and max_route_events < 1:
            raise ValueError("max_route_events must be positive")
        self.max_route_events = max_route_events
        set_process_below_normal_priority()
        self.workers = recommend_workers(workers, per_worker_ram_gb=0.6, min_free_ram_gb=1.5, max_cpu_frac=0.75)

    def pin(self, product, inputs):
        if product == "silver" and "baseline" in inputs:
            path = Path(inputs["baseline"]["silver_manifest_path"])
        else:
            directory = self.root / ("silver" if product == "silver" else "gold/agg_segment_travel_times")
            path = directory / "manifest.json"
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def pinned_reference(source):
        content = (Path(source["snapshot_path"]) / "reference.json").read_bytes()
        if digest(content) != source["reference_sha256"]:
            raise ValueError("reference hash mismatch")
        return json.loads(content)

    def silver(self, spec, inputs):
        build = new_build(self.root / "silver")
        output = build / "route_projected_telemetry"
        output.mkdir()
        counts = Counter()
        engines = set()
        batches = []
        with TemporaryDirectory(dir=build) as tmp, closing(sqlite3.connect(Path(tmp) / "events.db")) as db:
            db.execute("PRAGMA temp_store=FILE")
            db.execute("CREATE TABLE events(route INTEGER, vehicle INTEGER, stamp INTEGER, event TEXT, value TEXT)")
            db.execute("CREATE TABLE incidents(id TEXT, raw TEXT, batch TEXT, PRIMARY KEY(raw,batch)) WITHOUT ROWID")
            with (build / "rejects.jsonl").open("wb") as rejects, (build / "incident_rejects.jsonl").open("wb") as incident_rejects:
                for path in sorted(self.raw.glob("*/*/*.jsonl")):
                    category = path.parent.name
                    if category not in ("bus", "incidents", "traffic"):
                        continue
                    logical_path = "raw_data/" + path.relative_to(self.raw).as_posix()
                    # A batch is the transport unit; never accumulate a day's raw files.
                    with path.open("rb") as stream:
                        raw = stream.read(MAX_BATCH_BYTES + 1)
                    if len(raw) > MAX_BATCH_BYTES:
                        raise ValueError("raw batch exceeds byte limit: " + logical_path)
                    sha = digest(raw)
                    bid = batch_identity(self.dataset, logical_path, sha)
                    batches.append(dict(batch_id=bid, path=logical_path, content_sha256=sha, category=category))
                    if category == "traffic":
                        continue
                    for kind, row in silver.normalize_batch(category, raw, bid, self.reference):
                        counts["raw_" + category] += 1
                        if kind == "reject":
                            (rejects if category == "bus" else incident_rejects).write(encoded(row) + b"\n")
                            counts["reject_" + category] += 1
                        elif category == "bus":
                            key, _ = silver.ordered_event(row)
                            db.execute("INSERT INTO events VALUES(?,?,?,?,?)", (*key, encoded(row).decode()))
                        else:
                            db.execute("INSERT OR IGNORE INTO incidents VALUES(?,?,?)",
                                       (str(json.loads(row["raw_json"])["incident_id"]), row["raw_json"], bid))
                    db.commit()
                if not any(b["category"] == "bus" for b in batches):
                    raise ValueError("no bus batches in selected input")

                # event_id encodes route, vehicle and observed_ms. This external sort
                # makes duplicates adjacent AND delivers the complete vehicle stream.
                ordered = db.execute("SELECT event,value FROM events ORDER BY route,vehicle,stamp,event")
                with (build / "event_lineage.jsonl").open("wb") as lineage, (build / "sessions.jsonl").open("wb") as sessions:
                    def unique_events():
                        for _, group in groupby(ordered, key=lambda r: r[0]):
                            row = reduce(silver.merge_bus, (silver.event_pair(json.loads(v))[1] for _, v in group))
                            lineage.write(encoded(row) + b"\n")
                            counts["unique"] += 1
                            yield silver.ordered_event(row)

                    def projected_rows():
                        def project_one(session_args):
                            route_id, vehicle_id, rows = session_args
                            return silver.project_vehicle_session(route_id, vehicle_id, rows, self.reference, spec=spec)

                        def iter_projected():
                            sessions_iter = silver.iter_vehicle_sessions(unique_events(), MAX_SESSION_EVENTS)
                            if self.workers > 1:
                                silver._get_reference_cache(self.reference)
                                with ThreadPoolExecutor(self.workers) as pool:
                                    for session_chunk in chunks(sessions_iter, max(self.workers * 16, 64)):
                                        yield from pool.map(project_one, session_chunk)
                            else:
                                for route_id, vehicle_id, rows in sessions_iter:
                                    yield silver.project_vehicle_session(route_id, vehicle_id, rows, self.reference, spec=spec)

                        for session in iter_projected():
                            sessions.write(encoded({k: session[k] for k in ("route_id", "vehicle_id", "session_start_ms",
                                                                            "session_end_ms", "input_events")}) + b"\n")
                            engines.add(session["engine"])
                            for rejected in session["rejected"]:
                                rejects.write(encoded(rejected) + b"\n")
                                counts["projection_reject"] += 1
                            yield from session["rows"]

                    fields = arrow_schema(schema.SILVER + (("dt", "string", True),))
                    for index, rows in enumerate(chunks(projected_rows(), 65536)):
                        check_memory_pressure(label="local_silver")
                        table = pa.Table.from_pylist(rows, schema=fields)
                        ds.write_dataset(table, output, format="parquet", partitioning=["route_code", "dt"],
                                         partitioning_flavor="hive", basename_template=f"part-{index}-{{i}}.parquet",
                                         existing_data_behavior="overwrite_or_ignore")
                        counts["accepted"] += len(rows)

            # Store each canonical observation once, with all its source batches.
            obs_schema = pa.schema([("observation_id", pa.string()), ("raw_json", pa.string()),
                                    ("batch_ids", pa.list_(pa.string()))])
            obs_dir = build / "incident_observations"
            obs_dir.mkdir()
            with pq.ParquetWriter(obs_dir / "part.parquet", obs_schema) as writer:
                ordered = db.execute("SELECT raw,batch FROM incidents ORDER BY id,raw,batch")
                observations = (dict(raw_json=raw, observation_id=digest(raw.encode()), batch_ids=[b for _, b in group])
                                for raw, group in groupby(ordered, key=lambda r: r[0]))
                for rows in chunks(observations):
                    writer.write_table(pa.Table.from_pylist(rows, schema=obs_schema))
                    counts["observations"] += len(rows)

        if parquet_count(output) != counts["accepted"] or counts["accepted"] + counts["projection_reject"] != counts["unique"]:
            raise ValueError("Silver output row accounting mismatch")
        codes = sorted(p.name.split("=", 1)[1] for p in output.glob("route_code=*"))
        meta = features.build_route_feature_metadata(self.reference, codes, [], codes)
        facts_dir = build / "fact_route_tomtom_incidents"
        facts_dir.mkdir()
        incident_schema = _silver_incident_arrow_schema()
        observations = (json.loads(r["raw_json"]) for r in part_rows([obs_dir / "part.parquet"]))
        for index, facts in enumerate(features.incident_fact_batches(observations, meta)):
            if not facts:
                continue
            table = pa.Table.from_pylist([dict(zip(SILVER_INCIDENT_COLUMNS, f)) for f in facts], schema=incident_schema)
            ds.write_dataset(table, facts_dir, format="parquet", partitioning=["route_code"], partitioning_flavor="hive",
                             basename_template=f"part-{index}-{{i}}.parquet", existing_data_behavior="overwrite_or_ignore")
        fact_count = parquet_count(facts_dir)
        atomic_write(build / "reference.json", encoded(self.reference))
        return publish(build, stage_manifest("silver", spec, engines, build_id=build.name, snapshot_id=build.name,
            silver_path=str(output), snapshot_path=str(build), source_manifests=batches,
            reference_sha256=digest(encoded(self.reference)), accepted_bus_rows=counts["accepted"],
            raw_bus_rows=counts["raw_bus"], unique_bus_events=counts["unique"],
            rejected_bus_normalize=counts["reject_bus"], incident_observations=counts["observations"],
            rejected_rows=counts["reject_bus"] + counts["projection_reject"],
            raw_incident_rows=counts["raw_incidents"], rejected_incidents=counts["reject_incidents"],
            duplicate_bus_observations=counts["raw_bus"] - counts["reject_bus"] - counts["unique"],
            incident_facts_path=str(facts_dir), incident_fact_rows=fact_count))

    def check_route_size(self, parts):
        if self.max_route_events is not None:
            total = sum(pq.ParquetFile(p).metadata.num_rows for p in parts)
            if total > self.max_route_events:
                raise ValueError(f"route has {total} rows, exceeding local limit {self.max_route_events}")

    def baseline(self, spec, inputs):
        source = inputs["silver"]
        routes = sorted(Path(source["silver_path"]).glob("route_code=*"))
        if not routes:
            raise ValueError("no Silver routes for baseline")
        shapes, stations = baseline.build_reference_lookup(self.pinned_reference(source))
        build = new_build(self.root / "gold" / "agg_segment_travel_times")
        data = build / "data"
        data.mkdir()
        fields = arrow_schema(schema.BASELINE)

        def write_route(route):
            code = route.name.split("=", 1)[1]
            parts = sorted(p for p in route.glob("dt=*/*.parquet") if spec.includes_fit(p.parent.name[3:]))
            self.check_route_size(parts)
            columns = ["vehicle_id", "direction", "device_epoch_s", "s_bus_m"]
            rows = ((r["vehicle_id"], r["direction"], r["device_epoch_s"], r["s_bus_m"], p.parent.name[3:])
                    for p in parts for r in part_rows([p], columns))
            engines = set()
            cells = baseline.compute_route_baseline(code, rows, shapes, stations, spec.fit_end_date, engines.add)
            table = pa.Table.from_pylist([dict(zip(fields.names, row)) for row in cells], schema=fields)
            pq.write_table(table, data / f"part-{code}.parquet")
            return Counter(table["quality_tier"].to_pylist()), engines

        tiers, engines = Counter(), set()
        with ThreadPoolExecutor(self.workers) as pool:
            for counts, used in pool.map(write_route, routes):
                check_memory_pressure(label="local_baseline")
                tiers.update(counts)
                engines.update(used)
        total = parquet_count(data)
        validate_counts(tiers, total, range(4))
        return publish(build, stage_manifest("baseline", spec, engines, build_id=build.name,
            snapshot_id=source["snapshot_id"], reference_sha256=source["reference_sha256"], fit_end_date=spec.fit_end_date,
            silver_manifest_path=str(Path(source["snapshot_path"]) / "manifest.json"),
            routes=[r.name.split("=",1)[1] for r in routes], row_count=total, tier_counts=tiers, gold_data_path=str(data)))

    def features(self, spec, inputs):
        source, base = inputs["silver"], inputs["baseline"]
        build = new_build(self.root / "gold" / "causal_features")
        data = build / "features"
        data.mkdir()
        silver_root = Path(source["silver_path"])
        parts = sorted(p for p in silver_root.glob("route_code=*/dt=*/*.parquet") if spec.includes_features(p.parent.name[3:])
                       and (spec.selected_features is None or p.parent.parent.name[11:] in spec.selected_features))
        routes = sorted({p.parent.parent.name.split("=",1)[1] for p in parts})
        if not routes:
            raise ValueError("no Silver routes in chosen feature window")
        baseline_rows = list(part_rows(sorted(Path(base["gold_data_path"]).glob("*.parquet"))))
        catalog = sorted({row["route_code"] for row in baseline_rows})
        meta = features.build_route_feature_metadata(self.pinned_reference(source), routes, baseline_rows, catalog)
        _, start, end = features.incident_window(spec.from_day, spec.to_day)
        facts_root = Path(source["incident_facts_path"])
        splits, engines = Counter(), set()

        def process_route(route):
            route_parts = [p for p in parts if p.parent.parent.name == "route_code=" + route]
            self.check_route_size(route_parts)
            by_dir = {0: [], 1: []}
            for record in part_rows(sorted((facts_root / f"route_code={route}").glob("*.parquet"))):
                record["route_code"] = route
                fact = tuple(record[c] for c in SILVER_INCIDENT_COLUMNS)
                for _, (direction, interval) in features.window_interval(fact, start, end):
                    by_dir[direction].append(interval)
            route_engines = set()
            rows = features.compute_route_features(route, part_rows(route_parts), by_dir, meta,
                fit_end_date=spec.fit_end_date, validation_epoch=spec.validation_epoch, test_epoch=spec.test_epoch,
                cadence_sec=spec.forecast_every, record_engine=route_engines.add)
            counts = write_feature_part(data / f"{route}.parquet", rows)
            atomic_write(data / f"{route}.json", encoded(dict(route_code=route, rows=sum(counts.values()))))
            return counts, route_engines

        if self.workers > 1 and len(routes) > 1:
            with ThreadPoolExecutor(self.workers) as pool:
                for counts, used in pool.map(process_route, routes):
                    check_memory_pressure(label="local_features")
                    splits.update(counts)
                    engines.update(used)
        else:
            for route in routes:
                check_memory_pressure(label="local_features")
                counts, used = process_route(route)
                splits.update(counts)
                engines.update(used)
        total = parquet_count(data)
        validate_counts(splits, total, features.SPLIT_NAMES)
        atomic_write(build / "feature_inputs.json", encoded(dict(input_mode="busmap_silver",
            baseline_fit_end_date=spec.fit_end_date, baseline_build_id=base["build_id"], **dict(spec.manifest(), routes=routes))))
        return publish(build, stage_manifest("features", spec, engines, build_id=build.name, snapshot_id=source["snapshot_id"],
            baseline_build_id=base["build_id"], row_count=total, split_counts=splits, routes=routes, data_path=str(data)))

    def serving(self, spec, inputs):
        if digest(encoded(self.reference)) != inputs["baseline"]["reference_sha256"]:
            raise ValueError("serving reference differs from pinned Gold baseline")
        return sync_gold_to_serving_db(source_db=self.static_db, output_db=self.serving_db,
                                      gold_parquet_dir=Path(inputs["baseline"]["gold_data_path"]), fit_end_date=spec.fit_end_date)
