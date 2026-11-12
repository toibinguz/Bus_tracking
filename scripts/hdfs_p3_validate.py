"""Bounded observed Silver snapshot -> HDFS Gold; no local data reads."""
import ast
from datetime import datetime
from collections import defaultdict
import hashlib
import json
from pathlib import Path
from statistics import median
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from config import system_config as config
from module_1_data_ingestion_and_preprocessing.step_1_3_telemetry_kinematic_sanitizer.trip_segmenter import segment_trajectory_into_trips


def arrival_functions():
    # Load the two pure existing functions without importing pandas/pyarrow or
    # running the local baseline builder. Function bodies remain single-source.
    source = Path(__file__).resolve().parents[1] / 'module_3_bus_eta_prediction/step_3_1_historical_baseline_model/baseline_matrix_builder.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    names = {'extract_bracketed_station_arrivals', 'get_active_corridor_stations'}
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    if {node.name for node in selected} != names:
        raise RuntimeError('baseline arrival interfaces changed')
    namespace = dict(vars(config), np=np)
    exec(compile('from __future__ import annotations', '<annotations>', 'exec'), namespace)
    module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0)] + selected, type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(source), 'exec'), namespace)
    return namespace['extract_bracketed_station_arrivals'], namespace['get_active_corridor_stations']


def observations(pings, stations, train_date, test_date, shape_lengths=None):
    if train_date >= test_date:
        raise ValueError('held-out date must be strictly later than training')
    arrivals_for, active_stations = arrival_functions()
    groups, reference = defaultdict(list), defaultdict(list)
    counts = defaultdict(int)
    for s in stations:
        reference[s['direction']].append((int(s['station_order']), int(s['station_id']), s['station_name'], float(s['cum_distance_m'])))
    for p in pings:
        day = p['device_update_time'][:10]
        if day not in (train_date, test_date):
            raise ValueError('observation outside declared split')
        groups[(day, p['direction'], p['vehicle_id'])].append(p)
    samples, heldout, test_trips = defaultdict(list), [], []
    for (day, direction, vehicle), rows in groups.items():
        full = sorted(reference[direction])
        corridor = active_stations(full)
        if len(corridor) < 2:
            raise ValueError('missing station corridor for observed direction')
        rows.sort(key=lambda p: p['device_epoch'])
        tuples = [(day, p['device_epoch'], p['s_bus_m'], p['derived_speed_kmh']) for p in rows]
        shape_length = (shape_lengths or {}).get(direction, full[-1][3])
        trips = segment_trajectory_into_trips(tuples, epoch_idx=1, s_idx=2, shape_len_m=shape_length, trim_terminals=True)
        split = 'train' if day == train_date else 'test'
        counts[split + '_trips'] += len(trips)
        counts['pings_outside_valid_trimmed_trips'] += len(rows) - sum(map(len, trips))
        for trip in trips:
            trip_segments = []
            arrivals = arrivals_for(trip, corridor, epoch_idx=1, s_idx=2)
            for a, b in zip(corridor, corridor[1:]):
                if a[0] not in arrivals or b[0] not in arrivals:
                    counts['unbracketed_pairs'] += 1
                    continue
                duration, distance = arrivals[b[0]] - arrivals[a[0]], b[3] - a[3]
                if duration <= 0 or distance <= 1:
                    counts['nonpositive_duration_or_short_distance'] += 1
                    continue
                if not config.SEGMENT_MIN_SPEED_KMPH <= distance / duration * 3.6 <= config.SEGMENT_MAX_SPEED_KMPH:
                    counts['speed_guard'] += 1
                    continue
                key = (direction, a[0], b[0])
                if day == train_date:
                    samples[key].append(duration)
                else:
                    heldout.append((key, duration))
                    trip_segments.append((key, duration))
            if day == test_date:
                test_trips.append(trip_segments)
    return samples, heldout, dict(counts), test_trips


def main(observed_path, stations_path, manifest_path, output_root, published_checkpoint=None):
    from pyspark.sql import SparkSession
    if not all(path.startswith('hdfs://') for path in (observed_path, stations_path, manifest_path, output_root)):
        raise ValueError('all data paths must be HDFS')
    spark = (SparkSession.builder.appName('bus-eta-hdfs-p3a')
             .config('spark.executor.memory','512m').getOrCreate())
    def read_bytes(path):
        return bytes(spark.read.format('binaryFile').load(path).first().content)
    try:
        manifest = json.loads(read_bytes(manifest_path))
        raw, reference = read_bytes(observed_path), read_bytes(stations_path)
        if manifest['provenance'] != 'observed':
            raise ValueError('accuracy evaluation requires observed provenance')
        for content, field in ((raw, 'observed_sha256'), (reference, 'stations_sha256')):
            if hashlib.sha256(content).hexdigest() != manifest[field]:
                raise ValueError('input hash mismatch')
        # Import an already projected observed snapshot into Parquet once, then
        # evaluate only the HDFS Silver Parquet data, retaining exact source hash.
        silver_path = output_root + '/silver_snapshot'
        spark.read.json(observed_path).write.mode('errorifexists').parquet(silver_path)
        pings = [row.asDict() for row in spark.read.parquet(silver_path).collect()]
        if len(pings) != manifest['ping_count']:
            raise ValueError('input count mismatch')
        if any(p['route_code'] != manifest['route_code'] for p in pings):
            raise ValueError('route mismatch')
        samples, heldout, counts, test_trips = observations(pings, json.loads(reference), manifest['train_date'], manifest['test_date'], manifest['shape_lengths_m'])
        stats = {key: median(values) for key, values in samples.items()}
        gold_path = output_root + '/gold_segment_statistics'
        rows = [(manifest['route_code'], *key, len(samples[key]), float(value), manifest['train_date']) for key, value in sorted(stats.items())]
        schema = 'route_code string, direction string, from_station_order long, to_station_order long, sample_count long, tt_p50_sec double, train_date string'
        spark.createDataFrame(rows, schema).write.mode('errorifexists').parquet(gold_path)
        stats = {(row.direction, row.from_station_order, row.to_station_order):row.tt_p50_sec
                 for row in spark.read.parquet(gold_path).collect()}
        errors = [abs(actual - stats[key]) for key, actual in heldout if key in stats]
        trip_errors = [abs(sum(stats[key] for key, _ in trip) - sum(actual for _, actual in trip))
                       for trip in test_trips if trip and all(key in stats for key, _ in trip)]
        report = dict(manifest, inputs={'observed': observed_path, 'stations': stations_path, 'manifest': manifest_path}, silver_path=silver_path,
                      gold_path=output_root + '/gold_segment_statistics', counts=counts,
                      train_segment_samples=sum(map(len, samples.values())), heldout_segment_samples=len(heldout),
                      matched_samples=len(errors), coverage=len(errors)/len(heldout) if heldout else None,
                      heldout_trips=len(test_trips), matched_trips=len(trip_errors),
                      trip_coverage=len(trip_errors)/len(test_trips) if test_trips else None,
                      trip_span_mae_seconds=sum(trip_errors)/len(trip_errors) if trip_errors else None,
                      trip_metric_definition='sum of all valid bracketed adjacent spans within each trip; requires history for every valid span; excludes unbracketed gaps, not full terminal-to-terminal duration',
                      mae_seconds=sum(errors)/len(errors) if errors else None, status='complete' if errors else 'inconclusive',
                      reason=None if errors else 'no matched held-out samples',
                      baseline_definition='all-training-date median by direction and adjacent station pair; not the full day/hour local baseline',
                      local_baseline_reconciliation='not comparable: bounded two-day snapshot versus full training period; no parity claim')
        if published_checkpoint:
            if not published_checkpoint.startswith('hdfs://'):
                raise ValueError('checkpoint must be HDFS')
            checkpoint = json.loads(read_bytes(published_checkpoint))
            fixture_rows = [row.asDict() for row in spark.read.parquet(checkpoint['silver_path']).collect()]
            fixture_groups = defaultdict(list)
            for row in fixture_rows:
                fixture_groups[(row['vehicle_id'], row['direction'])].append(row)
            fixture_trip_count = 0
            for rows in fixture_groups.values():
                for row in rows:
                    row['device_epoch'] = datetime.fromisoformat(row['device_update_time']).timestamp()
                rows.sort(key=lambda row: row['device_epoch'])
                fixture_trip_count += len(segment_trajectory_into_trips(
                    [(row['device_epoch'], row['s_bus_m']) for row in rows], epoch_idx=0, s_idx=1))
            report['published_fixture_diagnostic'] = {
                'source_window_id':checkpoint['source_window_id'], 'silver_path':checkpoint['silver_path'],
                'ping_count':len(fixture_rows), 'valid_trip_count':fixture_trip_count,
                'accuracy_claim':False, 'reason':'bounded fixture used for API chain, not accuracy evaluation'}
        spark.createDataFrame([(json.dumps(report, sort_keys=True),)], ['value']).write.mode('errorifexists').text(output_root + '/validation_report')
        print('P3A_RESULT=' + json.dumps(report, sort_keys=True))
    finally:
        spark.stop()


if __name__ == '__main__':
    main(*sys.argv[1:])
