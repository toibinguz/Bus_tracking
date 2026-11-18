# P3B verification

- Distributed Spark run: `app-20261112085232-0011`, 2026-11-12 08:52 UTC, exit 0. Exact command: `docs/HDFS_P3B_RUNBOOK.md`.
- `fsck.txt`: independently invoked HDFS fsck, exit 0, 5 blocks with replication 2, HEALTHY.
- `stored_sha256.txt`: independently streamed HDFS part file into `sha256sum`, exit 0, matches generator report.
- Focused regression command: `.\.venv\Scripts\python.exe -m pytest tests/test_hdfs_p3b_scale.py tests/test_hdfs_history_query.py tests/test_hdfs_p3_observations.py -q -p no:cacheprovider` — 12 passed in 0.98s.
- Historical API after experiment: GET `http://127.0.0.1:8090/api/history/route-speed?route_code=08A&date_from=2026-10-08&date_to=2026-10-08` at 2026-11-12T08:54:39.054164+00:00 returned 200, `ping_count=4`, `avg_speed_kmh=16.53`, `storage=hdfs-silver`. Experimental rows did not change the published history result.

No independent-agent audit was performed in P3B. Checks above directly validate the bounded mechanics criteria in SPEC-42; throughput, recovery capacity and large-history ETA accuracy are outside this experiment.
