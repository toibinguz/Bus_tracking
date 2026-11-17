"""U3: recompute an immutable, published observed Silver snapshot from received HF batches."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from module_2_big_data_storage_and_lakehouse.step_2_4_hdfs_history.hf_bronze import encoded, digest
from module_2_big_data_storage_and_lakehouse.step_2_4_hdfs_history.history_execution import read_batches, merge_bus, project_vehicles

HDFS = 'hdfs://namenode:8020/bus-eta/v1'
PUBLICATIONS = HDFS + '/_published/history_snapshots'


def main():
    from pyspark.sql import SparkSession, functions as F
    from pyspark import StorageLevel
    from pyspark.sql.types import StructType, StructField, StringType, LongType, DoubleType
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', required=True)
    selection=parser.add_mutually_exclusive_group(required=True)
    selection.add_argument('--batch-id',nargs='+',help='explicit bounded set of received HF batches')
    selection.add_argument('--all-received',action='store_true',help='explicitly process the entire received ledger')
    parser.add_argument('--partitions',type=int,default=32)
    parser.add_argument('--max-session-events','--max-vehicle-events',dest='max_session_events',type=int,default=20000)
    parser.add_argument('--max-batch-bytes',type=int,default=16*1024*1024)
    parser.add_argument('--fail-before-publish', action='store_true')
    args = parser.parse_args()
    if min(args.partitions,args.max_session_events,args.max_batch_bytes)<1:
        parser.error('execution limits must be positive')
    started=time.monotonic()
    if not args.reference.startswith(HDFS+'/reference/history/'):
        parser.error('expected immutable full history reference on HDFS')
    spark = (SparkSession.builder.appName('bus-eta-history-snapshot').config('spark.sql.session.timeZone','Asia/Ho_Chi_Minh')
             .config('spark.sql.sources.partitionColumnTypeInference.enabled','false').getOrCreate())
    spark.sparkContext.setLogLevel('WARN')
    spark.conf.set('spark.sql.shuffle.partitions',str(args.partitions))
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
        if args.batch_id:
            requested=set(args.batch_id)
            manifests=[manifest for manifest in manifests if manifest['batch_id'] in requested]
            if {manifest['batch_id'] for manifest in manifests}!=requested:
                raise ValueError('requested received batch missing')
        manifests.sort(key=lambda row: row['batch_id'])
        print('HISTORY_INPUT='+json.dumps(dict(batches=len(manifests),bytes=sum(row['bytes'] for row in manifests))),flush=True)
        if len({row['batch_id'] for row in manifests}) != len(manifests):
            raise ValueError('duplicate batch manifest')
        from config import system_config as policy
        policy_keys = ['MAX_CORRIDOR_CROSS_TRACK_M','MAX_GPS_BACKWARD_JITTER_M','FRENET_MIN_FORWARD_WINDOW_M','FRENET_MAX_SPEED_MPS','GPS_DRIFT_MAX_SPEED_KMPH','STALE_DELTA_T_MAX_SEC','TERMINAL_RESET_ZONE_M','METERS_PER_DEG_LON_EQUATOR','METERS_PER_DEG_LAT']
        policy_values = {key:getattr(policy,key) for key in policy_keys}
        source_files = [Path(__file__), ROOT/'module_2_big_data_storage_and_lakehouse/step_2_4_hdfs_history/history_execution.py', ROOT/'module_2_big_data_storage_and_lakehouse/step_2_4_hdfs_history/artifact_transport.py', ROOT/'module_2_big_data_storage_and_lakehouse/step_2_4_hdfs_history/history_snapshot.py', ROOT/'module_2_big_data_storage_and_lakehouse/step_2_4_hdfs_history/contract.py', ROOT/'module_2_big_data_storage_and_lakehouse/step_2_4_hdfs_history/hf_bronze.py', ROOT/'module_1_data_ingestion_and_preprocessing/step_1_4_frenet_spatial_projection/projection_boundary.py', ROOT/'module_1_data_ingestion_and_preprocessing/step_1_4_frenet_spatial_projection/multi_route_projector.py']
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
        if not any(m['category']=='bus' for m in manifests):
            raise ValueError('no received bus batches')
        max_batch_bytes,max_session_events=args.max_batch_bytes,args.max_session_events
        normalized = spark.sparkContext.parallelize(manifests,args.partitions).mapPartitions(
            lambda rows:read_batches(rows,reference,max_batch_bytes)).persist(StorageLevel.DISK_ONLY)
        counts=dict(normalized.map(lambda pair:(pair[0],1)).reduceByKey(lambda a,b:a+b).collect())
        print('HISTORY_NORMALIZED='+json.dumps(counts),flush=True)
        if counts.get('batch',0)!=len(manifests):
            raise ValueError('not every input batch was verified')
        valid = normalized.filter(lambda pair:pair[0]=='bus_event').map(lambda pair:pair[1])
        unique = (valid.map(lambda row:(row['event_id'],dict(row,batch_ids=[row['batch_id']])))
                  .reduceByKey(merge_bus,args.partitions).values().persist(StorageLevel.DISK_ONLY))
        ordered = unique.map(lambda row:((row['route_id'],row['vehicle_id'],row['observed_ms'],row['event_id']),row))
        ordered = ordered.repartitionAndSortWithinPartitions(args.partitions,lambda key:key[0]*1000003+key[1])
        projected = ordered.mapPartitions(lambda rows:project_vehicles(rows,reference,max_session_events)).persist(StorageLevel.DISK_ONLY)
        bus_schema = StructType([StructField(k,StringType(),True) for k in ('event_id','route_code','plate','device_update_time','direction','provenance')] + [StructField(k,LongType(),True) for k in ('legacy_ping_id','route_id','vehicle_id')] + [StructField(k,DoubleType(),True) for k in ('device_epoch_s','device_epoch','lat','lon','s_bus_m','cross_track_m','derived_speed_kmh')])
        silver_path = attempt+'/route_projected_telemetry'
        silver = spark.createDataFrame(projected.flatMap(lambda result: result['rows']), bus_schema)
        dated = silver.withColumn('dt', F.to_date(F.from_unixtime(F.col('device_epoch_s').cast('long'))).cast('string'))
        # Keep a readable schema even when every event is rejected.
        if dated.limit(1).count():
            dated.repartition(args.partitions,'route_code','dt').write.mode('errorifexists').partitionBy('route_code','dt').parquet(silver_path)
        else:
            dated.write.mode('errorifexists').parquet(silver_path)
        # Keep all unique event lineage, including ones subsequently rejected by projection.
        spark.read.json(unique.map(lambda row: encoded(row).decode())).write.mode('errorifexists').parquet(attempt+'/event_lineage')
        rejected = normalized.filter(lambda pair:pair[0]=='bus_reject').map(lambda pair:pair[1]).union(projected.flatMap(lambda result:result['rejected']))
        rejected.map(lambda row:encoded(row).decode()).saveAsTextFile(attempt+'/rejects')
        projected.map(lambda row:encoded({key:row[key] for key in ('route_id','vehicle_id','session_start_ms','session_end_ms','input_events','executor_host','worker_peak_rss_kib','diagnostics')}).decode()).saveAsTextFile(attempt+'/projection_diagnostics')
        incident_rows, rejected_incidents = 0, 0
        if any(m['category']=='incidents' for m in manifests):
            # Canonical content identity preserves successive captures and null values.
            incident_rejects = normalized.filter(lambda pair:pair[0]=='incidents_reject').map(lambda pair:encoded(pair[1]).decode())
            incident_rejects.saveAsTextFile(attempt+'/incident_rejects')
            rejected_incidents = incident_rejects.count()
            canonical_incidents = normalized.filter(lambda pair:pair[0]=='incidents_event').map(lambda pair:(pair[1]['raw_json'],{pair[1]['batch_id']}))
            observations = canonical_incidents.reduceByKey(lambda a,b:a|b,args.partitions).map(lambda pair:dict(observation_id=digest(pair[0].encode()), raw_json=pair[0], batch_ids=sorted(pair[1])))
            incident_schema = 'observation_id string, raw_json string, batch_ids array<string>'
            incident_frame = spark.createDataFrame(observations,incident_schema)
            incident_frame = incident_frame.withColumn('dt',F.to_date(F.to_timestamp(F.get_json_object('raw_json','$.timestamp'))).cast('string'))
            incident_frame.repartition('dt').write.mode('errorifexists').partitionBy('dt').parquet(attempt+'/incident_observations')
            incident_rows = spark.read.parquet(attempt+'/incident_observations').count()
        accepted = spark.read.parquet(silver_path).count()
        report = dict(identity, snapshot_id=key, silver_path=silver_path, snapshot_path=attempt,
                      reference_path=args.reference, source_manifests=manifests, accepted_bus_rows=accepted,
                      raw_bus_rows=counts.get('bus_event',0)+counts.get('bus_reject',0), unique_bus_events=unique.count(),
                      duplicate_bus_observations=counts.get('bus_event',0)-unique.count(), rejected_rows=rejected.count(),
                      incident_observations=incident_rows, rejected_incidents=rejected_incidents, published_at=datetime.now(timezone.utc).isoformat())
        report['bronze_only_traffic_batches']=sum(manifest['category']=='traffic' for manifest in manifests)
        if report['raw_bus_rows']!=accepted+report['rejected_rows']+report['duplicate_bus_observations']:
            raise ValueError('bus row accounting mismatch; snapshot not published')
        report['raw_incident_rows']=counts.get('incidents_event',0)+counts.get('incidents_reject',0)
        report['duplicate_incident_observations']=counts.get('incidents_event',0)-incident_rows
        report['silver_partitions']=[dict(route_code=row.route_code,dt=str(row.dt),rows=row['count']) for row in spark.read.parquet(silver_path).groupBy('route_code','dt').count().collect()]
        measurements=projected.map(lambda row:(row['input_events'],row['worker_peak_rss_kib'],row['executor_host'])).collect()
        report['execution']=dict(partitions=args.partitions,max_session_events=max_session_events,max_batch_bytes=max_batch_bytes,
            vehicle_sessions=len(measurements),largest_session_events=max((row[0] for row in measurements),default=0),
            peak_worker_rss_kib=max((row[1] for row in measurements),default=0),executor_hosts=sorted({row[2] for row in measurements}),
            verified_batches=counts.get('batch',0),verified_raw_bytes=sum(m['bytes'] for m in manifests),elapsed_seconds=round(time.monotonic()-started,3))
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
