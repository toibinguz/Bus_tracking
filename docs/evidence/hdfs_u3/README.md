# U3 verification

2026-11-12; actual Docker HDFS and Spark 3.5.4.

| Run | Result |
| --- | --- |
| Full canonical reference export | Read-only SQLite; hash `7e1664bb57315eb23875421de7d3b7de7b9982e0fe6cfd6d04037729df24a2aa`; exact bytes verified on HDFS |
| Initial failpoint run `app-20261112094511-0012` | Exit 1 intentionally before publication. Completed but unpublished report retained in `unpublished_attempt.json`; API snapshot request returned 503 |
| Retry `app-20261112094704-0014` | Exit 0; snapshot `a2dc50ad61ac39d1ecfa92ad99ed37dee917eb7b85f996262c2c7dcce6226082`, 3,324 accepted bus rows |
| Receive late HF batch | U2 CLI exit 0; older `batch_160515.jsonl` received after initial snapshot; raw hash `b4c7da945be2d73614f122ce91caa0c09fd98cb92fe39c08fb9c93f7253307db` |
| Cumulative run `app-20261112095046-0015` | Exit 0; snapshot `f02a3bbf522eadf3bae1347ba63f0e50fcf54bf1c806e43dedb4c7e16223b57f` |
| Repeat `app-20261112095212-0016` | Exit 0; same final snapshot, `noop=true` |
| Separate verification script | Exit 0; all projected columns match local canonical boundary result, prior unique event IDs retained, query matches independent Spark SQL |

Raw final HDFS publication: [published_snapshot.json](published_snapshot.json). Actual host HTTP payload: [http_snapshot_query.json](http_snapshot_query.json). Exact commands and limits: [runbook](../../HDFS_RUNBOOK.md).

## Verification script final output

```json
{"snapshot_id":"f02a3bbf522eadf3bae1347ba63f0e50fcf54bf1c806e43dedb4c7e16223b57f","accepted_bus_rows":6596,"exact_local_projection_parity":true,"unique_events":8103,"cross_batch_duplicate_events":193,"query":{"route_code":"08A","date_from":"2026-11-12","date_to":"2026-11-12","rows":[{"dt":"2026-11-12","ping_count":140,"speed_sample_count":127,"avg_speed_kmh":14.127165354330712}],"storage":"hdfs-silver","provenance":"observed","snapshot_id":"f02a3bbf522eadf3bae1347ba63f0e50fcf54bf1c806e43dedb4c7e16223b57f"},"independent_sql":[{"dt":"2026-11-12","ping_count":140,"speed_sample_count":127,"avg_speed_kmh":14.127165354330712}],"previous_unique_events":4145,"late_batch_union_verified":true}
```

Bus counts reconcile: 10,220 input observations = 1,907 duplicate observations + 1,717 rejected rows/events + 6,596 accepted unique projected rows. Valid normalized unique event count is 8,103; raw unknown-route rows are rejected before that denominator. 193 distinct event IDs occur in both batch files; this is a different metric from total 1,907 duplicate observations (which also includes within-batch repeated polls). Incidents: 192 unique observations, 0 rejected.

Initial and cumulative scripts have different source hashes because input-validation/incident hardening was added between runs. The report records both; the whole-output count change is not presented as a controlled same-code A/B benchmark. Final verification directly checks the union of both source batches and no loss of the initial event lineage. Same-input repeat/noop was tested with the final code.

Legacy HTTP query without snapshot_id still returned 4 ping /16.53 km/h for 08A 2026-10-08. Snapshot API returned 200 with values shown above. Existing model/serving data were not promoted or overwritten.

## Focused regression

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_history_snapshot.py tests/test_hf_bronze.py tests/test_hf_storage_inspection.py tests/test_hdfs_contract.py tests/test_hdfs_p2_transform.py tests/test_hdfs_history_query.py -q -p no:cacheprovider
```

39 passed in 2.25s. Covers event identity/capture choice/order, unknown route/invalid timestamp, ambiguous station directions, incident observations/null/version identity, explicit snapshot-ID HTTP validation/routing and previous HDFS contract tests. This is scoped direct verification, not an independent-agent audit or a city-scale test.
