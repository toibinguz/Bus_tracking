# P3A execution evidence

`observed_validation.json` is retrieved directly from HDFS validation_report after successful distributed Spark execution. Inputs: route08A, training2026-10-27, holdout2026-11-01. See docs/HDFS_P3A_RUNBOOK.md for exact invocation and interpretation limits. Earlier unsuccessful runs remain in HDFS under p3a_observed_v1/v2; only v3 is the final validation.

Raw output source: `hdfs://namenode:8020/bus-eta/v1/gold/p3a_observed_v3/validation_report/part-*`.
Gold output: `hdfs://namenode:8020/bus-eta/v1/gold/p3a_observed_v3/gold_segment_statistics`.
Runbook's final `spark-submit` invocation is the exact successful command (exit 0, 2026-11-12 08:41 UTC). Driver application ID `app-20261112084047-0009`; two remote executors, one on each worker, 512 MiB/core each. The API process existed concurrently with the validation job, but no successful simultaneous HTTP query is claimed. Subsequent healthy API check returned 200 after the batch completed and the driver address for the two-network API container was corrected.

The imported Silver snapshot is physically co-located under the isolated validation run's Gold namespace (`p3a_observed_v3/silver_snapshot`), to retain run-specific input/output lineage. It is not a newly published P2 Silver run and is not automatically served by the API.
