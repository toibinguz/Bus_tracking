# Actual baseline consumer and offline operation

2026-11-12, Windows host Python venv; existing Docker HDFS P3A history.

1. Successful HDFS materialization and actual full baseline builder invocation, exit 0:

```powershell
.\.venv\Scripts\python.exe scripts/eta_history_baseline.py --source hdfs --hdfs-run hdfs://namenode:8020/bus-eta/v1/gold/p3a_observed_v3 --cache runtime/eta_hdfs_cache_01 --output runtime/eta_hdfs_baseline_01
```

2. Independent source comparison and offline rerun, exit 0:

```powershell
.\.venv\Scripts\python.exe scripts/verify_eta_history_integration.py runtime/eta_hdfs_cache_01 runtime/eta_hdfs_baseline_01 runtime/eta_offline_baseline_01 data/hanoi_bus_system.db
```

Raw final result:

```json
{"input_rows": 10268, "exact_input_parity": true, "baseline_cells": 3366, "exact_sqlite_gold_parity": true, "exact_parquet_gold_parity": true, "offline_external_calls": 0, "source_window_id": "observed-snapshot-e15c9a67ed42f71aa95d666c1accd22b13b1ed4acf8ea367e1f464b1edd52094"}
```

All selected input fields/multiset rows compared to read-only SQLite source. Offline execution patches subprocess.run to fail if invoked, so it verifies no Docker process regardless of whether Docker Desktop is running. Did not stop the user's Docker installation.

3. Focused tests: `python -m pytest tests/test_crawler_hdfs_spool.py tests/test_eta_history_baseline.py tests/test_hdfs_p3_observations.py tests/test_hdfs_history_query.py -q -p no:cacheprovider` — 15 passed in 3.17 seconds. Includes default local source dispatch without Docker, corruption/incomplete-cache rejection, and real crawler batch spool partitioning without network.

Only bounded two-day observed history is covered; no claim that operational full-history models or online serving were migrated. Existing user modifications in config/serving/web/experiments were not edited. Module-3 algorithm file was not changed. Local mode preserves the original builder behavior and therefore its operational writes; HDFS/cache modes write separate outputs.
