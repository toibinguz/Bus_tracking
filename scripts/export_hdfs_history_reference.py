"""Export full canonical route/station/shape reference read-only and upload immutably."""
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from module_2_big_data_storage_and_lakehouse.step_2_4_hdfs_history.hf_bronze import DockerHdfs, atomic_write, digest, encoded, ensure_object


def main(database, output):
    with sqlite3.connect(Path(database).resolve().as_uri()+'?mode=ro', uri=True) as conn:
        conn.row_factory = sqlite3.Row
        routes = {str(row['route_id']): row['route_code'] for row in conn.execute('SELECT route_id,route_code FROM canonical_route_master ORDER BY route_id')}
        stations = [dict(row) for row in conn.execute('SELECT route_id,route_code,direction,station_id,station_order,station_name,cum_distance_m FROM canonical_station_master ORDER BY route_id,direction,station_order')]
        shapes = {}
        for row in conn.execute('SELECT route_id,direction,point_order,lat,lon,cum_distance_m FROM canonical_shape_master ORDER BY route_id,direction,point_order'):
            shapes.setdefault(str(row['route_id']), {}).setdefault(row['direction'], []).append([row['point_order'],row['lat'],row['lon'],row['cum_distance_m']])
    content = encoded(dict(schema_version='history-reference.v1', routes=routes, stations=stations, shapes=shapes))
    target = Path(output)
    if target.exists() and target.read_bytes() != content:
        raise ValueError('local reference output already differs')
    atomic_write(target, content)
    remote = '/bus-eta/v1/reference/history/sha256='+digest(content)+'/reference.json'
    ensure_object(DockerHdfs(ROOT/'docker-compose.hdfs.yml'), remote, content)
    print('hdfs://namenode:8020'+remote, flush=True)


if __name__ == '__main__':
    main(*sys.argv[1:])
