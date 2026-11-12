"""Verify published U3 rows against local canonical projection and independent Spark SQL."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from module_2_big_data_storage_and_lakehouse.step_2_4_hdfs_history.history_snapshot import normalize_bus, merge_event, project_group
from module_2_big_data_storage_and_lakehouse.step_2_4_hdfs_history.history_query import load_history_snapshot, query_snapshot_speed


def main():
    from pyspark.sql import SparkSession
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',required=True)
    parser.add_argument('--previous')
    args = parser.parse_args()
    spark = SparkSession.builder.appName('verify-history-snapshot').config('spark.sql.session.timeZone','Asia/Ho_Chi_Minh').getOrCreate()
    spark.sparkContext.setLogLevel('WARN')
    def read(path):
        return bytes(spark.read.format('binaryFile').load(path).first().content)
    try:
        manifest = load_history_snapshot(spark,args.snapshot)
        reference = json.loads(read(manifest['reference_path']))
        grouped = defaultdict(list)
        batch_ids = defaultdict(set)
        for source in manifest['source_manifests']:
            if source['category'] != 'bus':
                continue
            content = read('hdfs://namenode:8020'+source['hdfs_raw_path'])
            for line in content.decode().splitlines():
                kind, row = normalize_bus(line,source['batch_id'],reference)
                if kind=='event':
                    grouped[row['event_id']].append(row)
                    batch_ids[row['event_id']].add(source['batch_id'])
        routes = defaultdict(list)
        for key, observations in grouped.items():
            row = merge_event((key,observations))
            routes[row['route_id']].append(row)
        local = [row for route,events in routes.items() for row in project_group((route,events),reference)['rows']]
        actual = spark.read.parquet(manifest['silver_path'])
        columns = sorted(k for k in actual.columns if k!='dt')
        def canonical_rows(rows):
            return sorted([json.dumps({k:row[k] for k in columns},sort_keys=True) for row in rows])
        assert canonical_rows(actual.collect()) == canonical_rows(local), 'distributed/local canonical projection mismatch'
        assert actual.count() == manifest['accepted_bus_rows']
        actual.createOrReplaceTempView('u3_silver')
        sql = spark.sql("SELECT dt, count(*) ping_count, count(derived_speed_kmh) speed_sample_count, avg(derived_speed_kmh) avg_speed_kmh FROM u3_silver WHERE route_code='08A' AND dt='2026-11-12' GROUP BY dt").collect()
        query = query_snapshot_speed(spark,args.snapshot,'08A','2026-11-12','2026-11-12')
        independent = [dict(row.asDict(),dt=str(row.dt)) for row in sql]
        assert query['rows'] == independent, 'query/Spark SQL mismatch'
        result = dict(snapshot_id=args.snapshot,accepted_bus_rows=actual.count(), exact_local_projection_parity=True,
                      unique_events=len(grouped),cross_batch_duplicate_events=sum(len(batches)>1 for batches in batch_ids.values()),
                      query=query,independent_sql=independent)
        if args.previous:
            previous = load_history_snapshot(spark,args.previous)
            before = {row.event_id for row in spark.read.parquet(previous['snapshot_path']+'/event_lineage').select('event_id').collect()}
            assert before.issubset(grouped), 'new snapshot lost prior input events'
            assert len(manifest['batches'])>len(previous['batches']), 'no late batch added'
            result.update(previous_unique_events=len(before), late_batch_union_verified=True)
        print('U3_VERIFIED='+json.dumps(result),flush=True)
    finally:
        spark.stop()


if __name__ == '__main__':
    main()
