"""Run the actual ETA baseline from local history, HDFS history, or its offline cache."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
HDFS_ROOT = 'hdfs://namenode:8020/bus-eta/v1/gold/'


def hdfs_bytes(path):
    if not path.startswith('hdfs://namenode:8020/bus-eta/v1/'):
        raise ValueError('unexpected HDFS root')
    return subprocess.run(
        ['docker', 'compose', '-f', str(ROOT / 'docker-compose.hdfs.yml'), 'exec', '-T',
         'namenode', 'hdfs', 'dfs', '-cat', path], check=True, capture_output=True, timeout=40
    ).stdout


def verify_cache(cache):
    manifest = json.loads((cache / 'cache_manifest.json').read_text(encoding='utf-8'))
    required = {'silver/part-00000.parquet', 'stations.json', 'origin.json'}
    if set(manifest['files']) != required:
        raise ValueError('incomplete snapshot file manifest')
    for relative, expected in manifest['files'].items():
        target = (cache / relative).resolve()
        if not target.is_relative_to(cache.resolve()):
            raise ValueError('cache file outside snapshot')
        if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
            raise ValueError('cache hash mismatch: ' + relative)
    return manifest


def materialize(run, cache):
    import pyarrow as pa
    import pyarrow.parquet as pq

    if not run.startswith(HDFS_ROOT) or '/experiments/' in run:
        raise ValueError('expected observed HDFS validation run')
    if cache.exists():
        raise ValueError('cache already exists; use --source cache or a new directory')
    report = json.loads(hdfs_bytes(run.rstrip('/') + '/validation_report/part-*'))
    if report['provenance'] != 'observed':
        raise ValueError('only observed history may build an ETA baseline')
    reference = hdfs_bytes(report['inputs']['stations'])
    if hashlib.sha256(reference).hexdigest() != report['stations_sha256']:
        raise ValueError('reference hash mismatch')
    # List part files: each Parquet file must be decoded separately, never concatenated.
    listing = subprocess.run(
        ['docker', 'compose', '-f', str(ROOT / 'docker-compose.hdfs.yml'), 'exec', '-T',
         'namenode', 'hdfs', 'dfs', '-ls', report['silver_path']],
        check=True, capture_output=True, text=True, timeout=40).stdout
    parts = sorted(line.split()[-1] for line in listing.splitlines() if '/part-' in line)
    if not parts:
        raise ValueError('HDFS Silver has no Parquet parts')
    tables, hashes = [], {}
    for part in parts:
        content = hdfs_bytes(part)
        hashes[part] = hashlib.sha256(content).hexdigest()
        tables.append(pq.read_table(io.BytesIO(content)))
    table = pa.concat_tables(tables)
    if table.num_rows != report['ping_count'] or set(table['route_code'].to_pylist()) != {report['route_code']}:
        raise ValueError('HDFS count/route mismatch')
    cache.mkdir(parents=True)
    silver = cache / 'silver'
    silver.mkdir()
    pq.write_table(table, silver / 'part-00000.parquet')
    (cache / 'stations.json').write_bytes(reference)
    (cache / 'origin.json').write_text(json.dumps(report, sort_keys=True), encoding='utf-8')
    files = {str(p.relative_to(cache)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in (silver / 'part-00000.parquet', cache / 'stations.json', cache / 'origin.json')}
    manifest = dict(source='hdfs', hdfs_run=run, source_window_id=report['source_window_id'],
                    silver_part_hashes=hashes, ping_count=table.num_rows, files=files)
    # Completion marker written only once all immutable input files exist.
    (cache / 'cache_manifest.json').write_text(json.dumps(manifest, sort_keys=True), encoding='utf-8')
    return verify_cache(cache)


def run_cached_baseline(cache, output):
    manifest = verify_cache(cache)
    origin = json.loads((cache / 'origin.json').read_text(encoding='utf-8'))
    stations = json.loads((cache / 'stations.json').read_text(encoding='utf-8'))
    if output.exists():
        raise ValueError('baseline output already exists; choose a fresh output directory')
    output.mkdir(parents=True)
    database = output / 'baseline.db'
    with sqlite3.connect(database) as conn:
        conn.execute('CREATE TABLE canonical_station_master (route_code TEXT, direction TEXT, station_order INTEGER, station_id INTEGER, station_name TEXT, cum_distance_m REAL)')
        conn.executemany('INSERT INTO canonical_station_master VALUES (?,?,?,?,?,?)',
                         [(s['route_code'], s['direction'], s['station_order'], s['station_id'], s['station_name'], s['cum_distance_m']) for s in stations])
        conn.execute('CREATE TABLE canonical_shape_master (route_code TEXT, direction TEXT, cum_distance_m REAL)')
        conn.executemany('INSERT INTO canonical_shape_master VALUES (?,?,?)',
                         [(origin['route_code'], direction, length) for direction, length in origin['shape_lengths_m'].items()])
    from module_3_bus_eta_prediction.step_3_1_historical_baseline_model import baseline_matrix_builder as builder
    previous = builder.DB_PATH, builder.SILVER_TEL_DIR, builder.GOLD_BASELINE_DIR
    try:
        builder.DB_PATH = str(database)
        builder.SILVER_TEL_DIR = str(cache / 'silver')
        builder.GOLD_BASELINE_DIR = str(output / 'gold')
        result = builder.build_and_evaluate_baseline_matrix()
    finally:
        builder.DB_PATH, builder.SILVER_TEL_DIR, builder.GOLD_BASELINE_DIR = previous
    lineage = dict(source='hdfs-materialized-cache', snapshot=manifest, result=result,
                   selected_dates=[origin['train_date'], origin['test_date']],
                   baseline_definition='existing Module-3 full day/hour tiered baseline')
    (output / 'lineage.json').write_text(json.dumps(lineage, sort_keys=True), encoding='utf-8')
    return lineage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', choices=['local', 'hdfs', 'cache'], default='local')
    parser.add_argument('--hdfs-run')
    parser.add_argument('--cache', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.source == 'local':
        if args.hdfs_run or args.cache or args.output:
            parser.error('local mode uses existing operational paths; omit snapshot options')
        from module_3_bus_eta_prediction.step_3_1_historical_baseline_model.baseline_matrix_builder import build_and_evaluate_baseline_matrix
        build_and_evaluate_baseline_matrix()
        return
    if not args.cache or not args.output or (args.source == 'hdfs' and not args.hdfs_run):
        parser.error('snapshot modes require --cache and --output; HDFS also requires --hdfs-run')
    if args.source == 'hdfs':
        materialize(args.hdfs_run, args.cache)
    print(json.dumps({'source_selected': args.source, 'cache': str(args.cache), 'output': str(args.output)}), flush=True)
    run_cached_baseline(args.cache, args.output)


if __name__ == '__main__':
    main()
