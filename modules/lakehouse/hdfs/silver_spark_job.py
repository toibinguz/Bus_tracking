"""U3: recompute an immutable, published observed Silver snapshot from received HF batches."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from modules.lakehouse.hdfs.hf_bronze import encoded, digest
from modules.lakehouse.hdfs.history_execution import read_batches
from modules.lakehouse.pipeline.silver import merge_bus, project_vehicles, event_pair, ordered_event

HDFS = 'hdfs://namenode:8020/bus-eta/v1'
PUBLICATIONS = HDFS + '/_published/history_snapshots'


from modules.lakehouse.pipeline.spec import (
    FEATURE_START, FORECAST_SECONDS, MAX_SESSION_EVENTS, logic_version, run_pipeline, stage_manifest, validate_counts,
)
from modules.lakehouse.hdfs.spark_adapter import SparkAdapter, cli_spec
from config.system_config import BASELINE_FIT_END_DATE, TEST_SPLIT_START_DATE, TEST_SPLIT_END_DATE


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', required=True)
    selection=parser.add_mutually_exclusive_group(required=True)
    selection.add_argument('--batch-id',nargs='+',help='explicit bounded set of received HF batches')
    selection.add_argument('--all-received',action='store_true',help='explicitly process the entire received ledger')
    parser.add_argument('--partitions',type=int,default=32)
    parser.add_argument('--max-session-events','--max-vehicle-events',dest='max_session_events',type=int,default=MAX_SESSION_EVENTS)
    parser.add_argument('--max-batch-bytes',type=int,default=16*1024*1024)
    parser.add_argument('--fail-before-publish', action='store_true')
    parser.add_argument("--routes", nargs="+")
    parser.add_argument("--build-gold", action="store_true")
    parser.add_argument("--export-features", action="store_true")
    parser.add_argument("--from-day", default=FEATURE_START)
    parser.add_argument("--to-day", default=TEST_SPLIT_END_DATE)
    parser.add_argument("--fit-end-date", default=BASELINE_FIT_END_DATE)
    parser.add_argument("--test-start", default=TEST_SPLIT_START_DATE)
    parser.add_argument("--validation-start")
    parser.add_argument("--forecast-every", type=float, default=FORECAST_SECONDS)
    parser.add_argument("--feature-routes", nargs="+")
    parser.add_argument("--all-routes", action="store_true")
    args = parser.parse_args()
    stages = ("silver", "baseline", "features") if args.export_features else (("silver", "baseline") if args.build_gold else ("silver",))
    return run_pipeline(cli_spec(args, stages), SparkAdapter(args))


def execute(spec, args):
    from pyspark.sql import SparkSession, functions as F
    from pyspark import StorageLevel
    from modules.lakehouse.hdfs.spark_schema import spark_schema
    from modules.lakehouse.pipeline.schema import SILVER
    if min(args.partitions,args.max_session_events,args.max_batch_bytes)<1:
        raise ValueError('execution limits must be positive')
    started=time.monotonic()
    if not args.reference.startswith(HDFS+'/reference/history/'):
        raise ValueError('expected immutable full history reference on HDFS')
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
        source_files = [Path(__file__), ROOT/'modules/lakehouse/hdfs/history_execution.py', ROOT/'modules/lakehouse/hdfs/artifact_transport.py', ROOT/'modules/lakehouse/hdfs/history_snapshot.py', ROOT/'modules/lakehouse/hdfs/contract.py', ROOT/'modules/lakehouse/hdfs/hf_bronze.py', ROOT/'modules/ingestion/projection/projection_boundary.py', ROOT/'modules/ingestion/projection/route_matcher.py']
        code_hash = digest(encoded({str(p.relative_to(ROOT)):digest(p.read_bytes()) for p in source_files}))
        identity = dict(schema_version='history-snapshot.v1', batches=[(m['batch_id'],m['content_sha256']) for m in manifests], reference_sha256=digest(ref_raw), code_sha256=code_hash, policy=policy_values, logic_version=logic_version(), silver_routes=spec.routes, silver_start=spec.silver_start)
        key = digest(encoded(identity))
        publication = PUBLICATIONS+'/'+key+'.json'
        if fs.exists(jpath(publication)):
            completed = json.loads(read(publication))
            if spark.read.parquet(completed['silver_path']).count() != completed['accepted_bus_rows']:
                raise ValueError('published snapshot output invalid')
            print('U3_RESULT='+json.dumps(dict(completed, noop=True)), flush=True)
            return completed
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
        unique = (valid.map(event_pair)
                  .reduceByKey(merge_bus,args.partitions).values().persist(StorageLevel.DISK_ONLY))
        ordered = unique.map(ordered_event)
        ordered = ordered.repartitionAndSortWithinPartitions(args.partitions,lambda key:key[0]*1000003+key[1])
        projected = ordered.mapPartitions(lambda rows:project_vehicles(rows,reference,max_session_events,spec)).persist(StorageLevel.DISK_ONLY)
        bus_schema = spark_schema(SILVER + (("dt","string",True),))
        silver_path = attempt+'/route_projected_telemetry'
        silver = spark.createDataFrame(projected.flatMap(lambda result: result['rows']), bus_schema)
        dated = silver
        # Keep a readable schema even when every event is rejected.
        if dated.limit(1).count():
            dated.repartition(args.partitions,'route_code','dt').write.mode('errorifexists').partitionBy('route_code','dt').parquet(silver_path)
        else:
            dated.write.mode('errorifexists').parquet(silver_path)
        # Keep all unique event lineage, including ones subsequently rejected by projection.
        spark.read.schema('event_id string, route_id long, route_code string, vehicle_id long, observed_ms long, captured_ms long, lat double, lon double, batch_id string, raw_json string, batch_ids array<string>').json(unique.map(lambda row: encoded(row).decode())).write.mode('errorifexists').parquet(attempt+'/event_lineage')
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
        engines = projected.map(lambda row:row["engine"]).distinct().collect()
        report = stage_manifest("silver", spec, engines, build_id=key, **report)
        write_once(attempt+'/reference.json',ref_raw)
        write_once(attempt+'/snapshot.json',encoded(report))
        if args.fail_before_publish:
            print('U3_UNPUBLISHED='+json.dumps(report),flush=True)
            raise RuntimeError('injected failure before publication')
        write_once(publication,encoded(report))
        print('U3_RESULT='+json.dumps(report),flush=True)
        return report
    finally:
        for rdd_name in ('projected', 'unique', 'normalized'):
            rdd_obj = locals().get(rdd_name)
            if rdd_obj is not None:
                try:
                    rdd_obj.unpersist()
                except Exception:
                    pass
        spark.stop()


if __name__ == '__main__':
    main()
