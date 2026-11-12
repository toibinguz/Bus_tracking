"""Versioned history cache, real ETA consumers and immutable HDFS artifacts."""
from contextlib import contextmanager
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import re
import sqlite3
from uuid import uuid4

from .hf_bronze import DockerHdfs, atomic_write, digest, encoded, ensure_object

ROOT = Path(__file__).resolve().parents[2]
HDFS = 'hdfs://namenode:8020/bus-eta/v1'


def transport():
    return DockerHdfs(ROOT/'docker-compose.hdfs.yml')


def read_json(store,path):
    return json.loads(store.read(path))


def files_manifest(root):
    return {path.relative_to(root).as_posix(): digest(path.read_bytes()) for path in sorted(root.rglob('*')) if path.is_file()}


def verify_files(root, manifest):
    root = Path(root).resolve()
    if not manifest:
        raise ValueError('empty file manifest')
    for relative, expected in manifest.items():
        path = (root/relative).resolve()
        if root not in path.parents or not path.is_file() or digest(path.read_bytes())!=expected:
            raise ValueError('file missing/corrupted/outside release: '+relative)


def parquet_table(store,path):
    import pyarrow as pa
    import pyarrow.parquet as pq
    listing = store.call('-ls','-R',path).decode()
    paths = sorted(line.split()[-1] for line in listing.splitlines() if line.split() and line.split()[-1].endswith('.parquet'))
    if not paths:
        raise ValueError('no Parquet parts: '+path)
    tables = [pq.read_table(io.BytesIO(store.read(part))) for part in paths]
    return pa.concat_tables(tables)


def materialize(snapshot_id, cache, dates, routes=None, store=None):
    if not re.fullmatch('[0-9a-f]{64}',snapshot_id):
        raise ValueError('invalid snapshot ID')
    cache = Path(cache)
    if cache.exists():
        raise ValueError('choose a new immutable cache directory')
    store = store or transport()
    raw = store.read(HDFS+'/_published/history_snapshots/'+snapshot_id+'.json')
    source = json.loads(raw)
    prefix = HDFS+'/silver/history/_runs/snapshot='+snapshot_id+'/attempt='
    if source['snapshot_id']!=snapshot_id or not source['snapshot_path'].startswith(prefix):
        raise ValueError('snapshot path mismatch')
    if source['silver_path']!=source['snapshot_path']+'/route_projected_telemetry':
        raise ValueError('Silver path belongs to another snapshot')
    if store.read(source['snapshot_path']+'/snapshot.json')!=raw:
        raise ValueError('snapshot not completed')
    reference_raw = store.read(source['reference_path'])
    if digest(reference_raw)!=source['reference_sha256']:
        raise ValueError('reference hash mismatch')
    frame = parquet_table(store,source['silver_path']).to_pandas()
    if len(frame)!=source['accepted_bus_rows']:
        raise ValueError('snapshot count mismatch')
    frame['dt'] = frame['device_update_time'].str[:10]
    frame = frame[frame['dt'].isin(dates)]
    if routes:
        frame = frame[frame['route_code'].isin(routes)]
    if frame.empty or set(frame['dt'])!=set(dates):
        raise ValueError('selected dates must all have real observations')
    if routes and set(frame['route_code'])!=set(routes):
        raise ValueError('selected routes must all have real observations')
    cache.mkdir(parents=True)
    silver = cache/'silver'/'route_projected_telemetry'
    for (route,day),group in frame.groupby(['route_code','dt']):
        target = silver/f'route_code={route}'/f'dt={day}'
        target.mkdir(parents=True)
        group.drop(columns=['route_code','dt']).to_parquet(target/'part.parquet',index=False)
    incident_count = 0
    if source['incident_observations']:
        incidents = parquet_table(store,source['snapshot_path']+'/incident_observations').to_pylist()
        by_day = {}
        for row in incidents:
            incident = json.loads(row['raw_json'])
            day = incident['timestamp'][:10]
            if day in dates:
                by_day.setdefault(day,[]).append(incident)
        for day, rows in by_day.items():
            target = cache/'raw'/day/'incidents'/'observed.jsonl'
            atomic_write(target,b'\n'.join(encoded(row) for row in rows)+b'\n')
            incident_count+=len(rows)
    atomic_write(cache/'reference.json',reference_raw)
    atomic_write(cache/'source.json',raw)
    info = dict(schema_version='eta-history-cache.v1',snapshot_id=snapshot_id,dates=sorted(dates),routes=sorted(routes) if routes else None,
                ping_count=len(frame),incident_observations=incident_count,files=files_manifest(cache))
    info['cache_id']=digest(encoded(info))
    atomic_write(cache/'cache.json',encoded(info))
    return verify_cache(cache)


def verify_cache(cache):
    info = json.loads((Path(cache)/'cache.json').read_text(encoding='utf-8'))
    verify_files(cache,info['files'])
    if set(files_manifest(Path(cache)))!=set(info['files'])|{'cache.json'}:
        raise ValueError('unlisted files in cache')
    identity = {k:v for k,v in info.items() if k!='cache_id'}
    if digest(encoded(identity))!=info['cache_id']:
        raise ValueError('cache identity mismatch')
    return info


@contextmanager
def paths(module, **selected):
    previous = {key:getattr(module,key) for key in selected}
    try:
        for key,value in selected.items():
            setattr(module,key,str(value))
        yield
    finally:
        for key,value in previous.items():
            setattr(module,key,value)


def build(cache,output,workers=2):
    import pandas as pd
    import pyarrow as pa
    import pyarrow.dataset as ds
    cache,output = Path(cache).resolve(),Path(output).resolve()
    info = verify_cache(cache)
    if output.exists():
        raise ValueError('choose a fresh output workspace')
    output.mkdir(parents=True)
    reference = json.loads((cache/'reference.json').read_text(encoding='utf-8'))
    silver = cache/'silver'/'route_projected_telemetry'
    partitioning=ds.partitioning(pa.schema([('route_code',pa.string()),('dt',pa.string())]),flavor='hive')
    frame = ds.dataset(silver,format='parquet',partitioning=partitioning).to_table().to_pandas()
    database = output/'baseline.db'
    with sqlite3.connect(database) as conn:
        pd.DataFrame(reference['stations']).to_sql('canonical_station_master',conn,index=False)
        shape_rows = [dict(route_id=int(route),route_code=reference['routes'][route],direction=direction,point_order=p[0],lat=p[1],lon=p[2],cum_distance_m=p[3]) for route, directions in reference['shapes'].items() for direction, points in directions.items() for p in points]
        pd.DataFrame(shape_rows).to_sql('canonical_shape_master',conn,index=False)
        frame.to_sql('route_projected_telemetry',conn,index=False)
    from module_3_bus_eta_prediction.step_3_1_historical_baseline_model import baseline_matrix_builder as baseline
    with paths(baseline,DB_PATH=database,SILVER_TEL_DIR=silver,GOLD_BASELINE_DIR=output/'gold'/'agg_segment_travel_times'):
        baseline_result = baseline.build_and_evaluate_baseline_matrix()
    incident_rows=0
    if info['incident_observations']:
        from module_1_data_ingestion_and_preprocessing.step_1_4_frenet_spatial_projection import tomtom_incident_projector as incidents
        with paths(incidents,DB_PATH=database,INCIDENTS_GLOB=cache/'raw'/'*'/'incidents'/'*.jsonl'):
            incidents.main()
        with sqlite3.connect(database) as conn:
            facts=pd.read_sql_query('SELECT * FROM fact_route_tomtom_incidents',conn)
        incident_rows=len(facts)
        for route,group in facts.groupby('route_code'):
            target=output/'silver'/'fact_route_tomtom_incidents'/f'route_code={route}'
            target.mkdir(parents=True)
            group.drop(columns=['route_code']).to_parquet(target/'part.parquet',index=False)
    from module_3_bus_eta_prediction.step_3_2_feature_store_extractor import feature_store_builder as features
    with paths(features,DB_PATH=database,SILVER_TEL_DIR=silver,SILVER_INC_DIR=output/'silver'/'fact_route_tomtom_incidents',GOLD_FEATURE_DIR=output/'gold'/'eta_feature_store'):
        feature_result=features.build_gold_feature_store(max_workers=workers)
    atomic_write(output/'source_snapshot.json',(cache/'source.json').read_bytes())
    from config import system_config as policy
    domain_policy={key:getattr(baseline,key) for key in dir(baseline) if key.startswith(('BRACKET_','BASELINE_','SEGMENT_','DAY_TYPE_','EXCLUDE_TERMINAL')) and isinstance(getattr(baseline,key),(int,float,bool,str))}
    domain_policy.update({key:getattr(features,key) for key in ('RECENT_PROBE_WINDOW_SEC','FLEET_ACTIVE_WINDOW_SEC','MIN_EGO_SAMPLE_ADVANCE_M')})
    lineage=dict(schema_version='eta-artifact.v1',snapshot_id=info['snapshot_id'],cache_id=info['cache_id'],selection=dict(dates=info['dates'],routes=info['routes']),
                 execution='local existing domain algorithms; Silver was processed by distributed Spark',
                 split=dict(train_end=policy.TRAIN_SPLIT_END_DATE,test_start=policy.TEST_SPLIT_START_DATE),
                 baseline_result=baseline_result,feature_result=feature_result,incident_fact_rows=incident_rows,
                 domain_policy=domain_policy,incident_projector_sha256=digest((ROOT/'module_1_data_ingestion_and_preprocessing/step_1_4_frenet_spatial_projection/tomtom_incident_projector.py').read_bytes()),
                 pipeline_sha256=digest(Path(__file__).read_bytes()),
                 code={str(Path(module.__file__).relative_to(ROOT)):digest(Path(module.__file__).read_bytes()) for module in (baseline,features)},
                 files=files_manifest(output))
    lineage['artifact_id']=digest(encoded(lineage))
    atomic_write(output/'artifact.json',encoded(lineage))
    return lineage


def verify_artifact(output):
    info=json.loads((Path(output)/'artifact.json').read_text(encoding='utf-8'))
    verify_files(output,info['files'])
    if set(files_manifest(Path(output)))!=set(info['files'])|{'artifact.json'}:
        raise ValueError('unlisted files in release')
    if digest(encoded({k:v for k,v in info.items() if k!='artifact_id'}))!=info['artifact_id']:
        raise ValueError('artifact identity mismatch')
    return info


def publish(output,store=None):
    output=Path(output)
    info=verify_artifact(output)
    store=store or transport()
    root=HDFS+'/gold/eta_artifacts/'+info['artifact_id']
    for relative in info['files']:
        ensure_object(store,root+'/'+relative,(output/relative).read_bytes())
    ensure_object(store,root+'/artifact.json',encoded(info))
    ensure_object(store,HDFS+'/_published/eta_artifacts/'+info['artifact_id']+'.json',encoded(info))
    return dict(artifact_id=info['artifact_id'],hdfs_root=root)


def download(artifact_id,release_root,store=None):
    if not re.fullmatch('[0-9a-f]{64}',artifact_id):
        raise ValueError('invalid artifact ID')
    store=store or transport()
    raw=store.read(HDFS+'/_published/eta_artifacts/'+artifact_id+'.json')
    info=json.loads(raw)
    if info['artifact_id']!=artifact_id or digest(encoded({k:v for k,v in info.items() if k!='artifact_id'}))!=artifact_id:
        raise ValueError('published artifact identity mismatch')
    release=Path(release_root)/artifact_id
    if release.exists():
        existing=verify_artifact(release)
        if existing['artifact_id']!=artifact_id:
            raise ValueError('existing release belongs to another artifact')
        return release
    temporary=Path(release_root)/('pending-'+str(uuid4()))
    temporary.mkdir(parents=True)
    for relative,expected in info['files'].items():
        target=(temporary/relative).resolve()
        if temporary.resolve() not in target.parents:
            raise ValueError('artifact file outside release')
        content=store.read(HDFS+'/gold/eta_artifacts/'+artifact_id+'/'+relative)
        if digest(content)!=expected:
            raise ValueError('download hash mismatch')
        atomic_write(target,content)
    atomic_write(temporary/'artifact.json',raw)
    verify_artifact(temporary)
    temporary.rename(release)
    return release


def activate(release, pointer):
    release=Path(release).resolve()
    info=verify_artifact(release)
    value=dict(artifact_id=info['artifact_id'],snapshot_id=info['snapshot_id'],release=str(release),activated_at=datetime.now(timezone.utc).isoformat())
    atomic_write(pointer,encoded(value))
    return value


def inspect_active(pointer):
    value=json.loads(Path(pointer).read_text(encoding='utf-8'))
    info=verify_artifact(value['release'])
    if info['artifact_id']!=value['artifact_id'] or info['snapshot_id']!=value['snapshot_id']:
        raise ValueError('active pointer/release mismatch')
    return value


def baseline_lookup(database, route_code, direction, from_order, to_order, day_type, hour_slot):
    """Read the normal baseline table; usable for both operational local and release DBs."""
    database=Path(database).resolve()
    with sqlite3.connect(database.as_uri()+'?mode=ro',uri=True) as conn:
        conn.row_factory=sqlite3.Row
        row=conn.execute('SELECT * FROM agg_segment_travel_times WHERE route_code=? AND direction=? AND from_station_order=? AND to_station_order=? AND day_type=? AND hour_slot=?',
                         (route_code,direction,from_order,to_order,day_type,hour_slot)).fetchone()
    return dict(row) if row else None
