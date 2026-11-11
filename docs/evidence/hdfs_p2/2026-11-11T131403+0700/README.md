# P2 raw Spark/HDFS run evidence

This evidence set re-runs the bounded SPEC-35 fixture with a new Bronze HDFS
path and hence a new job key. It exists because the earlier accepted-source
run did not retain the original raw Spark transform log.

## Identity

- Bronze fixture: `hdfs://namenode:8020/bus-eta/v1/bronze/telemetry/dt=2026-10-08/hr=13/ingest-p2-audit-20261111.jsonl`
- Job key: `76c7dbed2a7c0b177443afe10ba71cc4a6032e16b09cf659b3b893c2238e8918`
- Silver output: `hdfs://namenode:8020/bus-eta/v1/silver/route_projected_telemetry/provenance=replayed_observed/dt=2026-10-08/hr=13/_runs/job=76c7dbed2a7c0b177443afe10ba71cc4a6032e16b09cf659b3b893c2238e8918`
- Gold output: `hdfs://namenode:8020/bus-eta/v1/gold/route_speed_hourly/provenance=replayed_observed/dt=2026-10-08/_runs/job=76c7dbed2a7c0b177443afe10ba71cc4a6032e16b09cf659b3b893c2238e8918`

## Evidence map

| Requirement | Raw evidence |
| --- | --- |
| Fixture staged in HDFS and RF=2 | `01_stage_fixture_cp.txt`, `02_bronze_ls.txt`, `03_bronze_checksum.txt`, `04_bronze_fsck.txt` |
| Spark reads Bronze and writes Silver/Gold | `05_spark_submit_transform.log`, `05_spark_submit_transform.exit.txt` |
| Re-run is checkpoint no-op | `06_spark_submit_noop.log`, `06_spark_submit_noop.exit.txt` |
| Checkpoint/publish content and hash | `07_checkpoint.json`, `08_publish.json`, `09_checkpoint_publish_checksum.txt` |
| Silver schema, row/dedup diagnostics, Gold readback | `10_spark_readback.py`, `10_spark_readback.log`, `10_spark_readback.exit.txt` |
| Per-file HDFS replication/checksum and two live DataNodes | `14_{bronze,silver,gold,checkpoint,publish}_{ls,fsck}.txt`, `11_silver_gold_file_checksums.txt`, `12_dfsadmin_report.txt` |
| Independent `spark-sql` aggregate agreement | `13_spark_sql_gold_validation.sql`, `13_spark_sql_gold_validation.log`, `13_spark_sql_gold_validation.exit.txt` |

The current transform log records five raw Bronze rows, one duplicate identity,
four accepted Silver rows, and Gold `08A` aggregate `ping_count=4`,
`speed_sample_count=3`, `avg_speed_kmh=16.53`.

`10_spark_sql_schema_readback_validation.*` is retained as a failed diagnostic
attempt: `DESCRIBE parquet.<path>` is not accepted by this Spark SQL client.
It is not used for validation. The independent successful query is file `13`;
schema/readback uses the separate Spark audit program in file `10`.
