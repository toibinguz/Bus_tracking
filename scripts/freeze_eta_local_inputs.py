"""Freeze read-only serving tables and incident Parquet for independent replay."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from config.system_config import DEFAULT_DB_PATH,DEFAULT_LAKEHOUSE_ROOT


def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def freeze(session):
    session=Path(session).resolve();target=session/'local_inputs.json'
    if target.exists():return json.loads(target.read_text())
    manifest=json.loads((session/'session.json').read_text(encoding='utf-8'))
    if manifest['health']['serving']['mode']!='local':raise ValueError('local snapshot only supports local mode')
    source=(ROOT/DEFAULT_DB_PATH).resolve();database=session/'artifacts/serving.db'
    if database.exists():raise ValueError('partial snapshot exists; preserve it and choose another output')
    database.parent.mkdir(parents=True,exist_ok=True)
    counts={}
    with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as src,sqlite3.connect(database) as dest:
        src.execute('BEGIN')
        for table in ('canonical_route_master','canonical_station_master','canonical_shape_master','agg_segment_travel_times'):
            ddl=src.execute('SELECT sql FROM sqlite_master WHERE type=\'table\' AND name=?',(table,)).fetchone()[0]
            dest.execute(ddl);cursor=src.execute('SELECT * FROM '+table)
            placeholders=','.join('?' for _ in cursor.description);n=0
            while rows:=cursor.fetchmany(10000):
                dest.executemany('INSERT INTO '+table+' VALUES ('+placeholders+')',rows);n+=len(rows)
            counts[table]=n
    files={database.relative_to(session).as_posix():digest(database)}
    for selected in manifest['selected']:
        directory=ROOT/DEFAULT_LAKEHOUSE_ROOT/'silver/fact_route_tomtom_incidents'/('route_code='+selected['route'])
        if not directory.is_dir():continue
        for path in directory.rglob('*.parquet'):
            dest=session/'local_lakehouse/silver/fact_route_tomtom_incidents'/directory.name/path.relative_to(directory)
            dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,dest)
            files[dest.relative_to(session).as_posix()]=digest(dest)
    result=dict(tables=counts,files=files,
                provenance='read-only snapshot recovered during validation; API geometry is checked by geometry.json and feature replay checks used values')
    target.write_text(json.dumps(result,indent=2),encoding='utf-8');return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--session',type=Path,required=True)
    print(json.dumps(freeze(parser.parse_args().session)))
