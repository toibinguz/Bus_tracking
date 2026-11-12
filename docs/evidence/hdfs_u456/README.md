# U4–U6 evidence — 2026-11-12

## Source and publication

HF revision `f2e7378002113cb548e194f2e8bd11c97a1b94d9`, four paths in [source_window.json](source_window.json) were staged and received successfully through U2. U3 subsequently ran distributed Spark app `app-20261112134802-0017` (exit 0) over the received ledger: four bus batches and three incident batches including the three U3 batches from earlier.

Final Silver snapshot `fcd8fdaa7f7717b00cf4282f3f9d1a0b7c54981e46b4238b7ae392a89e9ba1f9`: 10,940 accepted bus rows, 361 incident observations. Consumer selection: routes `02`, `27`; dates 2026-10-27 and 2026-11-01. No observed history was imported from SQLite; canonical reference was exported read-only as in U3.

The domain builder ran existing baseline, incident projector and feature builder locally. The initial attempt `runtime/eta_u456_01/output` failed before publication with `ZeroDivisionError`: automatic Hive inference read numeric-only route codes as integers, losing the leading zero of `02`. Explicit string partition schemas fixed the consumer boundary; a regression now runs the actual baseline on a numeric-only route fixture. Failed output was retained. Completed build used `runtime/eta_u456_02/output`; cache was copied from the already verified first cache, without another HF/HDFS download.

## Actual U4 results

- 358 real projected pings selected: 166 train, 192 test.
- 19 train and 23 test trips; 54 training adjacent-segment samples.
- Baseline: 7,599 cells; tier 0:0, tier 1:0, tier 2:2,448, tier 3:5,151. Sparse data requires substantial fallback; this is not adequate evidence of city-wide ETA accuracy.
- Existing incident projector produced 14 fact records from 8 matched incidents on the two selected routes.
- Existing feature builder, with two spawned workers using explicit workspace paths: 180 train rows, 234 test rows, 60 columns (metadata/target included).
- [Consumer verification](consumer_verification.json): actual offline repeat, exact SQLite domain-table/Parquet parity, split checks, global model loaded and 16 finite prediction smoke rows. No retraining or serving promotion.

## Actual U5 results

Final artifact `4ee4031b0330c244267f0a249eaa8b49f3151bd664c277945c1179045e500e8a` was published and verified under HDFS `gold/eta_artifacts/<id>` with publication `_published/eta_artifacts/<id>.json`. [artifact_manifest.json](artifact_manifest.json) is the actual completed build manifest with all file hashes, selection, code and policy fields. Final workspace is `runtime/eta_u456_03/output`; it was rebuilt after adding an explicit existing-release identity check. The earlier valid release is retained; domain values were unchanged.

Private-network `eta-artifacts` service downloaded it into `runtime/eta_releases/<id>`. `runtime/eta_active.json` was activated only after verification. Existing operational SQLite/model/config/serving changes were not overwritten. The first release was activated at `2026-11-12T13:53:31.339389+00:00`; final hardened release at `2026-11-12T14:05:47.761237+00:00`. Final consumer and offline verification JSON files refer to that final release.

[Offline verification](offline_verification.json): `verify_eta_offline_release.py` exited 0. It blocked subprocess/HDFS calls, looked up a genuine observed-history baseline row (02, go, stations7→8, p50=92.9s), rejected an intentionally corrupted copy before pointer activation, and confirmed an injected unavailable-HDFS refresh did not change the active pointer. Docker itself was left running for other services. Unit tests additionally cover actual file hash mismatch during download, mixed/unlisted files and idempotent publish.

## Actual U6 replay

Final-code replay on `runtime/eta_u456_03` also exited 0, from the same pinned HF source window through verify/upload/Silver/publication/download/activation. All four input batches reported already received; the same final snapshot and artifact were retained. Activation time: `2026-11-12T14:09:07.219785+00:00`. Exact final result: [workflow_replay.json](workflow_replay.json). The initial successful replay below is retained as execution history, not the current artifact identifier.

```powershell
.\.venv\Scripts\python.exe scripts/run_hdfs_eta_workflow.py --source-window docs/evidence/hdfs_u456/source_window.json --workspace runtime/eta_u456_02 --dates 2026-10-27 2026-11-01 --routes 02 27 --pointer runtime/eta_active.json
```

Exit 0. All four HF paths were staged, all four receives reported `already_received=true`; source processing returned the same Silver snapshot ID; publish/download returned the same artifact ID; verified activation at `2026-11-12T14:01:01.171226+00:00`. This replay intentionally reused completed cache/output/release; original materialize/build/publish/download had already run earlier in the same turn. It does not claim a fresh empty cluster was rebuilt on replay.

Raw identifying result of the initial replay:

```json
{"artifact_id":"c5e2be5879848b1196228b88f1a274adc4fe777bb575a892c610b0b31f735822","snapshot_id":"fcd8fdaa7f7717b00cf4282f3f9d1a0b7c54981e46b4238b7ae392a89e9ba1f9","activated_at":"2026-11-12T14:01:01.171226+00:00","feature_result":{"elapsed_sec":2.7,"n_columns":60,"test_rows":234,"train_rows":180}}
```

All commands, prerequisites and limits: [runbook](../../HDFS_U456_RUNBOOK.md). No full-model retraining, full HF import, live-serving cutover or production availability claim.

## Final regression

With `HDFS_P3A_LIVE=1`, all HDFS/HF/history/cache/release tests, including real HTTP contract tests, completed: **69 passed in 9.97s**. No skipped tests in this final run. Regression includes the actual baseline leading-zero route case and rejection of an existing valid release stored under a different requested artifact ID.
