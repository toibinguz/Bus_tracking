"""Train the residual ETA model from historical BusMap Silver Parquet."""

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import date
from itertools import groupby
from pathlib import Path

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from module_3_bus_eta_prediction.step_3_2_feature_store_extractor.causal_eta import MAX_POSITION_AGE, CausalFeatures, Observation
from module_3_bus_eta_prediction.step_3_3_machine_learning_models.causal_eta_training import TrainingReplay, baseline_cutoff_epoch, digest, epoch, fit_bundle
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


def replay_silver(replay, partitions, baseline_end, cadence):
    members = defaultdict(dict)
    next_forecast = {}
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
            for vehicle in sorted(active):
                for order, *_ in replay.engine.corridor(route, direction):
                    replay.forecast(route, direction, vehicle, order, now)


def run(args):
    first_day, last_day = date.fromisoformat(args.from_day), date.fromisoformat(args.to_day)
    validation, test = epoch(args.validation_start), epoch(args.test_start)
    if first_day > last_day or validation >= test or args.rounds < 1 or args.forecast_every <= 0:
        raise ValueError('dates must be ordered and training settings must be positive')
    if args.output.exists():
        raise FileExistsError(args.output)
    with sqlite3.connect(args.baseline.resolve().as_uri() + '?mode=ro', uri=True) as db:
        cutoff, = db.execute('SELECT fit_end_date FROM eta_baseline_manifest').fetchall()
    fit_day, = cutoff
    if not fit_day or date.fromisoformat(fit_day) >= first_day:
        raise ValueError('baseline fit overlaps the Silver replay dates')
    partitions = select_partitions(args.silver, first_day, last_day, args.route)
    data = DataAccess(db_path=str(args.catalog), baseline_db_path=str(args.baseline))
    replay = TrainingReplay(CausalFeatures(data))
    replay_silver(replay, partitions, baseline_cutoff_epoch(fit_day), args.forecast_every)
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
    result = fit_bundle(rows, args.output, provenance, args.rounds)
    print(json.dumps(result['evaluation']['overall'], indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--silver', type=Path, required=True, help='Lakehouse Silver route_projected_telemetry root')
    parser.add_argument('--catalog', required=True, type=Path)
    parser.add_argument('--baseline', required=True, type=Path)
    parser.add_argument('--from-day', required=True)
    parser.add_argument('--to-day', required=True)
    parser.add_argument('--validation-start', required=True)
    parser.add_argument('--test-start', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--route', action='append', help='Lakehouse route_code partition, e.g. 02')
    parser.add_argument('--rounds', type=int, default=300)
    parser.add_argument('--forecast-every', type=float, default=30)
    run(parser.parse_args())


if __name__ == '__main__':
    main()
