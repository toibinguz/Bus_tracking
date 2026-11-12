"""U3: recompute an immutable, published observed Silver snapshot from received HF batches."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from module_2_big_data_storage_and_lakehouse.step_2_4_hdfs_history.hf_bronze import descriptor, encoded, digest
from module_2_big_data_storage_and_lakehouse.step_2_4_hdfs_history.history_snapshot import normalize_bus, normalize_incident, merge_event, project_group

HDFS = 'hdfs://namenode:8020/bus-eta/v1'
PUBLICATIONS = HDFS + '/_published/history_snapshots'


def main():
    from pyspark.sql import SparkSession, functions as F
    from pyspark.sql.types import StructType, StructField, StringType, LongType, DoubleType
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', required=True)
    parser.add_argument('--fail-before-publish', action='store_true')
    args = parser.parse_args()
    if not args.reference.startswith(HDFS+'/reference/history/'):
        parser.error('expected immutable full history reference on HDFS')
    spark = SparkSession.builder.appName('bus-eta-history-snapshot').config('spark.sql.session.timeZone','Asia/Ho_Chi_Minh').getOrCreate()
    spark.sparkContext.setLogLevel('WARN')
    fs = spark._jvm.org.apache.hadoop.fs.FileSystem.get(spark._jsc.hadoopConfiguration())
    jpath = spark._jvm.org.apache.hadoop.fs.Path
    def read(path):
        return bytes(spark.read.format('binaryFile').load(path).first().content)
    def write_once(path, content):
        fs.mkdirs(jpath(path.rsplit('/',1)[0]))
        temp = path+'.tmp-'+str(uuid4())
        stream = fs.create(jpath(temp), False)
        try:
            stream.write(bytearray(content))
        finally:
            stream.close()
        if fs.exists(jpath(path)) or not fs.rename(jpath(temp), jpath(path)):
            raise RuntimeError('publication collision; existing output retained')
    try:
        ref_raw = read(args.reference)
        if '/sha256='+digest(ref_raw)+'/' not in args.reference:
            raise ValueError('reference content hash mismatch')
        reference = json.loads(ref_raw)
        manifests = [json.loads(bytes(row.content)) for row in spark.read.format('binaryFile').load(HDFS+'/_received/hf_batch/*/manifest.json').collect()]
        manifests.sort(key=lambda row: row['batch_id'])
        if len({row['batch_id'] for row in manifests}) != len(manifests):
            raise ValueError('duplicate batch manifest')
        from config import system_config as policy
        policy_keys = ['MAX_CORRIDOR_CROSS_TRACK_M','MAX_GPS_BACKWARD_JITTER_M','FRENET_MIN_FORWARD_WINDOW_M','FRENET_MAX_SPEED_MPS','GPS_DRIFT_MAX_SPEED_KMPH','STALE_DELTA_T_MAX_SEC','TERMINAL_RESET_ZONE_M','METERS_PER_DEG_LON_EQUATOR','METERS_PER_DEG_LAT']
        policy_values = {key:getattr(policy,key) for key in policy_keys}
        source_files = [Path(__file__), ROOT/'module_2_big_data_storage_and_lakehouse/step_2_4_hdfs_history/history_snapshot.py', ROOT/'module_2_big_data_storage_and_lakehouse/step_2_4_hdfs_history/contract.py', ROOT/'module_2_big_data_storage_and_lakehouse/step_2_4_hdfs_history/hf_bronze.py', ROOT/'module_1_data_ingestion_and_preprocessing/step_1_4_frenet_spatial_projection/projection_boundary.py', ROOT/'module_1_data_ingestion_and_preprocessing/step_1_4_frenet_spatial_projection/multi_route_projector.py']
        code_hash = digest(encoded({str(p.relative_to(ROOT)):digest(p.read_bytes()) for p in source_files}))
        identity = dict(schema_version='history-snapshot.v1', batches=[(m['batch_id'],m['content_sha256']) for m in manifests], reference_sha256=digest(ref_raw), code_sha256=code_hash, policy=policy_values)
        key = digest(encoded(identity))
        publication = PUBLICATIONS+'/'+key+'.json'
        if fs.exists(jpath(publication)):
            completed = json.loads(read(publication))
            if spark.read.parquet(completed['silver_path']).count() != completed['accepted_bus_rows']:
                raise ValueError('published snapshot output invalid')
            print('U3_RESULT='+json.dumps(dict(completed, noop=True)), flush=True)
            return
        attempt = HDFS+'/silver/history/_runs/snapshot='+key+'/attempt='+str(uuid4())
        bus_inputs, incident_inputs = [], []
        for manifest in manifests:
            raw_path = HDFS.split('/bus-eta/v1')[0]+manifest['hdfs_raw_path']
            raw = read(raw_path)
            expected = descriptor(manifest['dataset'],manifest['revision'],manifest['path'],raw)
            if any(manifest[k] != v for k,v in expected.items()):
                raise ValueError('received batch metadata/hash mismatch')
            frame = spark.read.text(raw_path).withColumn('batch_id', F.lit(manifest['batch_id']))
            (bus_inputs if manifest['category']=='bus' else incident_inputs).append(frame)
        if not bus_inputs:
            raise ValueError('no received bus batches')
        combined = bus_inputs[0]
        for frame in bus_inputs[1:]:
            combined = combined.unionByName(frame)
        normalized = combined.rdd.map(lambda row: normalize_bus(row.value,row.batch_id,reference)).cache()
        valid = normalized.filter(lambda pair:pair[0]=='event').map(lambda pair:pair[1]).cache()
        unique = valid.map(lambda row:(row['event_id'],row)).groupByKey().map(merge_event).cache()
        projected = unique.map(lambda row:(row['route_id'],row)).groupByKey().map(lambda pair:project_group(pair,reference)).cache()
        bus_schema = StructType([StructField(k,StringType(),True) for k in ('event_id','route_code','plate','device_update_time','direction','provenance')] + [StructField(k,LongType(),True) for k in ('legacy_ping_id','route_id','vehicle_id')] + [StructField(k,DoubleType(),True) for k in ('device_epoch_s','device_epoch','lat','lon','s_bus_m','cross_track_m','derived_speed_kmh')])
        silver_path = attempt+'/route_projected_telemetry'
        silver = spark.createDataFrame(projected.flatMap(lambda result: result['rows']), bus_schema)
        dated = silver.withColumn('dt', F.to_date(F.from_unixtime(F.col('device_epoch_s').cast('long'))).cast('string'))
        # Keep a readable schema even when every event is rejected.
        if dated.limit(1).count():
            dated.write.mode('errorifexists').partitionBy('dt').parquet(silver_path)
        else:
            dated.write.mode('errorifexists').parquet(silver_path)
        # Keep all unique event lineage, including ones subsequently rejected by projection.
        spark.read.json(unique.map(lambda row: encoded(row).decode())).write.mode('errorifexists').parquet(attempt+'/event_lineage')
        rejected = normalized.filter(lambda pair:pair[0]=='reject').map(lambda pair:pair[1]).union(projected.flatMap(lambda result:result['rejected']))
        rejected.map(lambda row:encoded(row).decode()).saveAsTextFile(attempt+'/rejects')
        projected.map(lambda row:encoded(dict(route_id=row['route_id'],counts=row['diagnostics'])).decode()).saveAsTextFile(attempt+'/projection_diagnostics')
        incident_rows, rejected_incidents = 0, 0
        if incident_inputs:
            all_incidents = incident_inputs[0]
            for frame in incident_inputs[1:]:
                all_incidents = all_incidents.unionByName(frame)
            # Canonical content identity preserves successive captures and null values.
            parsed_incidents = all_incidents.rdd.map(lambda row: normalize_incident(row.value,row.batch_id)).cache()
            incident_rejects = parsed_incidents.filter(lambda pair:pair[0]=='reject').map(lambda pair:encoded(pair[1]).decode())
            incident_rejects.saveAsTextFile(attempt+'/incident_rejects')
            rejected_incidents = incident_rejects.count()
            canonical_incidents = parsed_incidents.filter(lambda pair:pair[0]=='event').map(lambda pair:(pair[1]['raw_json'],pair[1]['batch_id'])).cache()
            observations = canonical_incidents.groupByKey().map(lambda pair:dict(observation_id=digest(pair[0].encode()), raw_json=pair[0], batch_ids=sorted(set(pair[1]))))
            incident_schema = 'observation_id string, raw_json string, batch_ids array<string>'
            incident_frame = spark.createDataFrame(observations,incident_schema)
            incident_frame.write.mode('errorifexists').parquet(attempt+'/incident_observations')
            incident_rows = spark.read.parquet(attempt+'/incident_observations').count()
        accepted = spark.read.parquet(silver_path).count()
        report = dict(identity, snapshot_id=key, silver_path=silver_path, snapshot_path=attempt,
                      reference_path=args.reference, source_manifests=manifests, accepted_bus_rows=accepted,
                      raw_bus_rows=normalized.count(), unique_bus_events=unique.count(),
                      duplicate_bus_observations=valid.count()-unique.count(), rejected_rows=rejected.count(),
                      incident_observations=incident_rows, rejected_incidents=rejected_incidents, published_at=datetime.now(timezone.utc).isoformat())
        write_once(attempt+'/reference.json',ref_raw)
        write_once(attempt+'/snapshot.json',encoded(report))
        if args.fail_before_publish:
            print('U3_UNPUBLISHED='+json.dumps(report),flush=True)
            raise RuntimeError('injected failure before publication')
        write_once(publication,encoded(report))
        print('U3_RESULT='+json.dumps(report),flush=True)
    finally:
        spark.stop()


if __name__ == '__main__':
    main()
