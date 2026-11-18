# P3A independent HTTP checks

This report covers external HTTP behavior only. The tester read SPEC-25 and
SPEC-41 and did not read the API or validator implementation. It does not
replace the Spark/HDFS lineage, Gold leakage, dependency-outage or independent
aggregation evidence required by SPEC-41.

Command (PowerShell, with the Docker history service running):

```powershell
$env:HDFS_P3A_LIVE='1'
.\.venv\Scripts\python.exe -m pytest tests/test_hdfs_p3a_blackbox.py -q -p no:cacheprovider
```

Initial observed result:

```text
...........                                                              [100%]
11 passed in 4.52s
```

The checks cover eight rejected requests (missing parameter, duplicate route,
SQL-like route text, reversed dates, 32-day inclusive range, invalid calendar
date, empty route and unexpected parameter), the published 08A fixture for
2026-10-08 (four pings, average speed 16.53 km/h), an absent route returning
empty rows and an unknown endpoint returning HTTP 404. The fixture expected
values were supplied as the established integration fixture contract; an
independent Spark aggregation must separately establish those values.

Without `HDFS_P3A_LIVE=1`, the live-service checks deliberately skip:

```text
sssssssssss                                                              [100%]
11 skipped in 0.09s
```

Final external verification passed after the implementation stabilized; the
failed intermediate runs below are retained for traceability.

Dependency test attempt against the refreshed API:

```text
python tests/hdfs_p3a_dependency_checks.py
AssertionError: (503, {'error': 'hdfs_unavailable'}, 20.1)
```

This failure occurred at the healthy baseline request, before creating any
test checkpoint or stopping the NameNode. The deadline is observable, but a
healthy baseline must succeed before the outage test can establish recovery.

Independent Spark SQL oracle (no application imports), exit code 0:

```text
docker compose -f docker-compose.hdfs.yml exec -T spark-master /opt/spark/bin/spark-submit --master local[1] /workspace/tests/hdfs_p3a_independent_spark.py hdfs://namenode:8020/bus-eta/v1/silver/route_projected_telemetry/provenance=replayed_observed/dt=2026-10-08/hr=13/_runs/job=60ed5c1457557a6adea9f959437348efd9232cd49e806e87f72aadf8a42d42e2
P3A_INDEPENDENT_SPARK={"avg_speed_kmh": 16.53, "ping_count": 4}
```

The oracle runs Spark in `local[1]` within the Spark container to avoid competing
for the API executors. Its source is HDFS Parquet; it does not demonstrate
multi-executor processing, which requires separate distributed-run evidence.

After an API restart with 512 MiB executors, while a validator job ran, an
external rerun reported:

```text
FAILED tests/test_hdfs_p3a_blackbox.py::test_published_fixture_aggregate
FAILED tests/test_hdfs_p3a_blackbox.py::test_missing_route_has_empty_rows
2 failed, 9 passed in 41.18s
```

Both failures were HTTP 503 `hdfs_unavailable` on healthy-data queries. This
result is retained as a failed run; it must be resolved before final acceptance.

The coder corrected Spark driver address advertisement on the API container's
two networks. Independent final HTTP rerun:

```text
...........                                                              [100%]
11 passed in 2.87s
```

Independent dependency integration, exit code 0:

```text
python tests/hdfs_p3a_dependency_checks.py
namespace: blackbox-05c0647bc2004a17b1ff0ea46e7c478a
baseline: HTTP 200, 2.185 s, ping_count=4, avg_speed_kmh=16.53
unpublished_checkpoint_invisible: HTTP 200, 1.561 s, same rows
duplicate_published_window_rejected: HTTP 503 hdfs_unavailable, 1.110 s
actual_namenode_outage: HTTP 503 hdfs_unavailable, 0.185 s
restored: HTTP 200, 1.736 s, ping_count=4, avg_speed_kmh=16.53
```

The test stopped the real NameNode service and restarted it in `finally`.
It removed only its uniquely named publication and checkpoint paths. The
unpublished-checkpoint probe references existing Silver data; it establishes
publication gating and does not claim a separate physical-copy experiment.
Raw timestamped payloads are also retained in
`runtime/hdfs_p3a_blackbox/dependency_results.json` (ignored local runtime).

Independent HTTP/Spark/dependency result: **PASS**. This is scoped evidence;
Gold train/test correctness and observed-trip MAE remain the validator and
white-box review responsibilities.
