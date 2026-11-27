"""Train the residual ETA model from historical BusMap Silver Parquet."""

import argparse
import gc
import json
import sqlite3
import sys
from collections import defaultdict
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from datetime import date
from itertools import groupby
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from config.hardware_guard import (
    check_memory_pressure,
    recommend_workers,
    set_process_below_normal_priority,
)
from module_3_bus_eta_prediction.step_3_2_feature_store_extractor.causal_eta import (
    FEATURES,
    MAX_POSITION_AGE,
    CausalFeatures,
    Observation,
    RouteIncidentInterval,
)
from module_3_bus_eta_prediction.step_3_3_machine_learning_models.causal_eta_training import (
    ResidualETA,
    TrainingReplay,
    baseline_cutoff_epoch,
    digest,
    epoch,
    fit_bundle,
    metrics,
)
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.data_access import DataAccess


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
        columns = ['route_id', 'direction', 'vehicle_id', 'plate', time_column, 'lat', 'lon']
        for row in pq.ParquetFile(path).read(columns=columns).to_pylist():
            if row['direction'] not in ('go', 're'):
                continue
            if any(row[key] is None for key in ('route_id', 'vehicle_id', time_column, 'lat', 'lon')):
                continue
            plate = ''.join(c for c in (row['plate'] or '').upper() if c.isalnum())
            stamp = row[time_column]
            yield Observation(int(row['route_id']), int(row['direction'] == 're'),
                              plate or f"id:{row['vehicle_id']}", 'busmap', stamp, stamp,
                              row['lat'], row['lon'], '')


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
                for order, *_ in replay.engine.corridor(route, direction):
                    replay.forecast(route, direction, vehicle, order, now)
        if on_day_complete is not None and last_time > -float('inf'):
            on_day_complete(replay, last_time)


def _checkpoint_schema():
    fields = [pa.field(f, pa.float32()) for f in FEATURES]
    fields.extend([
        pa.field('route', pa.string()),
        pa.field('vehicle', pa.string()),
        pa.field('journey', pa.int64()),
        pa.field('target', pa.int64()),
        pa.field('split', pa.string()),
        pa.field('as_of', pa.float64()),
        pa.field('eta_seconds', pa.float64()),
        pa.field('bracket_before', pa.float64()),
        pa.field('bracket_after', pa.float64()),
        pa.field('crossing_epoch', pa.float64()),
        pa.field('history_seconds', pa.float64()),
    ])
    return pa.schema(fields)


def _export_single_route_checkpoint(task):
    """Replay 1 tuyến và flush Parquet từng ngày để giữ RAM cực thấp (~100-200 MB)."""
    set_process_below_normal_priority()
    (route_code, silver_root, incidents_root, catalog_path, baseline_path,
     first_day_iso, last_day_iso, validation, test, fit_day, cadence, out_dir_str) = task
    out_dir = Path(out_dir_str)
    pq_path = out_dir / f'{route_code}.parquet'
    meta_path = out_dir / f'{route_code}.json'
    if pq_path.exists() and meta_path.exists():
        return route_code, 0, 'skipped'
    first_day = date.fromisoformat(first_day_iso)
    last_day = date.fromisoformat(last_day_iso)
    partitions = select_partitions(Path(silver_root), first_day, last_day, [route_code])
    data = DataAccess(db_path=str(catalog_path), baseline_db_path=str(baseline_path))
    inc_root = Path(incidents_root) if incidents_root else (Path(silver_root).parent / 'fact_route_tomtom_incidents')
    inc_timeline = load_incident_timeline(inc_root, data, route_codes=[route_code])
    replay = TrainingReplay(CausalFeatures(data))

    schema = _checkpoint_schema()
    tmp_pq = out_dir / f'.{route_code}.parquet.tmp'
    writer = pq.ParquetWriter(tmp_pq, schema, compression='snappy')
    total_rows = 0

    def _flush_ready(rp, cutoff_epoch):
        nonlocal total_rows
        if cutoff_epoch is None:
            ready = rp.examples
            rp.examples = []
        else:
            ready = [r for r in rp.examples if r['as_of'] < cutoff_epoch]
            rp.examples = [r for r in rp.examples if r['as_of'] >= cutoff_epoch]
        if not ready:
            return
        tail = rp.examples
        rp.examples = ready
        records = []
        for row in rp.labeled(validation, test):
            rec = {f: row['features'][f] for f in FEATURES}
            rec['route'] = str(route_code)
            rec['vehicle'] = str(row['vehicle'])
            rec['journey'] = int(row['journey'])
            rec['target'] = int(row['target'])
            rec['split'] = str(row['split'])
            rec['as_of'] = float(row['as_of'])
            rec['eta_seconds'] = float(row['eta_seconds'])
            lbl = row['label']
            rec['bracket_before'] = float(lbl['before_epoch'])
            rec['bracket_after'] = float(lbl['after_epoch'])
            rec['crossing_epoch'] = float(lbl['epoch'])
            ego5 = row['speeds'].get('ego5')
            rec['history_seconds'] = float(ego5['seconds']) if ego5 else 0.0
            records.append(rec)
        rp.examples = tail
        if records:
            frame = pd.DataFrame(records)
            for f in FEATURES:
                frame[f] = frame[f].astype('float32')
            table = pa.Table.from_pandas(frame, schema=schema, preserve_index=False)
            writer.write_table(table)
            total_rows += len(frame)
            del frame, table
        del ready, records

    try:
        replay_silver(
            replay,
            partitions,
            baseline_cutoff_epoch(fit_day),
            cadence,
            inc_timeline,
            on_day_complete=lambda rp, last_t: _flush_ready(rp, last_t - 7200.0),
        )
        _flush_ready(replay, None)
    finally:
        writer.close()

    tmp_pq.replace(pq_path)
    meta_path.write_text(json.dumps({
        'route_code': route_code,
        'rows': total_rows,
        'counts': dict(replay.counts),
    }, indent=2), encoding='utf-8')
    del replay, inc_timeline, partitions
    gc.collect()
    return route_code, total_rows, 'written'


def run(args):
    set_process_below_normal_priority()
    first_day, last_day = date.fromisoformat(args.from_day), date.fromisoformat(args.to_day)
    validation_day = args.test_start if args.no_valid or not args.validation_start else args.validation_start
    validation, test = epoch(validation_day), epoch(args.test_start)
    if first_day > last_day or validation > test or (not args.no_valid and validation >= test) or args.rounds < 1 or args.forecast_every <= 0:
        raise ValueError('dates must be ordered and training settings must be positive')
    with sqlite3.connect(args.baseline.resolve().as_uri() + '?mode=ro', uri=True) as db:
        cutoff, = db.execute('SELECT fit_end_date FROM eta_baseline_manifest').fetchall()
    fit_day, = cutoff
    if not fit_day or date.fromisoformat(fit_day) >= first_day:
        raise ValueError('baseline fit overlaps the Silver replay dates')

    if args.export_checkpoints_dir is not None:
        ckpt_root = args.export_checkpoints_dir
        feat_dir = ckpt_root / 'features'
        feat_dir.mkdir(parents=True, exist_ok=True)
        route_codes = sorted({p.name.removeprefix('route_code=') for p in args.silver.glob('route_code=*') if p.is_dir()})
        if args.route:
            route_codes = [r for r in route_codes if r in set(args.route)]
        inc_root = str(args.incidents) if args.incidents is not None else str(args.silver.parent / 'fact_route_tomtom_incidents')
        tasks = [
            (rc, str(args.silver), inc_root, str(args.catalog), str(args.baseline),
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
            'input_mode': 'busmap_lakehouse_silver',
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

    if args.output.exists():
        raise FileExistsError(args.output)
    partitions = select_partitions(args.silver, first_day, last_day, args.route)
    data = DataAccess(db_path=str(args.catalog), baseline_db_path=str(args.baseline))
    incidents_root = args.incidents if args.incidents is not None else (args.silver.parent / 'fact_route_tomtom_incidents')
    incident_timeline = load_incident_timeline(incidents_root, data)
    replay = TrainingReplay(CausalFeatures(data))
    replay_silver(replay, partitions, baseline_cutoff_epoch(fit_day), args.forecast_every, incident_timeline)
    rows = list(replay.labeled(validation, test))
    files = [path for paths in partitions.values() for path in paths]
    source_manifest = args.silver.parent.parent / 'source.json'
    if source_manifest.is_file():
        files.append(source_manifest)
    files.extend((args.catalog, args.baseline, Path(__file__),
                  ROOT / 'module_3_bus_eta_prediction/step_3_2_feature_store_extractor/causal_eta.py',
                  ROOT / 'module_3_bus_eta_prediction/step_3_3_machine_learning_models/causal_eta_training.py',
                  ROOT / 'module_1_data_ingestion_and_preprocessing/step_1_4_frenet_spatial_projection/route_matcher.py'))
    provenance = dict(inputs={str(path): digest(path) for path in files}, baseline_fit_end_date=fit_day,
                      input_mode='busmap_lakehouse_silver', replay_clock='device_timestamp',
                      fleet_membership='recent_visible_busmap', validation_start_epoch=validation,
                      test_start_epoch=test, routes=args.route, counts=dict(replay.counts),
                      forecast_every=args.forecast_every)
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--silver', type=Path, required=True, help='Lakehouse Silver route_projected_telemetry root')
    parser.add_argument('--catalog', required=True, type=Path)
    parser.add_argument('--baseline', required=True, type=Path)
    parser.add_argument('--from-day', required=True)
    parser.add_argument('--to-day', required=True)
    parser.add_argument('--validation-start', default=None)
    parser.add_argument('--test-start', required=True)
    parser.add_argument('--no-valid', action='store_true', help='Merge train+validation and fit without early stopping')
    parser.add_argument('--reference-model', type=Path, default=None, help='Optional existing model dir to evaluate on test split before fitting')
    parser.add_argument('--output', required=False, type=Path, default=None)
    parser.add_argument('--export-checkpoints-dir', type=Path, default=None, help='Export per-route Parquet checkpoints to avoid OOM')
    parser.add_argument('--workers', type=int, default=4, help='Parallel workers for --export-checkpoints-dir')
    parser.add_argument('--route', action='append', help='Lakehouse route_code partition, e.g. 02')
    parser.add_argument('--rounds', type=int, default=1200)
    parser.add_argument('--max-depth', type=int, default=6)
    parser.add_argument('--forecast-every', type=float, default=30)
    parser.add_argument('--incidents', type=Path, default=None, help='Optional Lakehouse Silver fact_route_tomtom_incidents root')
    run(parser.parse_args())


if __name__ == '__main__':
    main()
