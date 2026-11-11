# SPEC-35: P2 Spark Bronze-to-Silver/Gold implementation directive

**Status:** implementation directive after P1 acceptance.  
**Owner:** `@architect`  
**Scope:** the smallest real Spark/HDFS transformation slice.  The web demo,
historical HTTP endpoint, and online ETA path remain out of scope.

## 1. Preconditions and boundary

P1 is accepted on `codex/hdfs-vertical-slice` at `a7096ad`: a closed spool
file is uploaded through the private `ingest-runner`, retry is idempotent, and
HDFS outage preserves the spool.  P2 must use that accepted Bronze path; it
must not read a host JSON file, a local Parquet copy, pandas, DuckDB, or SQLite
as its telemetry input and call that an HDFS result.

The exact first P2 slice is deliberately bounded:

```text
one replayed-observed source window in HDFS Bronze
  -> one Spark application reading hdfs://.../bronze
  -> projection through the accepted SPEC-26 boundary
  -> HDFS Silver Parquet
  -> HDFS Gold hourly route-speed Parquet
  -> immutable checkpoint and publish manifest
```

The source window must be labelled `replayed_observed`, have a committed
fixture/manifest, and contain enough events for both (a) a duplicate
`event_id` case and (b) at least one valid projected speed.  It is not a
benchmark and must not be described as city-scale or real-time data.

## 2. Inputs that the Spark job may use

### 2.1 Bronze telemetry

The job receives explicit `hdfs://namenode:8020/bus-eta/v1/bronze/...` paths,
not a broad glob over the whole namespace.  It validates the `bus-telemetry.v1`
envelope and reads its JSONL with Spark.  Required envelope fields, UTC time
semantics, provenance and deterministic `event_id` remain those in SPEC-25.

The P2 fixture must state all of the following before its first job run:

- `source_window_id`, provenance, Bronze object path, byte SHA-256 and input
  row count;
- the duplicate event identity and expected distinct-event count; and
- the canonical route/station-master digest used by the projection.

### 2.2 Projection references

Spark must not query the mutable SQLite database while transforming rows.
Before the job, a small immutable reference bundle is placed in HDFS under
`/bus-eta/v1/reference/<canonical-master-digest>/`.  It contains only the
route shape(s) and unambiguous station-to-direction mappings needed for the
declared P2 route/window, plus a manifest with their canonical digest.

The job constructs `ProjectableEvent` values and calls the one accepted
`project_route_events` boundary from SPEC-26.  It must not reproduce its
geometry, constants, raw-direction mapping, or corridor rule.  The adapter
maps source direction explicitly (`0 -> go`, `1 -> re`, anything else
`unknown`) before the boundary.

## 3. Job, outputs, and idempotency

### 3.1 Deterministic job identity

Compute `job_key = SHA-256` of canonical JSON containing: input Bronze paths
and hashes, source-window IDs, reference digest, transform schema version, and
the job's own source revision.  A caller supplies no random run identifier.

Before transformation, the job checks
`/bus-eta/v1/_checkpoints/bronze_to_silver/<job_key>.json`:

- no checkpoint: run the job;
- valid checkpoint and readable declared outputs: exit success as a no-op;
- malformed/missing output checkpoint: fail loudly; it must not silently
  append a second logical run.

### 3.2 Silver output

For the declared `provenance`, `dt`, and `hr`, write Parquet to a unique,
immutable run directory:

```text
/bus-eta/v1/silver/route_projected_telemetry/
  provenance=<value>/dt=<YYYY-MM-DD>/hr=<HH>/_runs/job=<job_key>/
```

Silver carries the SPEC-25 lineage fields (`event_id`, `source_window_id`,
`provenance`) and the accepted SPEC-26 projected fields.  Before write,
deduplicate on `event_id`; record raw, distinct, accepted and rejected counts
by stable diagnostic reason.  Do not use a local `ping_id` as identity.

### 3.3 Gold output

The same Spark application reads only its just-validated Silver relation and
writes one hourly aggregate to:

```text
/bus-eta/v1/gold/route_speed_hourly/
  provenance=<value>/dt=<YYYY-MM-DD>/_runs/job=<job_key>/
```

Each aggregate row has at least `route_code`, `dt`, `hr`, `provenance`,
`ping_count`, and `avg_speed_kmh`.  `ping_count` counts accepted Silver rows;
`avg_speed_kmh` is computed only over non-null `derived_speed_kmh`, and the
output must also expose `speed_sample_count` so a null average is never
misread as zero.

### 3.4 Validate, then publish

Validate both Parquet outputs by reading them back through Spark from their
`hdfs://` locations.  Only after validation, write:

1. the immutable checkpoint JSON containing job key, input/reference hashes,
   output paths, row counts, diagnostic counts, aggregate counts and UTC
   completion timestamp; then
2. a small immutable publish manifest identifying this completed run.

The first P2 slice does **not** compact or delete old runs.  A later query
layer consumes only an explicit publish manifest; it must never scan a partial
`_runs` directory.

## 4. Required P2 acceptance evidence

| ID | Pass condition |
| --- | --- |
| P2-01 | Spark application log/config proves `hdfs://` Bronze read and `hdfs://` Silver/Gold writes; no local telemetry mirror is used. |
| P2-02 | Bronze raw count, duplicate identity, distinct count, accepted count and rejection diagnostics agree with the committed P2 fixture. |
| P2-03 | Silver's projected rows equal the accepted SPEC-26 fixture output for the declared input: identity, order-independent fields and legacy rounding. |
| P2-04 | Silver schema/lineage fields are present; all accepted `cross_track_m <= MAX_CORRIDOR_CROSS_TRACK_M`, speed is non-negative or null, and provenance is unchanged. |
| P2-05 | Gold `ping_count`, `speed_sample_count` and average exactly match an independent bounded `spark-sql` query over the stated Silver HDFS path. |
| P2-06 | A second invocation with identical input/reference code exits through the checkpoint path; it creates no second logical Silver/Gold run and output hash/count remain unchanged. |
| P2-07 | Checkpoint/publish manifest exists only after read-back validation and contains enough hashes/counts to reproduce the run. |

Store timestamped raw logs, `hdfs dfs -ls/-checksum` outputs, Spark application
details, fixture manifest and validation query output under
`docs/evidence/hdfs_p2/<timestamp>/`.  The P1 `runtime/` directory remains
untracked operational evidence and is not an input substitute.

## 5. Sequence for the coder

1. Add the committed P2 replay fixture and immutable reference-bundle manifest.
2. Add one Spark-submit entry point and its narrow input/output/checkpoint
   interfaces.  Start with the P2 fixture; do not build a generic ETL platform.
3. Run it in the existing private Spark cluster against Bronze already uploaded
through P1.  Capture P2-01 through P2-05.
4. Re-run unchanged for P2-06 and capture the no-op evidence.
5. Run the focused unit tests plus the live evidence commands.  Only then
   request white-box and independent black-box P2 audit.

## 6. Explicitly deferred after P2

Historical HTTP API, date-partition pruning proof, offline ETA-history
validation, benchmark scale-out, compaction, and all web-demo work remain
deferred.  P2 proves a real, domain-specific Spark/HDFS transformation; it
does not yet prove the complete HDFS vertical slice or a serving system.
