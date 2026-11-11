# P2 raw Spark/HDFS run evidence

This evidence set re-runs the bounded SPEC-35 fixture with a new Bronze HDFS
path and hence a new job key. It exists because the earlier accepted-source
run did not retain the original raw Spark transform log.

## Identity

- Bronze fixture: `hdfs://namenode:8020/bus-eta/v1/bronze/telemetry/dt=2026-10-08/hr=13/ingest-p2-stage-closed-20261111.jsonl`
- Job key: `2a86ec9d93685ebb66d71872847796156ba1c87475e140905e3294d7e38facb3`
- Silver output: `hdfs://namenode:8020/bus-eta/v1/silver/route_projected_telemetry/provenance=replayed_observed/dt=2026-10-08/hr=13/_runs/job=2a86ec9d93685ebb66d71872847796156ba1c87475e140905e3294d7e38facb3`
- Gold output: `hdfs://namenode:8020/bus-eta/v1/gold/route_speed_hourly/provenance=replayed_observed/dt=2026-10-08/_runs/job=2a86ec9d93685ebb66d71872847796156ba1c87475e140905e3294d7e38facb3`

## Evidence map

| Requirement | Raw evidence |
| --- | --- |
| Closed fixture, reference, and manifest staged in HDFS with RF=2 | `16_stage_closed_fixture_raw.txt` |
| Spark reads staged Bronze and writes Silver/Gold | `17_spark_submit_staged_transform.log` |
| Re-run is checkpoint no-op | `19_spark_submit_staged_noop_raw.log`, `19_spark_submit_staged_noop_raw.exit.txt` |
| Checkpoint/publish content, HDFS state, and hash | `20_staged_job_hdfs_state.txt` |
| Silver schema, row/dedup diagnostics, Gold readback | `21_spark_readback_staged.py`, `21_spark_readback_staged.log`, `21_spark_readback_staged.exit.txt` |
| Per-file HDFS replication/checksum for the staged job | `20_staged_job_hdfs_state.txt`, `23_staged_output_file_checksums.txt` |
| Independent `spark-sql` aggregate agreement | `22_staged_spark_sql_gold_validation.sql`, `22_staged_spark_sql_gold_validation.log`, `22_staged_spark_sql_gold_validation.exit.txt` |

The current transform log records five raw Bronze rows, one duplicate identity,
four accepted Silver rows, and Gold `08A` aggregate `ping_count=4`,
`speed_sample_count=3`, `avg_speed_kmh=16.53`.

`10_spark_sql_schema_readback_validation.*` is retained as a failed diagnostic
attempt: `DESCRIBE parquet.<path>` is not accepted by this Spark SQL client.
It is not used for validation. The independent successful query is file `13`;
schema/readback uses the separate Spark audit program in file `10`.
