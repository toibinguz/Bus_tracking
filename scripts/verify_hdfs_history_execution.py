"""Distributed accounting/uniqueness checks, optionally comparing a prior snapshot."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from module_2_big_data_storage_and_lakehouse.step_2_4_hdfs_history.history_query import load_history_snapshot


def main():
    from pyspark.sql import SparkSession, functions as F
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',required=True)
    parser.add_argument('--baseline')
    args=parser.parse_args()
    spark=(SparkSession.builder.appName('verify-bounded-history').config('spark.sql.session.timeZone','Asia/Ho_Chi_Minh')
           .config('spark.sql.shuffle.partitions','32').getOrCreate())
    spark.sparkContext.setLogLevel('WARN')
    try:
        info=load_history_snapshot(spark,args.snapshot)
        frame=spark.read.parquet(info['silver_path'])
        count=frame.count()
        assert count==info['accepted_bus_rows']
        assert frame.select('event_id').distinct().count()==count,'duplicate accepted event'
        assert info['raw_bus_rows']==count+info['rejected_rows']+info['duplicate_bus_observations']
        lineage=spark.read.parquet(info['snapshot_path']+'/event_lineage')
        assert lineage.count()==info['unique_bus_events']
        assert lineage.select('event_id').distinct().count()==lineage.count(),'duplicate lineage event'
        assert lineage.where(F.size('batch_ids')<1).limit(1).count()==0,'missing batch association'
        known=spark.createDataFrame([(row['batch_id'],) for row in info['source_manifests']],['batch_id'])
        associations=lineage.select(F.explode('batch_ids').alias('batch_id'))
        assert associations.join(F.broadcast(known),'batch_id','left_anti').limit(1).count()==0,'unknown batch association'
        assert frame.select('event_id').subtract(lineage.select('event_id')).count()==0
        actual=[dict(route_code=row.route_code,dt=str(row.dt),rows=row['count']) for row in frame.groupBy('route_code','dt').count().collect()]
        canonical=lambda rows:sorted(rows,key=lambda row:(row['route_code'],row['dt']))
        assert canonical(actual)==canonical(info['silver_partitions'])
        assert info['execution']['largest_session_events']<=info['execution']['max_session_events']
        assert info['execution']['verified_batches']==len(info['source_manifests'])
        result=dict(snapshot_id=args.snapshot,accepted_bus_rows=count,raw_bus_rows=info['raw_bus_rows'],
                    unique_bus_events=info['unique_bus_events'],partition_count=len(actual),
                    accounting=True,unique_events=True,lineage=True,partition_index=True,execution=info['execution'])
        if args.baseline:
            before=load_history_snapshot(spark,args.baseline)
            assert before['batches']==info['batches'],'parity requires identical input batches'
            assert before['reference_sha256']==info['reference_sha256']
            other=spark.read.parquet(before['silver_path'])
            columns=sorted(frame.columns)
            assert frame.select(columns).exceptAll(other.select(columns)).count()==0
            assert other.select(columns).exceptAll(frame.select(columns)).count()==0
            previous=spark.read.parquet(before['snapshot_path']+'/event_lineage')
            # Check every normalized field and association, not just accepted-row counts.
            columns=sorted(lineage.columns)
            assert lineage.select(columns).exceptAll(previous.select(columns)).count()==0
            assert previous.select(columns).exceptAll(lineage.select(columns)).count()==0
            for name in ('raw_bus_rows','unique_bus_events','duplicate_bus_observations','rejected_rows','incident_observations','rejected_incidents'):
                assert info[name]==before[name],name
            result.update(baseline=args.baseline,exact_silver_and_lineage_parity=True)
        print('HISTORY_VERIFIED='+json.dumps(result),flush=True)
    finally:
        spark.stop()


if __name__=='__main__':
    main()
