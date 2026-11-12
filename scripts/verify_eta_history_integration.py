"""Check bounded HDFS history parity and full baseline offline reproducibility."""
import json
from pathlib import Path
import sqlite3
import sys
from unittest.mock import patch

import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.eta_history_baseline import run_cached_baseline, verify_cache


def main(cache, first_output, offline_output, source_database):
    cache, first_output, offline_output = map(Path, (cache, first_output, offline_output))
    manifest = verify_cache(cache)
    origin = json.loads((cache / 'origin.json').read_text())
    table = pq.read_table(cache / 'silver' / 'part-00000.parquet')
    columns = table.column_names
    # SQL identifiers are selected only from a fixed list from the snapshot contract.
    allowed = {'route_code','route_id','vehicle_id','device_update_time','device_epoch','direction','s_bus_m','cross_track_m','derived_speed_kmh'}
    if set(columns) != allowed:
        raise ValueError('unexpected snapshot schema')
    with sqlite3.connect(Path(source_database).resolve().as_uri() + '?mode=ro', uri=True) as conn:
        rows = conn.execute('SELECT ' + ','.join(columns) + ' FROM route_projected_telemetry WHERE route_code=? AND substr(device_update_time,1,10) IN (?,?)',
                            (origin['route_code'], origin['train_date'], origin['test_date'])).fetchall()
    snapshot_rows = [tuple(row[c] for c in columns) for row in table.to_pylist()]
    # Compare multisets including duplicates, every selected column and all bounded rows.
    key = lambda row: json.dumps(row, sort_keys=True)
    assert sorted(rows, key=key) == sorted(snapshot_rows, key=key), 'SQLite/HDFS input parity failed'
    with patch('subprocess.run', side_effect=AssertionError('offline cache invoked external process')):
        run_cached_baseline(cache, offline_output)
    with sqlite3.connect(first_output / 'baseline.db') as a, sqlite3.connect(offline_output / 'baseline.db') as b:
        first = a.execute('SELECT * FROM agg_segment_travel_times ORDER BY route_code,direction,from_station_order,to_station_order,day_type,hour_slot').fetchall()
        second = b.execute('SELECT * FROM agg_segment_travel_times ORDER BY route_code,direction,from_station_order,to_station_order,day_type,hour_slot').fetchall()
        assert first == second, 'offline baseline values differ'
    assert pq.read_table(first_output / 'gold' / 'part-00000.snappy.parquet').equals(pq.read_table(offline_output / 'gold' / 'part-00000.snappy.parquet'))
    print('INTEGRATION_RESULT=' + json.dumps(dict(input_rows=len(rows), exact_input_parity=True, baseline_cells=len(first),
          exact_sqlite_gold_parity=True, exact_parquet_gold_parity=True, offline_external_calls=0,
          source_window_id=manifest['source_window_id'])))


if __name__ == '__main__':
    main(*sys.argv[1:])
