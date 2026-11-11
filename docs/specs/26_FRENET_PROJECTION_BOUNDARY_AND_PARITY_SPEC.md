# SPEC-26: Narrow Frenet projection boundary and parity gate

**Status:** proposed; prerequisite to SPEC-25 P1/P2.  
**Date:** 2026-11-10  
**Owner:** `@architect`  
**Implementation owner:** `@leaf_coder`  
**Scope:** extract one deterministic, storage-independent projection boundary
from the existing SQLite batch projector. No change to projection policy, route
geometry, ETA serving, or database schema is authorized by this document.

## 1. Decision and current blocker

`multi_route_projector.py` currently combines four concerns in its SQLite-bound
batch worker: loading `vehicle_unique_pings`, direction resolution from
`current_station_id`, stateful Frenet projection, and writing
`route_projected_telemetry`. The geometry primitive `project_points_to_shape`
is already computationally pure, but the route worker and speed calculation are
not reusable from HDFS/Spark input.

SPEC-25 cannot create a second approximation of those rules inside a Spark job.
**A focused extraction is permitted and required**: create one pure projection
boundary that is called by both the existing SQLite batch adapter and the new
HDFS/Spark adapter. The existing SQL reads/writes remain thin adapters. Moving
or wrapping the exact existing logic is permitted; changing its thresholds,
algorithms, output semantics, or performing a general Module-1 refactor is not.

The HDFS path remains blocked until this specification's parity gate passes.

## 2. Normative interface

The implementation must expose one importable, side-effect-free operation with
the following conceptual signature (names may differ, fields may not):

```text
project_route_events(events, shape_by_direction, station_direction_lookup)
    -> accepted_projected_events, projection_diagnostics
```

It must not open SQLite, read files, read clocks, mutate global state, write
HDFS, or depend on input row order supplied by a database engine.

### 2.1 Required input: `ProjectableEvent`

The operation receives events from exactly one `(route_id, route_code)`.
Before invocation, the adapter validates required fields and sorts them by
`(vehicle_id, device_epoch_s, event_id)`. P1 fixtures contain no duplicate
`(vehicle_id, device_epoch_s)`; a production collision is rejected/quarantined
with a diagnostic until an explicit policy is specified.

| Field | Type | Rule |
| --- | --- | --- |
| `event_id` | string | Stable source/HDFS identity; replaces SQLite-only `ping_id` as the pure-function key. |
| `legacy_ping_id` | integer nullable | Retained solely by the SQLite adapter/output parity fixture. Not a distributed key. |
| `route_id`, `route_code`, `vehicle_id` | integer, string, integer | Must match the route invocation. |
| `plate` | string nullable | Passed through unchanged. |
| `device_update_time` | string | Passed through unchanged. |
| `device_epoch_s` | float | UTC seconds; conversion from the SPEC-25 millisecond envelope occurs once in the adapter. |
| `direction_hint` | `go`, `re`, or `unknown` | Already normalized by the adapter; raw BusMap direction codes must not be reinterpreted in this boundary. |
| `current_station_id` | integer nullable | Used only for the unambiguous-station override. |
| `lat`, `lon` | float | WGS84. |

**Important compatibility finding:** the telemetry sanitizer comments use a
different raw BusMap direction convention from the projector's legacy database
convention (`0 -> go`, `1 -> re`, otherwise unassigned). The pure boundary
therefore accepts only `direction_hint`; the SQLite adapter reproduces its
current conversion and the HDFS adapter owns one explicit source-to-hint map.
That source mapping is a P0 fixture requirement, not an implicit heuristic.

### 2.2 Required reference inputs

`shape_by_direction` is a mapping for `go` and/or `re` to an ordered list of
`(point_order, lat, lon, cum_distance_m)`, exactly as loaded from
`canonical_shape_master`. `station_direction_lookup` maps an *unambiguous*
`(route_id, station_id)` to `go`/`re`; ambiguous and absent stations are not
present. These inputs are versioned by a recorded canonical-master digest in
each fixture/run manifest.

### 2.3 Required accepted output

Every accepted output has these fields:

```text
event_id, legacy_ping_id, route_code, route_id, vehicle_id, plate,
device_update_time, device_epoch_s, direction, lat, lon,
s_bus_m, cross_track_m, derived_speed_kmh
```

`direction` is `go` or `re`; `s_bus_m` and `cross_track_m` retain the legacy
one-decimal rounding; `derived_speed_kmh` retains the legacy two-decimal
rounding or null. The SQLite adapter maps these fields 1:1 into the current
13-column table (using `legacy_ping_id` as `ping_id`). The HDFS adapter maps
them into the SPEC-25 Silver schema, carrying its envelope lineage separately.

The return order is deterministic: `(vehicle_id, device_epoch_s, event_id)`.
Diagnostics contain counts keyed by stable category, at minimum
`unknown_direction`, `missing_shape`, `off_corridor_or_rejected_projection`,
and `duplicate_timestamp`; diagnostics are observability only and are not a new
Silver schema requirement.

## 3. Preserved projection policy

The extraction must preserve the current `worker_project_route` behavior:

1. An unambiguous canonical station direction overrides the hint; otherwise
   `go`/`re` hint is used and `unknown` is excluded.
2. Events are grouped by vehicle and direction runs. A short opposite-direction
   burst bracketed by the same direction is relabelled only when its enclosing
   time span is `0 < dt <= STALE_DELTA_T_MAX_SEC`.
3. For each contiguous direction run, use the current vectorized orthogonal
   projection and forward sliding-window/global-fallback rules. Do not replace
   it with a nearest-point approximation.
4. Keep only projections satisfying `cross_track_m <=
   MAX_CORRIDOR_CROSS_TRACK_M`; preserve existing terminal-reset and backward
   jitter handling.
5. Compute derived speed only after this corridor filtering, from successive
   accepted events for the same vehicle when direction is unchanged,
   `0 < dt <= STALE_DELTA_T_MAX_SEC`, `ds >= -MAX_GPS_BACKWARD_JITTER_M`, and
   the resulting speed is at most `GPS_DRIFT_MAX_SPEED_KMPH`. Otherwise emit
   null. Constants are imported from `config.system_config`; no duplicate
   numeric literals are permitted.

The boundary does not perform the earlier raw coordinate swap, EMA sanitization,
trip segmentation, incident projection, or any ETA policy. Those remain outside
this narrow extraction.

## 4. Parity fixtures and pass/fail

Fixtures must be committed as small JSON/Parquet inputs plus expected JSON
outputs under a dedicated test-fixture directory. They are generated once from
an independently selected, immutable SQLite source slice and its canonical
shape/station rows; the manifest records source database fingerprint, route,
time interval, canonical-master digest, and expected-result SHA-256.

The suite must include at least:

| Fixture | Must demonstrate |
| --- | --- |
| F1 normal forward run | accepted `go` rows, increasing `s_bus_m`, and a non-null derived speed |
| F2 station override | station lookup overrides an otherwise conflicting direction hint |
| F3 short direction glitch | the bracketed burst is relabelled under the existing time rule |
| F4 off-corridor and backward case | exclusion or null speed consistent with legacy guards |
| F5 terminal reset/long gap | no invalid continuity speed across the boundary |
| F6 selected real slice | at least one route/vehicle window from the current SQLite input, including all accepted rows and order |

For every fixture, the pure boundary must equal the frozen legacy output on:

- the accepted event identity set;
- all output fields, using exact string/integer equality and exact legacy
  rounded numeric values (null equals null);
- deterministic output order; and
- total accepted count.

F6 additionally compares its SQLite-adapter output to the existing
`route_projected_telemetry` rows for the exact source slice. Any mismatch is a
**fail**, not a tolerance discussion. If the legacy output itself changes,
fixtures are regenerated only through an explicit spec/version update with the
old and new evidence retained.

## 5. Integration sequence and acceptance boundary

1. `@leaf_coder` performs only the focused extraction plus SQLite adapter and
   parity tests. Existing full batch CLI must produce the same selected-slice
   result. No HDFS code is required for this sub-milestone.
2. `@whitebox_auditor` confirms there is one projection-policy implementation,
   the old worker delegates to it, and no duplicated thresholds or alternate
   geometric implementation were added for Spark.
3. `@blind_tester` uses fixture contracts and an input/output-only invocation
   to verify F1–F6 without reading implementation code.
4. Only then may the HDFS adapter call this boundary. Its P1 result is compared
   to F6 and the SPEC-25 end-to-end source-window evidence.

Focused extraction is accepted when F1–F6 pass and both audit reports pass.
It is rejected if it changes existing SQLite projection output, uses a separate
Spark geometry algorithm, silently maps ambiguous raw direction values, or
requires a full historical database rebuild merely to run the fixtures.

