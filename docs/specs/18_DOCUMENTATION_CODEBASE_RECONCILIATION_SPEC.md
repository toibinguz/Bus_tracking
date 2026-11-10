# SPEC-18: Documentation–Codebase Reconciliation

**Status:** READY FOR GOVERNANCE EXECUTION  
**Author:** `@architect`  
**Audit date:** 2026-11-10  
**Scope:** repository documentation and current working-tree code. This is an
audit specification, not permission to edit or delete the documents named below.

## 1. Evidence baseline

1. The active web module declares `/api/health` and returns `status: "ok"`
   (`module_3_bus_eta_prediction/step_3_5_web_demo/app.py:64-73`). The launcher
   probes `/api/v1/health` and requires `status == "healthy"`
   (`run_demo.ps1:38-39`).
2. `app.py` imports the legacy monolithic `busmap_service.py` (`app.py:16-25`).
   The new split files exist (`dto.py`, `data_access.py`, `live_feed.py`,
   `frenet.py`, `online_features.py`, `model_runtime.py`, `eta_policy.py`, and
   `serving_service.py`), but are not the app's wired public facade.
3. `tests/` is empty. Therefore no document may truthfully claim a current
   passing black-box suite, regardless of historic logs.
4. `module_2/.../step_2_3_columnar_query_engine/` has only `__init__.py`; no
   HDFS query service or HDFS operational scripts exist.
5. Commit `f49e21c12881689b324a9ad383c4a19e1b7b9ae2` deliberately purged
   TimBus code, legacy serving names, and test scripts. It is required evidence
   for interpreting, and potentially removing, historical TimBus documentation.

## 2. Classification rules

- **KEEP**: preserve as-is; only index/status metadata may change elsewhere.
- **UPDATE**: preserve the document but correct its current-state statements,
  missing-file links, and status. Historical measurements must be explicitly
  dated, not silently presented as runtime guarantees.
- **DELETE (candidate)**: remove only after the Git-history proof in §4. A
  replacement must be linked before deletion.

## 3. Per-document disposition

| Document | Decision | Required normalized state / evidence |
| --- | --- | --- |
| `README.md` | UPDATE | Describe 3.4/3.5 as integration in progress, not complete. Remove unsupported claims of raw socket telemetry, a working 15 s cache, current 18.23 ms inference, 47 features, and passing tests. Make the docs index include the canonical specs through 18 and state that exact data counts are snapshots. |
| `docs/README.md` | UPDATE | Convert absolute local links to repository-relative Markdown links; enumerate all current specs 04–18; mark 11–14 historical and 16 implementation-in-progress. |
| `docs/01_MASTER_WORK_BREAKDOWN_STRUCTURE_ROADMAP.md` | UPDATE | Keep as WBS, but mark the HDFS phase deferred because its code is absent; revise Phase 7 to the app/service wiring and test gap in §1. |
| `docs/02_CANONICAL_DATA_DIRECTORY_SPECIFICATION.md` | UPDATE | Keep the target data contract, but label ignored raw/lakehouse paths as runtime-managed and distinguish them from tracked `data/ground_truth`, `data/metadata`, and `data/models`. |
| `docs/03_SILVER_TRAJECTORY_CONTINUITY_AND_ETA_CHECKLIST.md` | KEEP | It is an upstream quality checklist and names no removed runtime interface. Do not recast it as proof that current serving has passed tests. |
| `docs/04_TECHNICAL_DEBT_AND_OPEN_ISSUES_LEDGER.md` | UPDATE | Replace all current-tense claims that point to absent `tests/*` or deleted `scripts/test_*`; reopen or mark verification pending. TD-26/30/42/62/63 must not claim the new split service is live while `app.py` imports `busmap_service.py`. |
| `docs/05_ONLINE_FEATURE_EXTRACTOR_AND_SERVING_SPEC.md` | UPDATE | Mark as superseded design history and map deleted `online_feature_extractor.py`/`eta_serving_service.py` to `online_features.py`/`serving_service.py`; make SPEC-16 the implementation authority. |
| Retired TimBus parity bridge report | DELETE (approved) | Its raw-result link and executable link are absent: `data/metadata/timbus_busmap_parity_results.json` and the retired TimBus experiment. It contradicts the BusMap-only direction in SPEC-04; deletion proof is recorded from commit `f49e21c`. |
| `docs/07_SESSION_HANDOVER_PHASE_7_WEB_DEMO_AND_HARDWARE_GPS_AUDIT.md` | UPDATE | Preserve as dated handover evidence, but replace “completed” assertions with an explicit 2026-11-10 reconciliation note; remove links to absent test files and old service filenames. |
| `docs/08_GROUND_TRUTH_TEST_SPEC_AND_ANTI_PATCHING_STANDARD.md` | UPDATE | Keep its oracle principles; supersede its prescribed deleted `scripts/test_ground_truth_and_night_mode.py` and obsolete `/api/v1/routes/{route_code}/live-eta` contract with current test requirements under `tests/`. |
| Retired TimBus serving/tweening specification | DELETE (approved) | It mandated TimBus, 60 FPS tweening, and deleted serving interfaces, all prohibited or absent under SPEC-04 and commit `f49e21c`; deletion proof is recorded from that commit. |
| `docs/specs/04_BUSMAP_ONLY_DISCRETE_TRACKING_SPEC.md` | UPDATE | Retain as the frontend telemetry authority. Clarify that its ban on animation is browser-only; server-side physics in SPEC-15 must not imply frontend tweening. Point implementation references to the eventual facade rather than asserting the monolith is final. |
| `docs/specs/05_ROUTE_SHAPE_AND_STATION_INTERACTIONS_SPEC.md` | UPDATE | Preserve endpoint contract. Replace historic PASS assertions with pending verification and state which facade (`busmap_service.py` until the migration is wired) owns the routes. |
| `docs/specs/06_CLEANUP_SCRIPTS_AND_EXPERIMENTS_AUDIT.md` | UPDATE | Mark completed for the actual script/experiment migration; remove its expected moved test files because no such files now exist in `tests/`. Retain the cleanup decision record. |
| `docs/specs/07_TECHNICAL_DEBT_LEDGER_PARITY_AUDIT.md` | UPDATE | Keep as a reconciliation audit but label historical references and link its successor ledger. Do not describe deleted tests or TimBus artefacts as current. |
| `docs/specs/08_STATION_ETA_MAP_INTEGRATION_SPEC.md` | UPDATE | Preserve the station-ETA product contract; identify the current endpoint at `app.py:165` and replace references to an absent black-box test with a pending test deliverable. |
| `docs/specs/09_REALTIME_FEATURE_EXTRACTION_AND_COLD_START_SPEC.md` | UPDATE | Preserve its feature contract; map old class/file assumptions to the present split modules and defer “implemented” status until the app imports the split facade and tests exist. |
| `docs/specs/10_DISTRIBUTED_HDFS_LAMBDA_STORAGE_AND_QUERY_SPEC.md` | UPDATE | Mark explicitly **deferred / proposed**. Its named `hdfs_query_service.py`, `demo_hdfs_ingestion_stream.py`, `run_hdfs_analytical_query.py`, and test do not exist. It must not be presented as an implemented module. |
| `docs/specs/11_CONSERVATIVE_ASYMMETRIC_ETA_AND_UI_HYSTERESIS_SPEC.md` | UPDATE | Preserve as a superseded design input; add a precedence notice: SPEC-15/16 define the active policy, and no absent test can be cited as current evidence. |
| `docs/specs/12_INDEPENDENT_CODE_AND_MATH_DEFECT_AUDIT.md` | UPDATE | Preserve forensic findings, but add a dated historical banner and replace implementation directives with links to SPEC-15/16. Its tested-code claims cannot certify the current split modules. |
| `docs/specs/13_INDEPENDENT_RUNTIME_TELEMETRY_AUDIT.md` | UPDATE | Preserve measured observations as historical. Remove any implication that deleted `eta_inference_engine.py`, `online_feature_extractor.py`, or `eta_serving_service.py` is current. |
| `docs/specs/14_PEER_REVIEW_CODER_MINDSET_AND_INVARIANTS_AUDIT.md` | UPDATE | Preserve the audit, but remove “PASS” as a current claim because `tests/test_peer_review_invariants.py` is absent; route its unresolved requirements to a new blind test suite. |
| `docs/specs/15_PHYSICAL_KINEMATICS_AND_SERVING_SPEC.md` | UPDATE | Keep as the current mathematical authority. State its precedence over 11–14 and its strict coexistence rule with SPEC-04: server-side projection is allowed; TimBus and browser interpolation remain prohibited. |
| `docs/specs/16_REFACTOR_SPEC_STEP_3_4_SERVING_AND_3_5_WEB_DEMO.md` | UPDATE | Change status to **partially implemented / verification pending**. Its split files exist, but the public app still imports the monolith; W-01 fails by interface inspection; planned tests are absent. |
| `docs/specs/17_REPOSITORY_DIRECTORY_RECONCILIATION_SPEC.md` | KEEP | It accurately records the present directory and verification gap. Update it only after a later test-delivery task changes those facts. |
| `data/ground_truth/README.md` | UPDATE | Keep schema as canonical input documentation, but label the numerical counts as snapshot data and point to the ingestion script as schema authority. |
| `module_1_data_ingestion_and_preprocessing/README.md` | UPDATE | Retain module topology; enumerate the actual crawler support modules or shorten to public entry points. Mark counts and operational commands as snapshot-dependent. |
| `module_2_big_data_storage_and_lakehouse/README.md` | UPDATE | Correct the statement that step 2.3 is a PyArrow/DuckDB engine; only its package marker exists. Mark all lakehouse row counts as a dated dataset snapshot. |
| `module_3_bus_eta_prediction/README.md` | UPDATE | Replace “implemented Phase 3–7” with accurate status: offline pieces/artifacts exist; split serving modules are present but not wired by the app; no current tests are stored. Correct the model feature count to the canonical 54-feature full model where applicable. |
| `academic_proposal/big_data_bus_eta_proposal.tex` and `.pdf` | KEEP | Preserve as an academic proposal and generated artifact, not an operational runbook. Add no live-code claims; a future revision may add a “proposal snapshot” note in the TeX source and regenerate the PDF. |
| `academic_proposal/big_data_bus_eta_slides.tex` and `.pdf` | KEEP | Preserve as presentation material and generated artifact. It may describe the Lambda/HDFS target, but must be labelled proposed unless the HDFS code is delivered. |

## 4. Historical deletion proof

The two retired TimBus documents were removed after the following evidence was
recorded for their exact paths in the execution log:

```powershell
git log --follow --format=fuller -- <retired-parity-report>
git log --follow --format=fuller -- <retired-serving-tweening-spec>
git show --stat f49e21c12881689b324a9ad383c4a19e1b7b9ae2
git grep -n -e "retired-parity-report" -e "retired-serving-tweening-spec"
```

The evidence established the original purpose, cleanup commit `f49e21c`,
removed implementation/data, and inbound-reference audit. The replacements are
[SPEC-04](04_BUSMAP_ONLY_DISCRETE_TRACKING_SPEC.md) and the historical cleanup
record [SPEC-06](06_CLEANUP_SCRIPTS_AND_EXPERIMENTS_AUDIT.md). Reproducible
research artefacts require a separately approved historical archive.

## 5. Acceptance criteria for the documentation change

1. Every UPDATE action changes only documentation and uses repository-relative
   links.
2. No document states an absent file or passing test as current fact.
3. The docs index distinguishes active authority, historical audit, proposed
   work, and implementation-in-progress.
4. The documented deletions have §4 evidence and review approval.
5. After the serving migration, a blind tester supplies tests before any
   document is changed from “verification pending” to “implemented”.
