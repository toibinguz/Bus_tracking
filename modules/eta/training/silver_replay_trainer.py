"""Train the residual ETA model from historical BusMap Silver Parquet."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
from collections import defaultdict
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from datetime import date, datetime
from itertools import groupby
from pathlib import Path
from urllib.parse import urlparse

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from config.hardware_guard import (
    check_memory_pressure,
    recommend_workers,
    set_process_below_normal_priority,
)
from config.system_config import DEFAULT_DB_PATH, TZ_HANOI
from modules.eta.features.causal_eta import (
    MAX_POSITION_AGE,
    CausalFeatures,
    Observation,
    RouteIncidentInterval,
)
from modules.eta.training.causal_eta_training import (
    ResidualETA,
    TrainingReplay,
    baseline_cutoff_epoch,
    digest,
    epoch,
    fit_bundle,
    metrics,
)
from modules.eta.serving.data_access import DataAccess


def select_partitions(root, first_day, last_day, routes):
    by_day = defaultdict(list)
    for path in sorted(root.glob('route_code=*/dt=*/*.parquet')):
        day = date.fromisoformat(path.parent.name.removeprefix('dt='))
        route_code = path.parent.parent.name.removeprefix('route_code=')
        if first_day <= day <= last_day and (not routes or route_code in routes):
            by_day[day].append(path)
    if not by_day:
        raise ValueError('no BusMap Silver partitions for the chosen dates and routes')
    return by_day


def silver_rows(paths):
    for path in paths:
        schema = pq.ParquetFile(path).schema_arrow.names
        time_column = 'device_epoch_s' if 'device_epoch_s' in schema else 'device_epoch'
        has_s_bus = 's_bus_m' in schema
        columns = ['route_id', 'direction', 'vehicle_id', 'plate', time_column, 'lat', 'lon']
        if has_s_bus:
            columns.append('s_bus_m')
        tbl = pq.ParquetFile(path).read(columns=columns)
        rids = tbl['route_id'].to_pylist()
        dirs = tbl['direction'].to_pylist()
        vids = tbl['vehicle_id'].to_pylist()
        plates = tbl['plate'].to_pylist()
        stamps = tbl[time_column].to_pylist()
        lats = tbl['lat'].to_pylist()
        lons = tbl['lon'].to_pylist()
        s_vals = tbl['s_bus_m'].to_pylist() if has_s_bus else [None] * len(rids)
        for rid, d_str, vid, pl, stamp, lat, lon, s_bus in zip(
            rids, dirs, vids, plates, stamps, lats, lons, s_vals
        ):
            if d_str not in ('go', 're'):
                continue
            if rid is None or vid is None or stamp is None or lat is None or lon is None:
                continue
            plate = ''.join(c for c in (pl or '').upper() if c.isalnum())
            yield Observation(
                int(rid),
                int(d_str == 're'),
                plate or f'id:{vid}',
                'busmap',
                stamp,
                stamp,
                lat,
                lon,
                '',
                s_bus_m=float(s_bus) if s_bus is not None else None,
            )


def load_incident_timeline(incidents_root: Path | None, data: DataAccess, route_codes=None):
    """Đọc Silver fact_route_tomtom_incidents và sắp theo (route_id, direction, t_start_epoch)."""
    timeline = defaultdict(list)
    if not incidents_root or not incidents_root.is_dir():
        return timeline
    allowed = set(route_codes) if route_codes else None
    for route_dir in sorted(incidents_root.glob('route_code=*')):
        route_code = route_dir.name.removeprefix('route_code=')
        if allowed is not None and route_code not in allowed:
            continue
        route_id = data.resolve_route_id(route_code)
        if route_id is None:
            continue
        for parquet_path in sorted(route_dir.glob('*.parquet')):
            table = pq.ParquetFile(parquet_path).read(
                columns=['direction', 't_start_epoch', 't_end_epoch', 's_min_m', 's_max_m', 'delay_seconds']
            )
            for row in table.to_pylist():
                direction_str = row.get('direction')
                if direction_str not in ('go', 're'):
                    continue
                delay = float(row.get('delay_seconds') or 0.0)
                if delay <= 0.0:
                    continue
                timeline[(int(route_id), int(direction_str == 're'))].append(
                    RouteIncidentInterval(
                        s_min_m=float(row['s_min_m']),
                        s_max_m=float(row['s_max_m']),
                        delay_seconds=delay,
                        crawled_epoch=float(row['t_start_epoch']),
                        expires_epoch=float(row['t_end_epoch']),
                    )
                )
    for key in timeline:
        timeline[key].sort(key=lambda iv: iv.crawled_epoch)
    return timeline


def replay_silver(replay, partitions, baseline_end, cadence, incident_timeline=None, on_day_complete=None):
    members = defaultdict(dict)
    next_forecast = {}
    inc_ptrs = defaultdict(int)
    active_incidents = defaultdict(list)
    last_time = -float('inf')

    def group_key(row):
        return row.epoch, row.route_id, row.direction

    for day in sorted(partitions):
        rows = sorted(silver_rows(partitions[day]), key=lambda o: (*group_key(o), o.vehicle, o.lat, o.lng))
        for (now, route, direction), observations in groupby(rows, key=group_key):
            if now < baseline_end or now < last_time:
                raise ValueError('Silver partition timestamps overlap baseline fitting or arrive out of order')
            last_time = now
            key = (route, direction)
            batch = list(observations)
            active = {plate: t for plate, t in members[key].items() if now - t <= MAX_POSITION_AGE}
            active.update((row.vehicle, now) for row in batch)
            members[key] = active
            replay.snapshot(route, direction, now, batch, active, fleet_valid=True)
            if now < next_forecast.get(key, 0):
                continue
            next_forecast[key] = now + cadence
            if incident_timeline is not None:
                route_inc = incident_timeline.get(key, ())
                ptr = inc_ptrs[key]
                cur_active = active_incidents[key]
                while ptr < len(route_inc) and route_inc[ptr].crawled_epoch <= now:
                    if route_inc[ptr].expires_epoch >= now:
                        cur_active.append(route_inc[ptr])
                    ptr += 1
                inc_ptrs[key] = ptr
                if cur_active:
                    cur_active = [iv for iv in cur_active if iv.expires_epoch >= now]
                    active_incidents[key] = cur_active
                replay.engine.observe_incidents(route, direction, cur_active)
            for vehicle in sorted(active):
                replay.forecast_all(route, direction, vehicle, now)
        if on_day_complete is not None and last_time > -float('inf'):
            on_day_complete(replay, last_time)


def _export_single_route_checkpoint(task):
    from uuid import uuid4
    from modules.lakehouse.hdfs.hf_bronze import atomic_write, encoded
    from modules.lakehouse.local_adapter import part_rows, write_feature_part
    from modules.lakehouse.pipeline.features import features_with_lookup

    set_process_below_normal_priority()
    (route, silver_root, incidents_root, db_path, first_day, last_day,
     validation, test, fit_day, cadence, output) = task
    path = Path(output) / f"{route}.parquet"
    metadata = path.with_suffix(".json")
    if path.exists() and metadata.exists():
        return route, 0, "skipped"
    partitions = select_partitions(Path(silver_root), date.fromisoformat(first_day), date.fromisoformat(last_day), [route])
    data = DataAccess(db_path=str(db_path))
    rid = data.resolve_route_id(route)
    idx = data.get_route_idx(rid)
    if idx is None:
        raise ValueError("route missing from baseline: " + route)
    inc_root = Path(incidents_root) if incidents_root else Path(silver_root).parent / "fact_route_tomtom_incidents"
    timeline = load_incident_timeline(inc_root, data, route_codes=[route])
    intervals = {d: [(v.s_min_m, v.s_max_m, v.delay_seconds, v.crawled_epoch, v.expires_epoch)
                     for v in timeline.get((rid, d), ())] for d in (0, 1)}
    engines = set()
    rows = features_with_lookup(route, rid, idx, data,
        part_rows(p for day in sorted(partitions) for p in partitions[day]), intervals,
        fit_day, validation, test, cadence, engines.add)
    temporary = path.with_name(f".{route}.{uuid4().hex}.tmp")
    try:
        counts = write_feature_part(temporary, rows)
        temporary.replace(path)
        total = sum(counts.values())
        atomic_write(metadata, encoded(dict(route_code=route, rows=total, counts=dict(counts), engines=sorted(engines))))
        return route, total, "written"
    finally:
        temporary.unlink(missing_ok=True)


def _hdfs_posix(uri: str) -> str:
    parsed = urlparse(uri)
    return parsed.path if parsed.scheme else uri


def _pull_silver_snapshot_from_hdfs(
    snapshot_id: str,
    compose_file: Path,
    dest_dir: Path,
    db_path: Path,
) -> tuple[Path, Path | None]:
    """Tải Silver Telemetry (và TomTom incidents nếu có) của snapshot HDFS về thư mục tạm local."""
    from modules.ingestion.projection import (
        tomtom_incident_projector as inc_proj,
    )
    from modules.lakehouse.hdfs.hf_bronze import DockerHdfs

    if len(snapshot_id) != 64 or any(c not in '0123456789abcdef' for c in snapshot_id):
        raise ValueError('invalid snapshot ID')

    hdfs = DockerHdfs(compose_file)
    pub_raw = hdfs.read(f'/bus-eta/v1/_published/history_snapshots/{snapshot_id}.json')
    pub = json.loads(pub_raw)
    if pub.get('snapshot_id') != snapshot_id:
        raise ValueError('snapshot ID mismatch in HDFS publication manifest')

    silver_remote = _hdfs_posix(pub['silver_path']).rstrip('/')
    listing = hdfs.call('-ls', '-R', silver_remote).decode('utf-8', errors='replace')
    remote_parts = sorted(
        line.split()[-1]
        for line in listing.splitlines()
        if line.split() and line.split()[-1].endswith('.parquet')
    )
    if not remote_parts:
        raise ValueError(f'no Silver Parquet parts found in HDFS: {silver_remote}')

    local_silver = dest_dir / 'route_projected_telemetry'
    for part in remote_parts:
        part_posix = _hdfs_posix(part)
        if not part_posix.startswith(silver_remote + '/'):
            raise ValueError(f'unexpected HDFS path {part_posix} outside {silver_remote}')
        rel = part_posix[len(silver_remote) + 1:]
        target = local_silver / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(hdfs.read(part_posix))

    local_inc: Path | None = None
    hdfs_fact_inc = f'/bus-eta/v1/silver/fact_route_tomtom_incidents/snapshot={snapshot_id}'
    if hdfs.exists(hdfs_fact_inc):
        inc_listing = hdfs.call('-ls', '-R', hdfs_fact_inc).decode('utf-8', errors='replace')
        inc_parts = sorted(
            line.split()[-1]
            for line in inc_listing.splitlines()
            if line.split() and line.split()[-1].endswith('.parquet')
        )
        if inc_parts:
            local_inc = dest_dir / 'fact_route_tomtom_incidents'
            for part in inc_parts:
                part_posix = _hdfs_posix(part)
                rel = part_posix[len(hdfs_fact_inc) + 1:]
                target = local_inc / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(hdfs.read(part_posix))
    elif pub.get('incident_observations'):
        raw_records = inc_proj._read_raw_incidents_from_hdfs(snapshot_id, compose_file)
        if raw_records:
            local_inc = dest_dir / 'fact_route_tomtom_incidents'
            _, route_shapes, route_stations = inc_proj._load_canonical_geometry(db_path, local_silver)
            fact_rows, _ = inc_proj.project_incidents_to_route_facts(raw_records, route_shapes, route_stations)
            if fact_rows:
                inc_proj.write_silver_incidents_parquet(fact_rows, local_inc, clean=True)
            else:
                local_inc = None

    return local_silver, local_inc


def _run_with_silver(args, silver_root: Path, incidents_root: Path | None, db_path: Path, first_day: date, last_day: date, validation: float, test: float, fit_day: str):
    if args.export_checkpoints_dir is not None:
        ckpt_root = args.export_checkpoints_dir
        feat_dir = ckpt_root / 'features'
        feat_dir.mkdir(parents=True, exist_ok=True)
        partitions_in_window = select_partitions(silver_root, first_day, last_day, args.route)
        route_codes = sorted({
            p.parent.parent.name.removeprefix('route_code=')
            for paths in partitions_in_window.values()
            for p in paths
        })
        inc_root = str(incidents_root) if incidents_root is not None else str(silver_root.parent / 'fact_route_tomtom_incidents')
        tasks = [
            (rc, str(silver_root), inc_root, str(db_path),
             args.from_day, args.to_day, validation, test, fit_day, args.forecast_every, str(feat_dir))
            for rc in route_codes
        ]
        workers = recommend_workers(args.workers, per_worker_ram_gb=0.45, min_free_ram_gb=1.5, max_cpu_frac=0.75)
        if workers == 1:
            for t in tasks:
                rc, _, st = _export_single_route_checkpoint(t)
                print(f'[checkpoint] route={rc} status={st}', flush=True)
                check_memory_pressure(label=f'checkpoint={rc}')
        else:
            with ProcessPoolExecutor(max_workers=workers) as pool:
                task_iter = iter(tasks)
                in_flight = set()
                for _ in range(min(workers, len(tasks))):
                    t = next(task_iter, None)
                    if t is None:
                        break
                    in_flight.add(pool.submit(_export_single_route_checkpoint, t))
                while in_flight:
                    done, in_flight = wait(in_flight, return_when=FIRST_COMPLETED)
                    for fut in done:
                        next_t = next(task_iter, None)
                        if next_t is not None:
                            in_flight.add(pool.submit(_export_single_route_checkpoint, next_t))
                        rc, _, st = fut.result()
                        print(f'[checkpoint] route={rc} status={st}', flush=True)
                        check_memory_pressure(label=f'checkpoint={rc}')
        (ckpt_root / 'feature_inputs.json').write_text(json.dumps({
            'input_mode': 'hdfs_silver' if args.hdfs_snapshot else 'busmap_silver',
            'from_day': args.from_day,
            'to_day': args.to_day,
            'test_start': args.test_start,
            'no_valid': bool(args.no_valid),
            'baseline_fit_end_date': fit_day,
            'forecast_every': args.forecast_every,
            'routes': route_codes,
        }, indent=2), encoding='utf-8')
        print(f'[checkpoint] Exported {len(route_codes)} route checkpoints to {feat_dir}', flush=True)
        return

    if args.output is None:
        raise ValueError('--output is required when not using --export-checkpoints-dir')
    if args.output.exists():
        raise FileExistsError(args.output)
    partitions = select_partitions(silver_root, first_day, last_day, args.route)
    data = DataAccess(db_path=str(db_path))
    resolved_incidents = incidents_root if incidents_root is not None else (silver_root.parent / 'fact_route_tomtom_incidents')
    incident_timeline = load_incident_timeline(resolved_incidents, data)
    replay = TrainingReplay(CausalFeatures(data))
    replay_silver(replay, partitions, baseline_cutoff_epoch(fit_day), args.forecast_every, incident_timeline)
    rows = list(replay.labeled(validation, test))
    files = [path for paths in partitions.values() for path in paths]
    source_manifest = silver_root.parent.parent / 'source.json'
    if source_manifest.is_file():
        files.append(source_manifest)
    files.extend((db_path, Path(__file__),
                  ROOT / 'modules/eta/features/causal_eta.py',
                  ROOT / 'modules/eta/training/causal_eta_training.py',
                  ROOT / 'modules/ingestion/projection/route_matcher.py'))
    provenance = dict(inputs={str(path): digest(path) for path in files}, baseline_fit_end_date=fit_day,
                      input_mode='hdfs_silver' if args.hdfs_snapshot else 'busmap_silver',
                      replay_clock='device_timestamp',
                      fleet_membership='recent_visible_busmap', validation_start_epoch=validation,
                      test_start_epoch=test, routes=args.route, counts=dict(replay.counts),
                      forecast_every=args.forecast_every)
    if args.hdfs_snapshot:
        provenance['hdfs_snapshot_id'] = args.hdfs_snapshot
    print(json.dumps(provenance['counts']), flush=True)
    if args.reference_model is not None:
        import numpy as np
        ref_runner = ResidualETA.load(args.reference_model)
        test_rows = [r for r in rows if r['split'] == 'test']
        ref_preds = ref_runner.predict((r['features'] for r in test_rows), allow_unknown_routes=True)
        actual = np.array([r['eta_seconds'] for r in test_rows])
        groups = [(r['journey'], r['target']) for r in test_rows]
        inc_delays = np.array([float(r['features'].get('inc_ahead_total_delay_sec') or 0.0) for r in test_rows])
        ref_report = {
            'reference_model': str(args.reference_model),
            'overall': metrics(actual, ref_preds, groups),
            'by_incident': {},
        }
        for name, mask in [('no_incident', inc_delays <= 0.0), ('has_incident', inc_delays > 0.0)]:
            if mask.any():
                keys = [g for g, keep in zip(groups, mask, strict=True) if keep]
                ref_report['by_incident'][name] = metrics(actual[mask], ref_preds[mask], keys)
        ref_out = args.output.parent / f'{args.output.name}_reference_eval.json'
        ref_out.parent.mkdir(parents=True, exist_ok=True)
        ref_out.write_text(json.dumps(ref_report, indent=2) + '\n', encoding='utf-8')
        print(f'[REFERENCE EVAL] Saved {ref_out}:', json.dumps(ref_report, indent=2), flush=True)
    result = fit_bundle(rows, args.output, provenance, args.rounds, max_depth=args.max_depth, use_validation=not args.no_valid)
    print(json.dumps(result['evaluation']['overall'], indent=2))


def _split_epoch(value) -> float:
    if isinstance(value, str) and len(value) == 10:
        d = date.fromisoformat(value)
        return datetime(d.year, d.month, d.day, tzinfo=TZ_HANOI).timestamp()
    return epoch(value)


def run(args):
    set_process_below_normal_priority()
    if bool(args.silver) == bool(args.hdfs_snapshot):
        raise ValueError('specify exactly one of --silver or --hdfs-snapshot')
    first_day, last_day = date.fromisoformat(args.from_day), date.fromisoformat(args.to_day)
    validation_day = args.test_start if args.no_valid or not args.validation_start else args.validation_start
    validation, test = _split_epoch(validation_day), _split_epoch(args.test_start)
    if first_day > last_day or validation > test or (not args.no_valid and validation >= test) or args.rounds < 1 or args.forecast_every <= 0:
        raise ValueError('dates must be ordered and training settings must be positive')

    db_path = Path(args.db_path)
    db = sqlite3.connect(db_path.resolve().as_uri() + '?mode=ro', uri=True)
    try:
        cutoff, = db.execute('SELECT fit_end_date FROM eta_baseline_manifest').fetchall()
    finally:
        db.close()
    fit_day, = cutoff
    if not fit_day or date.fromisoformat(fit_day) >= first_day:
        raise ValueError('baseline fit overlaps the Silver replay dates')

    if args.hdfs_snapshot:
        with tempfile.TemporaryDirectory(prefix='causal_eta_hdfs_') as tmp_dir:
            silver_root, pulled_inc = _pull_silver_snapshot_from_hdfs(
                args.hdfs_snapshot, Path(args.compose_file), Path(tmp_dir), db_path
            )
            inc_root = Path(args.incidents) if args.incidents is not None else pulled_inc
            _run_with_silver(args, silver_root, inc_root, db_path, first_day, last_day, validation, test, fit_day)
    else:
        inc_root = Path(args.incidents) if args.incidents is not None else None
        silver_root = Path(args.silver)
        pointer = silver_root / "manifest.json"
        if not pointer.exists() and silver_root.name == "route_projected_telemetry":
            pointer = silver_root.parent / "manifest.json"
        if pointer.is_file():
            silver_root = Path(json.loads(pointer.read_text(encoding="utf-8"))["silver_path"])
        _run_with_silver(args, silver_root, inc_root, db_path, first_day, last_day, validation, test, fit_day)


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--silver', type=Path, default=None, help='Local Silver route_projected_telemetry root')
    parser.add_argument('--hdfs-snapshot', default=None, help='64-hex HDFS published Silver snapshot ID')
    parser.add_argument('--compose-file', type=Path, default=ROOT / 'docker-compose.hdfs.yml')
    parser.add_argument('--db-path', type=Path, default=ROOT / DEFAULT_DB_PATH, help='Unified 5-table Serving SQLite DB')
    parser.add_argument('--from-day', required=True)
    parser.add_argument('--to-day', required=True)
    parser.add_argument('--validation-start', default=None)
    parser.add_argument('--test-start', required=True)
    parser.add_argument('--no-valid', action='store_true', help='Merge train+validation and fit without early stopping')
    parser.add_argument('--reference-model', type=Path, default=None, help='Optional existing model dir to evaluate on test split before fitting')
    parser.add_argument('--output', required=False, type=Path, default=None)
    parser.add_argument('--export-checkpoints-dir', type=Path, default=None, help='Export per-route Parquet checkpoints to avoid OOM')
    parser.add_argument('--workers', type=int, default=6, help='Parallel workers for --export-checkpoints-dir')
    parser.add_argument('--route', action='append', help='Silver route_code partition, e.g. 02')
    parser.add_argument('--rounds', type=int, default=1200)
    parser.add_argument('--max-depth', type=int, default=6)
    parser.add_argument('--forecast-every', type=float, default=30)
    parser.add_argument('--incidents', type=Path, default=None, help='Optional Silver fact_route_tomtom_incidents root')
    return parser


def main(argv=None):
    run(build_parser().parse_args(argv))


if __name__ == '__main__':
    main()
