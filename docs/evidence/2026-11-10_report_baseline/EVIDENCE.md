# Report evidence baseline — 2026-11-10

This file is a measurement ledger, not an interpretation of the proposal or
README.  All commands below ran in the checked-out workspace on 2026-11-10
(Asia/Ho_Chi_Minh).  A future report must cite this file or re-run its commands
against the stated snapshot.

## Snapshot identity

| Item | Value | Command / unit |
| --- | ---: | --- |
| Git revision | `cee5324f3cda08dcbe46ed35a7bf4a78ff6c177d` | `git rev-parse HEAD` |
| SQLite artifact | `data/hanoi_bus_system.db` | filesystem artifact |
| SQLite size | 3,081,240,576 bytes | `Get-Item data/hanoi_bus_system.db` |
| Silver lakehouse files | 1,361 | `Get-ChildItem data/lakehouse -Recurse -File \| Measure-Object Length -Sum` |
| Silver lakehouse bytes | 1,719,937,794 bytes | same command |
| Gold lakehouse files | 96 | `Get-ChildItem data/lakehouse/gold -Recurse -File \| Measure-Object Length -Sum` |
| Gold lakehouse bytes | 1,359,923,163 bytes | same command |
| Model-6 metadata artifact | `data/models/eta_xgb_metadata_and_calibrator_r3_big.json` | versioned file |
| Model-6 metadata SHA-256 | `2C49778CE1EAF79592B156EB0BF54D7C15E73B535094150932831575E649C35E` | `Get-FileHash ... -Algorithm SHA256` |
| Pruned global model SHA-256 | `E7992FB52DD4FA6917726F5171DB5517D2EB5FB9944D336CDD7E49138736E688` | `Get-FileHash data/models/eta_xgb_global_pruned_r3_big.json -Algorithm SHA256` |
| Full global model SHA-256 | `EB524DE9E2838880BC9D4CC4CE0BF8F8D77024665E36BBC70B99EBF0D3034EF2` | `Get-FileHash data/models/eta_xgb_global_full_54feat_r3_big.json -Algorithm SHA256` |

## SQLite inventory

Source: `data/hanoi_bus_system.db`; command: `sqlite3` `COUNT(*)` query over
the named tables.  Unit is rows.

| Table | Rows |
| --- | ---: |
| `canonical_route_master` | 176 |
| `canonical_shape_master` | 118,563 |
| `canonical_station_master` | 13,301 |
| `vehicle_unique_pings` | 7,333,298 |
| `route_projected_telemetry` | 5,565,232 |
| `fact_route_tomtom_incidents` | 836,761 |
| `agg_segment_travel_times` | 169,830 |

For `route_projected_telemetry`, the measured time range is
`2026-10-08T12:55:20+07:00` to `2026-11-07T13:53:37+07:00`, with 48 route codes
and 481 vehicle IDs.  Its `cross_track_m` mean is 7.263 m, maximum is 35.0 m,
and count above 35.0 m is zero.  These figures do **not** prove an ingestion
rejection rate: the precise denominator/rejection-reason ledger has not yet
been measured.

The measured projected rows for the two named routes are:

| Route code | Rows | First event | Last event |
| --- | ---: | --- | --- |
| `02` | 253,626 | `2026-10-08T12:55:20+07:00` | `2026-11-07T13:53:15+07:00` |
| `27` | 252,554 | `2026-10-08T12:55:27+07:00` | `2026-11-07T13:52:38+07:00` |

## Parquet purity audit

Command:

```powershell
.\.venv\Scripts\python.exe scripts\audit_silver_lakehouse_purity.py
```

Result: **pass**. The auditor scanned 1,191 Silver partition files and
5,565,232 rows in 20.21 s (275,313 rows/s).  Direction counts were 2,777,696
`go` (49.91%) and 2,787,536 `re` (50.09%); invalid directions and rows above
35.0 m were both zero.  This is a measured local Parquet result, not HDFS
evidence.

## Temporal split and model evaluation artifact

Split artifact: `data/splits/train_test_split_v1.json`.

* Train dates: 2026-10-08 through 2026-11-01, with the exact 22-date list in
  that JSON.
* Test dates: 2026-11-02 through 2026-11-07 (six dates).
* Corridor rule stored in the split: `cross_track_m <= 35.0`.

The metadata artifact reports 3,704,820 held-out test rows, 54 candidate
features, 53 retained Model-6 features, and 47 route entries in the per-route
audit.  Its Model-6 (`6_XGB_Pruned_53Feat`) aggregate metrics are:

| Test rows | MAE (s) | MedAE (s) | RMSE (s) | P90 AE (s) | MAPE (%) | R² | within 1/2/3 min (%) |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 3,704,820 | 96.70 | 46.69 | 170.89 | 244.58 | 13.25 | 0.9774 | 56.37 / 74.88 / 84.24 |

The same artifact contains only a **per-route evaluation** of the global model,
not route-specific model artifacts.  For Model 4 (full global XGBoost), its
stored route rows are:

| Route | Held-out N | Baseline MAE (s) | Global XGB MAE (s) | Calibrated MAE (s) |
| --- | ---: | ---: | ---: | ---: |
| `02` | 158,756 | 106.27 | 89.54 | 90.22 |
| `27` | 167,383 | 111.52 | 91.03 | 90.53 |

These two rows do **not** establish that routes 02 and 27 alone were trained
through Model 6.  Code evidence in
`module_3_bus_eta_prediction/step_3_3_machine_learning_models/eta_model_trainer.py`
loads all route partitions, trains `Model_4_XGB_Global_Full_54Feat` and
`Model_6_XGB_Pruned_*`, then streams evaluation by route.  Therefore the
current trainer is global, not route-scoped.

## Measured gaps / prohibited claims

| Required result | Status | Reason / next measurement |
| --- | --- | --- |
| Input → accepted → rejected counts by reason | N/A — not measured | Add a read-only ledger query/run from the canonical ingestion/projector artifacts. |
| Train/validation rows per route and missing-value rates | N/A — not measured | Count feature parquet partitions using the split artifact. |
| Route-specific Model-6 completion | N/A — unsupported by current trainer | First specify a route-scoped runner, or redefine completion as per-route evaluation of one frozen global model. |
| Runtime for long route completion | N/A — not measured | Record start/end UTC and resources only after the runner semantics are decided. |
| HDFS/Spark Silver/Gold/history query | N/A — not complete | Do not use local lakehouse audit as HDFS proof. |

## Safe next plan for the “run remaining routes” request

No long training was started.  The prerequisite decision is whether the project
needs (A) a new route-scoped Model-6 runner or (B) a fixed global Model-6 plus
per-route held-out evaluation.  The existing code implements B.  If B is
accepted, generate an atomic route-completion manifest by evaluating the frozen
global model per sorted route code and saving each route's input hash, row
counts, metrics, model hash, start/end UTC, exit status, and wall time.  If A
is required, write and approve a separate specification before implementation;
do not label the existing global artifacts as 48 per-route models.
