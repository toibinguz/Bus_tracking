"""Read-only structural readiness checks, scoped to Silver or Gold.

Passing this command does not certify label correctness, leakage or ML accuracy.
Gold is allowed to exist when verifying Silver; no historical row thresholds.
"""
import argparse
import json
from pathlib import Path
import sqlite3
import sys

import pyarrow.parquet as pq

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def parquet_inventory(root,required):
    files=sorted(Path(root).rglob('*.parquet'))
    if not files:raise ValueError('no Parquet files: '+str(root))
    count=0
    for path in files:
        file=pq.ParquetFile(path)
        columns=file.schema_arrow.names
        if len(columns)!=len(set(columns)) or not set(required).issubset(columns):
            raise ValueError('invalid Parquet schema: '+str(path))
        count+=file.metadata.num_rows
    if not count:raise ValueError('stage has no rows: '+str(root))
    return dict(files=len(files),rows=count)


def verify(database,lakehouse,stage='silver'):
    database=Path(database).resolve()
    tables={}
    required={'canonical_route_master':['route_id','route_code'],
              'canonical_station_master':['route_id','route_code','direction','station_order','station_id','cum_distance_m'],
              'canonical_shape_master':['route_id','route_code','direction','point_order','lat','lon','cum_distance_m']}
    if stage=='gold':required['agg_segment_travel_times']=['route_code','direction','from_station_order','to_station_order','tt_p50_sec','sample_count']
    with sqlite3.connect(database.as_uri()+'?mode=ro',uri=True) as conn:
        for table,columns in required.items():
            actual={r[1] for r in conn.execute('PRAGMA table_info('+table+')')}
            if not set(columns).issubset(actual):raise ValueError('missing table/columns: '+table)
            count=conn.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
            if not count:raise ValueError('empty required table: '+table)
            invalid=conn.execute('SELECT COUNT(*) FROM '+table+' WHERE '+' OR '.join(c+' IS NULL' for c in columns)).fetchone()[0]
            if invalid:raise ValueError('null required values: '+table)
            if conn.execute('SELECT COUNT(*) FROM '+table+" WHERE typeof(route_code)!='text'").fetchone()[0]:
                raise ValueError('route codes must remain text: '+table)
            tables[table]=count
    lakehouse=Path(lakehouse)
    silver=parquet_inventory(lakehouse/'silver/route_projected_telemetry',
                              ['vehicle_id','device_update_time','device_epoch','direction','s_bus_m','derived_speed_kmh'])
    result=dict(stage=stage,tables=tables,silver=silver,scope='structural readiness only; not a correctness/accuracy verdict')
    if stage=='gold':
        result['features']=parquet_inventory(lakehouse/'gold/eta_feature_store',
                                             ['route_id_idx','actual_eta_sec','baseline_eta_p50_sec','n_stations_ahead'])
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,default=ROOT/'data/hanoi_bus_system.db')
    parser.add_argument('--lakehouse',type=Path,default=ROOT/'data/lakehouse')
    parser.add_argument('--stage',choices=['silver','gold'],default='silver')
    args=parser.parse_args();print(json.dumps(verify(args.database,args.lakehouse,args.stage)))
