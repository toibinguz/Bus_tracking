# SPEC-31: Evidence-first report and model-completion plan

**Status:** planning specification; it creates no new implementation claim.  
**Rule:** a report claim is admissible only when the checked-out code, a versioned
data/model artifact, and a repeatable command or saved run log support it.  Earlier
proposals, READMEs, and design specs are not evidence by themselves.

## 1. Evidence protocol for the final report

Every number in the report must carry these five fields in its table caption or
adjacent text:

`artifact path | data/snapshot identifier | command or test | execution date | unit`.

The report must classify each result as one of:

| Label | Required evidence | Permitted wording |
| --- | --- | --- |
| **Measured** | immutable artifact plus rerunnable command/log | “Measured …” |
| **Verified implementation** | code path plus passing test/audit log | “The repository implements and the test verifies …” |
| **Integrated demo** | timestamped end-to-end command/log | “Demonstrated in this environment …” |
| **Planned** | design only | “Planned”; never “supports”, “achieves”, or “is deployed” |

No percentage, row count, latency, coverage, model result, or availability claim
may be copied from a README. Recompute it from the listed source artifact, or
write `not measured in this revision`.

## 2. Claim-to-evidence ledger

| Report subject | Code/artifact source of truth | Required measured outputs | Current safe status |
| --- | --- | --- | --- |
| Canonical routes/stations/shapes | `data/hanoi_bus_system.db`; canonical ingestion and `db_manager.py` | table counts; snapshot hash; date range | must query DB in report build |
| Raw/clean/projected telemetry | SQLite tables; `bulk_ping_ingester.py`, `telemetry_sanitizer.py`, `multi_route_projector.py` | raw→accepted→rejected counts, rejection reasons, `cross_track_m` distribution, routes/dates | must recompute |
| Parquet lakehouse | `data/lakehouse/`; `lakehouse_exporter.py`, `silver_lakehouse_auditor.py` | path/file/byte/row counts; partition coverage; auditor result | must rerun auditor |
| Temporal split | `data/splits/train_test_split_v1.json` | exact train/test dates and counts read from each feature parquet | versioned split exists; counts must be recomputed |
| ETA models 0–6 | `eta_model_trainer.py`, model JSON and `eta_xgb_metadata_and_calibrator*.json` | model tag/hash; feature count; MAE, RMSE, MedAE, P90, MAPE, R2, <=1/2/3-min accuracy by horizon; per-route table | artifact `*_r3_big.json` contains 3,704,820 test rows; it is evidence only after its artifact hash is recorded |
| ETA serving/demo | `step_3_4_*`, `step_3_5_web_demo`; request/response log | exact endpoint, timestamp, selected route, response fields/latency | do not infer from source alone |
| HDFS baseline | HDFS_DEMO_RUNBOOK.md, HDFS_P1_RECOVERY_ADDENDUM.md and docs/evidence/hdfs_p1; Compose and command logs | 2 DataNodes, RF=2, `fsck`, single-DataNode read, WebHDFS Bronze receipt/hash | demonstrated; retain raw logs before report claim |
| HDFS/Spark historical path | HDFS specs 25–30 and actual job/API logs | Spark input URI, Silver/Gold output counts, independent aggregate parity, failure/retry logs | **not complete**; report only as planned/in progress |

## 3. Mandatory numeric tables and the allowed null value

The report must contain these tables. A missing measurement is shown as `N/A —
not measured`, with a reason and the command that will produce it; it is never
replaced with a qualitative adjective.

1. **Data inventory:** DB bytes, file bytes, rows, route count, date range, and
   partition count at the named snapshot.
2. **Data-quality flow:** input/accepted/rejected rows and rejection rate for
   each ingestion/projection stage; include cross-track threshold and observed
   max/quantiles.
3. **Feature/train/test inventory:** rows and routes per split, date boundary,
   missing-value rates for every model input or a documented aggregate rule.
4. **ETA accuracy:** models 0–6 × horizon buckets (`1_hop`, `2_to_5`,
   `6_to_15`, `gt_15`, `ALL`) with all metrics emitted by `StreamingEvaluator`.
5. **Per-route ETA:** at least every completed route; show `N`, baseline MAE,
   model-6 MAE, signed/percentage change. Never average route MAEs without
   stating whether the aggregation is macro or sample-weighted.
6. **Storage evidence:** local SQLite/Parquet inventory separately from HDFS;
   HDFS table includes only commands that were run.
7. **Runtime:** each long job's start/end UTC, wall time, host CPU/RAM,
   input rows, output rows, exit code, and artifact hash.

## 4. Reproducible measurement collection

Before prose is drafted, run these commands and save stdout/stderr unchanged to
`docs/evidence/<UTC-run-id>/` (the directory is a report input, not a claim).

```powershell
# Environment, revision, artifacts
git rev-parse HEAD
Get-FileHash data\models\eta_xgb_metadata_and_calibrator_r3_big.json
Get-ChildItem data\lakehouse -Recurse -File | Measure-Object Length -Sum

# SQLite schema and counts (execute through the project's configured Python/SQLite runtime)
# Export: table name, COUNT(*), MIN/MAX event time where present, and DB pragma page_count/page_size.

# Lakehouse integrity
.\.venv\Scripts\python.exe scripts\audit_silver_lakehouse_purity.py

# Model evaluation: retain the complete stdout and generated metadata JSON.
.\.venv\Scripts\python.exe module_3_bus_eta_prediction\step_3_3_machine_learning_models\eta_model_trainer.py

# HDFS claims only after cluster start; retain each raw output.
docker compose -f docker-compose.hdfs.yml ps
docker compose -f docker-compose.hdfs.yml exec namenode hdfs dfsadmin -report
docker compose -f docker-compose.hdfs.yml exec namenode hdfs fsck /bus-eta -files -blocks -locations
```

The trainer currently defines a temporal split and emits the full metric ledger;
the report generator must cite the generated metadata, rather than hard-code
numbers in Markdown. Running the trainer may overwrite untagged model files;
therefore set a unique `ETA_MODEL_TAG` and record it before every report run.

## 5. Correct handling of the current “02 and 27 through model 6” assertion

This statement is a **work-state claim**, not a network-wide accuracy claim. It
must be checked against a manifest created by the completion process. Until that
manifest exists, word it as: “At the time of this report, only routes reported
by the completion manifest are considered model-6-complete.” Do not list `02`
or `27` as complete merely because a model file exists.

The completion manifest is one JSONL record per route, written atomically after
that route's held-out evaluation succeeds. Required fields:

```text
run_id, git_commit, route_code, model_tag, source_feature_hash,
train_rows, validation_rows, test_rows, split_id, started_at_utc,
finished_at_utc, wall_seconds, exit_code, metrics, model_sha256, status
```

`status=complete` requires: correct temporal split, model-6 artifact hash,
non-empty held-out rows, saved metric payload, and exit code 0. `failed` and
`skipped` records are retained; absence is not success.

## 6. Resumable route-completion plan

This plan deliberately does not predict a duration. It measures the duration of
the first two completed routes and then reports observed median/p90 wall time.

1. **Freeze inputs:** record git commit, Python/package versions, feature-store
   paths and SHA-256/row counts; reject a run if these differ from the active
   manifest.
2. **Preflight each route:** verify train/validation/test parquet exists and
   count rows. Record a `skipped` or `failed` manifest line rather than silently
   dropping a route.
3. **Run one route at a time:** use a deterministic route list sorted by route
   code, fixed seed, unique model tag/run ID, and separate output directory.
   Each route is an atomic unit; no parallel route process shares model paths.
4. **Checkpoint:** write the manifest only after model, metric JSON, and hashes
   are durable. On restart, select the first route without `status=complete`
   whose input hash equals the current preflight result.
5. **Validate immediately:** independently load the saved metric JSON; check
   row count and model hash, then append completion. Route 02 and 27 must be
   revalidated with this same rule before being counted.
6. **Publish:** create the per-route table only from `status=complete` manifest
   records. Report completion coverage as `complete_routes / eligible_routes`.

Implementation must first establish whether the existing trainer trains one
global model or supports route-scoped artifacts. If it is global-only, do not
pretend it is a per-route training plan: add a separately specified route-scoped
runner, or define “completed route” as successful per-route evaluation of the
fixed global model. This decision is mandatory before a long run begins.

## 7. Report language guardrails

- Say “held-out temporal test set” only if dates and rows are printed from the
  saved split/feature artifact.
- Say “HDFS fault experiment with one DataNode loss” rather than “high
  availability” or “production fault tolerance.”
- Say “Model-6 completed for *k/n eligible routes*” only from the manifest.
- Do not claim real-time, citywide coverage, 24/7 availability, scalability, or
  an HDFS-backed historical API until its corresponding raw evidence exists.
- Screenshots illustrate a result; they do not substitute for a command, data
  artifact, or metric table.

## 8. Acceptance for the report-writing phase

The numerical report is ready only when every table cell links to its evidence
run, all model values identify a model artifact hash and split, all claims are
labeled by §1, and the route-completion manifest is included as an appendix.
