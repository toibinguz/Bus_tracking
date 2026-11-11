# SPEC-25: HDFS storage and historical-query vertical slice

**Status:** proposed; no implementation is implied by this document.  
**Date:** 2026-11-10  
**Owner:** `@architect`  
**Scope:** the Module-1 crawler-to-Module-2 history boundary and an offline
Module-3 ETA validation input. The web demo remains frozen. This is a
reproducible academic simulation, not a production deployment claim. It is the
cross-module contract to which the narrow interface changes in section 12 must
conform.

## 1. Decision

The project should demonstrate a small but real distributed-storage vertical
slice, rather than attempt the full Kafka + Hive + Spark Streaming + Lambda
architecture described in the academic proposal. The recommended first release
is:

```text
BusMap crawler -> durable local spool -> WebHDFS -> HDFS Bronze JSONL
                                         -> scheduled Spark SQL job -> HDFS Silver Parquet
REST client -> existing live/ETA service (latest state)        |
REST client -> bounded historical-query API -> Spark SQL ------+
```

HDFS is the durable source for *historical* telemetry. It is not a low-latency
database and must not be placed directly behind the live-vehicle or ETA
endpoints. The present service may keep its bounded latest state in the existing
operational SQLite store; its persistence is not proof of distributed storage.
The new historical API proves that a client can request data already committed
to HDFS and receive a query result without loading the entire lake into the web
process. The same HDFS Silver data must also feed the offline ETA-history
validation in section 6; without that link, the cluster is only a side demo.

This design is deliberately smaller than the proposal:

- No Kafka in release 1: the observed crawler rate is modest and a durable spool
  plus retryable WebHDFS upload provides a testable delivery boundary.
- No Hive Metastore or HiveServer2 in release 1: Spark SQL reads the declared
  Parquet paths directly, avoiding another stateful service.
- No Spark Structured Streaming in release 1: a scheduled bounded Spark job is
  easier to recover, demonstrate, and assess. It remains compatible with a
  later streaming consumer.
- No fake/local "HDFS fallback": when the cluster is unavailable, ingestion
  retains spool files and reports degraded health. Calling a local directory
  HDFS would invalidate the learning objective.

### Academic claim boundary

The team claims only that the architecture and repeatable experiment model the
essential properties of a distributed historical bus-data store: partitioned
durable files, replicated HDFS blocks, distributed Spark reads, deterministic
replay, and a domain query/ETA-validation result. It does **not** claim public
24/7 availability, city-scale throughput, commercial SLA, or that the small
student cluster is itself a BusMap/TimBus replacement. Controlled scale data is
allowed solely to make block placement and parallel processing observable; it
must be generated deterministically from documented bus-shaped input and be
labelled `benchmark`, never presented as real observations.

## 2. Assumptions and boundaries

1. Docker Desktop with Linux containers is available on the demonstration host.
   Hadoop is not run natively on Windows.
2. The minimum demonstration cluster has one NameNode and **two DataNodes**;
   `dfs.replication=2`. A one-DataNode cluster is permitted only for local
   development and must declare replication `1`, not claim fault tolerance.
3. The crawler yields BusMap snapshots. A snapshot is treated as an at-least-once
   delivery source, so duplicate events are expected and are removed during the
   Bronze-to-Silver transformation.
4. A demo run begins either with a bounded capture from the existing BusMap
   crawler or a replay of a tracked/recorded crawler-shaped raw window. Each
   object carries a source-window identifier, so its provenance can be shown.
5. `data/hanoi_bus_system.db`, existing local lakehouse files, model artifacts,
   and web-demo contracts are not migrated or rewritten by this scope.
6. The project does not promise a 24/7 public production service. It demonstrates
   the same separations—durable ingest, replayable history, analytical query,
   and client API—that such a service needs.

## 3. Components and responsibilities

| Component | Responsibility | Persistent state |
| --- | --- | --- |
| Existing crawler | Produces raw BusMap/TomTom payloads; it does not speak SQL. | none required here |
| Spool writer | Atomically closes a time-windowed JSONL file before it is eligible for upload. Retains it until upload is acknowledged. | host volume `runtime/hdfs_spool/` (ignored) |
| HDFS uploader | Creates Bronze objects through WebHDFS and records a local upload receipt. Retries safely after failure. | spool + receipt sidecar |
| HDFS cluster | Stores Bronze and Silver data blocks and replica metadata. | Docker named volumes |
| Spark batch job | Validates, de-duplicates, projects/normalizes using existing rules, and writes Silver Parquet plus domain aggregates. | HDFS Silver/Gold paths |
| Query service | Accepts a deliberately small historical-query contract, invokes a bounded Spark SQL query, and returns JSON. | no data copy |
| Offline ETA validator | Uses the HDFS Gold/Silver result and held-out observed trips to evaluate a historical ETA baseline. | HDFS Gold evidence path + report |
| Existing live service | Serves latest vehicle/ETA state. It must not scan HDFS in request handling. | existing operational store/cache |

The implementation may run Spark in a dedicated container or submit `spark-submit`
to the cluster. It must not silently replace Spark SQL with pandas/DuckDB on a
downloaded full dataset, because that would not validate the HDFS query path.
For the academic demo, a CLI or a single queued worker is sufficient for the
history endpoint; a production multi-user query service is explicitly out of
scope. The endpoint must nevertheless enforce the stated route/date bounds.

## 4. Data contract and HDFS layout

All timestamps are UTC ISO-8601 in Bronze and UTC epoch milliseconds in Silver.
`dt` is derived in `Asia/Ho_Chi_Minh` for bus-operation reporting and is always
written explicitly; it is not inferred from the host timezone.

```text
/bus-eta/v1/
  bronze/
    telemetry/provenance=<class>/dt=YYYY-MM-DD/hr=HH/ingest-<uuid>.jsonl
    incidents/provenance=<class>/dt=YYYY-MM-DD/hr=HH/ingest-<uuid>.jsonl
  silver/
    route_projected_telemetry/provenance=<class>/dt=YYYY-MM-DD/hr=HH/part-<job-run>-<n>.snappy.parquet
    fact_route_tomtom_incidents/provenance=<class>/dt=YYYY-MM-DD/hr=HH/part-<job-run>-<n>.snappy.parquet
  gold/
    route_speed_hourly/provenance=<class>/dt=YYYY-MM-DD/part-<job-run>.snappy.parquet
  _checkpoints/bronze_to_silver/<job-run>.json
```

Bronze is immutable: the uploader never overwrites a successfully named object.
It sends only fully closed files. Each upload name contains a UUID, so a retry
uses a `GETFILESTATUS` check: an existing object with matching byte length and
SHA-256 is success; a mismatch is a hard error requiring a new UUID. This
prevents a half-retried request from being mistaken for data loss.

### 4.1 Canonical cross-module event envelope (Bronze)

Module 1 must emit one JSON object per telemetry observation with this envelope:

| Field | Type | Owner/rule |
| --- | --- | --- |
| `schema_version` | string | Starts at `bus-telemetry.v1`; incompatible change requires a new version. |
| `provenance` | enum | `observed`, `replayed_observed`, or `synthetic_scale`; immutable and propagated to all tiers. |
| `source_window_id` | string | Module-1 capture or replay window identifier, retained end to end. |
| `event_id` | string | Deterministic SHA-256 of canonical source and observation identity; never a database auto-increment. |
| `observed_at_epoch_ms`, `received_at_epoch_ms` | long | UTC; source observation time and crawler receipt time respectively. |
| `route_id`, `route_code`, `vehicle_id`, `plate`, `direction` | scalar | Source identifiers; `direction` becomes `go` or `re` in Silver. |
| `lat`, `lon` | double | WGS84 source coordinate. |
| `payload` | object | Original source fields retained only where needed for replay/audit. |

`event_id` uses canonical string formatting and includes source name, source-side
record identity when supplied, route/vehicle, observation time, and coordinates.
Its exact serializer and a fixed fixture set must be published before coding;
otherwise modules can silently generate incompatible de-duplication keys.

### 4.2 Silver and Gold contracts

The initial Silver telemetry schema is compatible with the current
`route_projected_telemetry` Parquet contract, with envelope fields added:

| Field | Type | Rule |
| --- | --- | --- |
| `event_id`, `source_window_id`, `provenance` | string | Envelope lineage; `event_id` is the de-duplication key |
| `ping_id` | long nullable | Current local identifier if available; not a distributed primary key |
| `route_id`, `vehicle_id` | long | required |
| `route_code`, `plate`, `direction` | string | `direction` is `go` or `re` |
| `device_update_time` | string | source time retained for traceability |
| `device_epoch_ms`, `ingested_at_epoch_ms` | long | UTC epoch milliseconds |
| `lat`, `lon`, `s_bus_m`, `cross_track_m`, `derived_speed_kmh` | double | existing physical/quality rules apply |

`route_code` is a column, not an HDFS partition in release 1. At sparse student
capture volume, partitioning each day by 48 routes creates many small Parquet
files; at the target 5-second × 2,000-bus rate, `dt/hr` prevents oversized daily
tasks while retaining date/hour pruning. Spark output is sorted by
`route_code, vehicle_id, device_epoch_ms` and targets 32–128 MiB files where
the volume permits. Existing local `route_code=.../dt=...` files remain a legacy
input/output contract and are out of scope.

## 5. Processing semantics

1. A one-hour collector window writes `*.jsonl.tmp`, fsyncs/closes it, then
   renames it to `*.jsonl`. Only the final extension may be uploaded. A shorter
   capture cadence may feed the local spool, but it is consolidated into this
   hourly Bronze object so the simulation does not manufacture an HDFS
   small-files problem.
2. The uploader sends the closed file to the matching Bronze hour. On failure it
   leaves the spool file unchanged and exposes backlog age/count in health.
3. The scheduled Spark job reads selected Bronze windows, applies the
   storage-independent projection boundary defined by SPEC-26, removes duplicate
   `event_id` values, and rejects rows failing required fields or
   `cross_track_m > MAX_CORRIDOR_CROSS_TRACK_M`. It may not reimplement a
   second Frenet approximation.
4. It writes a new, immutable Silver run and then writes its checkpoint only
   after output validation succeeds. Re-running the same input must yield the
   same distinct event set; it must not create a second logical record.
5. A daily compaction job may replace a completed Silver *physical* run only
   through write-to-new-path, validate, then atomically publish a current-path
   manifest. It must never delete the previous validated output before the new
   manifest is published.

The maximum expected delay to analytical visibility is one collector window
plus one scheduled transformation interval. It must be configured and exposed
as a documented value, rather than described as "real-time".

## 6. Mandatory bus-domain integration

The HDFS slice is accepted only when the following chain is demonstrated using
the same `source_window_id`:

```text
existing crawler capture/replay
  -> Bronze telemetry on HDFS
  -> Spark sanitization + Frenet projection -> HDFS Silver
  -> Spark daily route-speed aggregate -> HDFS Gold
  -> (a) historical route-speed query and (b) offline ETA-history validation
```

The existing sanitizer/projection rules and canonical route/station masters are
the domain definition. The Spark transformation may call or faithfully port
those rules, but its output must be checked against a small, independently
selected sample produced by the existing pipeline. This prevents a generic GPS
ETL job from being called a bus-storage system.

For each route/date/hour with sufficient observations, the Gold job produces
at least `ping_count`, `avg_speed_kmh`, and a route/station-segment historical
travel-time statistic. The offline ETA validator reads that HDFS result and a
held-out observed trip set, then reports:

- coverage: number and proportion of hold-out trips for which a historical
  estimate is available;
- MAE in seconds between the historical estimate and observed trip duration;
- a reconciliation table for a small sample against the current local baseline
  calculation, explaining any intentional semantic difference.

This is validation of the storage-backed historical feature path, not a claim
that HDFS improves the ML model or a requirement to retrain it. If coverage is
too small, the run is reported as inconclusive rather than padded with invented
ground truth.

## 7. Historical query API

The only required public analytical endpoint is:

```text
GET /api/history/route-speed?route_code=<code>&date_from=YYYY-MM-DD&date_to=YYYY-MM-DD
```

Response 200:

```json
{
  "route_code": "01",
  "date_from": "2026-11-01",
  "date_to": "2026-11-02",
  "rows": [{"dt": "2026-11-01", "ping_count": 1234, "avg_speed_kmh": 18.2}],
  "storage": "hdfs-silver",
  "generated_at": "2026-11-10T00:00:00Z"
}
```

The service validates the route and an inclusive date range no greater than 31
days. It uses parameter binding or an allow-listed SQL relation/value builder;
raw user text must never be interpolated into Spark SQL. It reads only matching
`dt` partitions and selects only the columns needed for `COUNT` and `AVG`.
When Spark/HDFS is unavailable it returns `503` with a machine-readable
`hdfs_unavailable` code. It does not return stale local data while claiming
`storage: hdfs-silver`.

This endpoint is intentionally an analytical summary, not a generic SQL proxy
and not a replacement for the live ETA APIs.

## 8. Deployment and distributed-property proof

`docker-compose.hdfs.yml` (implementation work) must define:

- one NameNode, two DataNodes, and a Spark execution service/submit client;
- explicit persistent Docker volumes for NameNode and both DataNodes;
- a private Compose network; NameNode UI/WebHDFS may be bound to localhost for
  the demo, while DataNode internals are not exposed unnecessarily;
- health checks that demonstrate two live DataNodes and an under-replicated
  block count of zero after the demo ingest.

For an honest fault-tolerance demonstration, upload a file with replication 2,
stop one DataNode, show that the file remains readable, then restart it and
show replication recovers. The team must state that this is availability of one
replica loss, not high availability of the NameNode (HA is out of scope).

To make distribution visible despite the small real capture, the demo includes
a deterministic `benchmark` dataset derived from the same valid Silver schema.
Its generator, seed, multiplier, input row count, output byte size, and
separation from real data must be published. It must create at least three HDFS
blocks and enough partitions/tasks for Spark to show work on more than one
executor. This benchmark establishes the mechanism, not a fabricated claim of
real-world data volume.

## 9. Implementation phases

1. **Cluster proof:** Compose cluster, health script, HDFS namespace creation,
   and replication demonstration. Verify HDFS reports two live DataNodes.
2. **Durable ingest:** spool/uploader and Bronze contract. Verify an induced
   WebHDFS outage retains a closed file and a later retry uploads exactly one
   valid object.
3. **Silver and domain transform:** Spark job and checkpoint/manifest. Verify
   duplicate Bronze events produce one Silver event, physical constraints hold,
   and Gold aggregate agrees with an independently selected local sample.
4. **Query and ETA-history validation:** bounded API plus offline validator.
   Verify query totals independently with `spark-sql` on the same HDFS path;
   retain coverage/MAE evidence rather than making an accuracy claim by fiat.
5. **Demo/runbook:** repeatable commands, diagrams, benchmark provenance, and
   raw verification logs. Do not resume web-demo feature work in this phase.

## 10. Acceptance criteria and black-box evidence

| ID | Required evidence |
| --- | --- |
| HDFS-01 | Cluster health reports two live DataNodes; a written test file has replication 2 and zero missing blocks. |
| HDFS-02 | A crawler-shaped sample is durable in Bronze after uploader process restart; byte hash and row count match the closed spool file. |
| HDFS-03 | Replaying a Bronze input does not duplicate `event_id` in Silver. |
| HDFS-04 | Silver Parquet can be read by Spark from HDFS; schema and physical bounds (`cross_track_m <= 35`, non-negative speed) pass. |
| HDFS-05 | The history endpoint returns a route/date aggregate matching an independent Spark SQL query and labels storage `hdfs-silver`. |
| HDFS-06 | Querying one date does not read unrelated date partitions, shown by Spark plan/log evidence. |
| HDFS-07 | With HDFS unavailable, the history endpoint returns 503 and the uploader leaves unacknowledged spool data recoverable. |
| HDFS-08 | With one DataNode stopped after replication is complete, the demonstration file remains readable; after restart, replication returns to target. |
| HDFS-09 | One source window can be traced crawler/replay → Bronze → Silver → Gold → historical API and ETA-history report; the report contains hold-out coverage and MAE or explicitly reports insufficient coverage. |
| HDFS-10 | The published benchmark has a fixed seed and is visibly separate from real data; `hdfs fsck` shows its blocks on at least two DataNodes and Spark logs/UI show reads executed by at least two executors. |

`@blind_tester` must derive black-box tests from this section without reading
the coder implementation. `@whitebox_auditor` must verify that the production
path actually uses WebHDFS/HDFS and Spark SQL, preserves the spool/retry rule,
and contains no mock-local success path. Both reports are mandatory before the
feature is accepted.

## 11. Explicit non-goals and later options

Not in this release: Kafka, ZooKeeper, Hive Metastore, HDFS NameNode HA,
Kerberos, Kubernetes, continuous Spark streaming, generic SQL, production
multi-user SLA, model retraining, or migration of all historical local files.
Add Kafka only when multiple independent consumers or source throughput make
spool-based decoupling insufficient. Add Hive/Trino only when several users or
tools require shared, interactive SQL; neither is necessary to prove the HDFS
storage objective.

The key trade-off is intentional: this plan sacrifices always-on ingestion and
interactive-query polish for a smaller experiment that can be rerun by students
and still proves real HDFS replication, Spark computation, and a bus-ETA
historical-data use case. It fails the academic objective if its commands read
only a local mirror, if benchmark data is disguised as observed telemetry, or
if the HDFS result is not consumed by the stated domain query and validation.

## 12. Coordinated roadmap and compatibility decision

### 12.1 Compatibility stance

The HDFS contract is additive in the first release. Existing Module-1 JSON
capture, SQLite tables, local Parquet lakehouse, feature builder, model files,
and web APIs retain their current contracts. There is no bulk migration and no
dual-write claim of transactional consistency. The one permitted interface
change is a Module-1 adapter that serializes a closed crawler window into the
Bronze envelope in section 4.1. Module 2 owns all HDFS paths and transformations.
Module 3 consumes HDFS Gold only through the offline validator until parity is
demonstrated; it does not change online ETA serving.

This lets the team prove the new path without destabilizing the established
course artifacts. Promotion of HDFS Gold as an input to the existing feature
builder is a later, explicit decision requiring record-count, schema, and
sample-value parity with the existing local source.

### 12.2 Phased work

| Phase | Narrow change | Evidence to exit |
| --- | --- | --- |
| P0 — contract fixtures | Freeze envelope serializer, provenance rules, representative observed/replay fixtures, and expected event IDs. No services. | Two independently run fixture checks produce byte-identical event IDs and schema validation. |
| P1 — minimum vertical slice | Add the crawler-window adapter, HDFS Compose cluster, uploader, and one Spark Bronze→Silver→Gold run for a bounded real/replayed window. | Trace one `source_window_id` end-to-end; row counts and selected values agree with the existing pipeline sample. |
| P2 — domain query/validation | Add the bounded history query and offline ETA-history validator. | Route-speed result is independently reproduced by Spark SQL; coverage/MAE and reconciliation report are retained. |
| P3 — scale simulation | Run deterministic `synthetic_scale` and accelerated `replayed_observed` experiments without mixing them with observed paths. | Published generator/seed/multiplier; ≥3 HDFS blocks, block locations on ≥2 DataNodes, Spark work on ≥2 executors. |
| P4 — optional promotion | Consider HDFS Gold as a feature-builder input only if parity is passed. | Explicit approval plus schema, count, and sample-value parity report; otherwise local pipeline remains canonical. |

The **minimal first milestone is P1**, not a real-time service: one authentic
or recorded crawler window must become a traceable HDFS Bronze object, Spark
must create valid Silver and a route-speed Gold result, and the same selected
records must reconcile with the existing local pipeline. It fails if the input
is hand-authored GPS data or if the transform reads only a local copy.

### 12.3 Scale simulation and interpretation

At a hypothetical 5-second heartbeat from 2,000 buses, the source rate is 400
events/second: 24.48 million observations across a 17-hour bus operating day
(34.56 million for a full day). Sparse public API capture cannot substantiate
that volume. P3 therefore separates two valid experiments:

- `replayed_observed`: replay a recorded crawler window at controlled speed,
  retaining the original events and marking the provenance. This tests recovery
  and backpressure semantics, not larger unique history.
- `synthetic_scale`: deterministically tile/derive valid observations while
  assigning a run namespace, synthetic vehicle identities and/or time offsets.
  It preserves declared route/cadence/value distributions only to test storage
  layout, HDFS blocks, and Spark execution. It is excluded from ETA accuracy,
  real-count, and real-coverage reporting.

Neither form may overwrite observed paths or be queried together with observed
data by default. Every result/report displays provenance and source-window/run
identifiers. This is a simulation of capacity mechanics, not fabricated field
telemetry.

### 12.4 Dependencies, risks, and pass/fail gates

| Risk/dependency | Decision or gate |
| --- | --- |
| Docker/virtualization unavailable | P1 is blocked; do not substitute a local filesystem and claim HDFS. |
| Existing sanitizer/Frenet logic cannot be called from Spark | SPEC-26 focused extraction and its parity fixtures must pass before P1 exits; no second geometry implementation is allowed. |
| Sparse capture has insufficient ETA hold-out coverage | P2 reports `inconclusive`; it does not manufacture accuracy results. |
| Event identity changes across modules | P0 fails; no ingestion implementation begins until shared fixtures pass. |
| Student hardware cannot retain the proposed benchmark | Reduce the published multiplier while preserving ≥3 blocks and two-executor evidence; report the achieved scale, not a target rate. |
| HDFS output diverges from existing pipeline | HDFS remains experimental; P4 promotion is refused until reconciliation passes. |

