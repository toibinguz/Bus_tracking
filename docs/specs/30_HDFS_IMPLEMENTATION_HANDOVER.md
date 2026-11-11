# HDFS implementation handover

**Status:** paused at a safe boundary because the execution quota was exhausted.  
**Scope:** Module 2 distributed-storage vertical slice only. Web-demo work remains frozen.

## Decisions already accepted

- **SPEC-25:** Academic, repeatable HDFS simulation: crawler/replay -> Bronze
  HDFS -> Spark Silver/Gold -> historical query and offline ETA validation. It
  is not a 24/7 production-SLA claim. Observed, replayed-observed, and
  synthetic-scale data must retain distinct provenance.
- **SPEC-26:** Extract the existing route projection as one pure boundary,
  `project_route_events`; no duplicate geometry. The raw direction adapter
  explicitly maps `0 -> go`, `1 -> re`, all others to `unknown`.
- **SPEC-27:** Module 2 uses lazy public exports. The HDFS path imports its
  concrete submodule and must not pull pandas-dependent legacy exports into
  the Spark image.
- **SPEC-28:** Timezone-aware spool partitioning stays at the host boundary.
  Spark-side WebHDFS code uses timezone-free receipt/hash helpers and must not
  import `zoneinfo` on the Python 3.8 Spark image.
- **SPEC-29:** Keep `hdfs-private` internal. The host owns only the durable
  spool bind-mount; a non-published Compose `ingest-runner` uploads via WebHDFS
  inside that network. Do not expose NameNode/DataNodes or add a local fallback.

## Completed, evidenced work

| Area | State | Evidence/commits |
| --- | --- | --- |
| Projection parity gate | accepted | Both white-box and black-box audits accepted SPEC-26 at `2e940c5`; F1-F6 and P0 are committed and DB-free. F6 has six frozen source events and expected rows. |
| Base HDFS proof | passed | Compose NameNode, two DataNodes, Spark master/two workers; `dfsadmin` showed two live DataNodes. An RF=2 HDFS file was readable with one DataNode stopped, then recovery succeeded. |
| Lazy import boundary | implemented | `ca743e3`, `c07f8c8`; fresh-import/API tests passed and the Spark probe no longer pulled pandas legacy imports. |
| Timezone import boundary | implemented | `bdbf487`; `receipt.py` is timezone-free, standard Spark-container import probe passed, and host tests passed. |

The current implementation branch is `codex/hdfs-vertical-slice`. Previous
leaf reports mentioned an existing uncommitted Compose mount change; preserve
and inspect it before staging or rebasing any work.

## Deliberately unfinished

1. **SPEC-29 implementation and NET-01..NET-06 proof.** `ingest-runner` was
   being implemented when paused. It must upload a closed host spool file over
   real WebHDFS, verify hash/receipt, survive idempotent retry/interruption,
   leave data recoverable during NameNode outage, and never report local
   success.
2. **P1 acceptance.** Only the base replication/failover cluster proof passed;
   the full spool-to-Bronze adapter acceptance has not passed.
3. **P2.** Spark Bronze-to-Silver transform, Gold aggregates, checkpoint/
   manifest semantics, bounded historical API, and offline ETA-history
   validation are not implemented or accepted.
4. **Final acceptance.** After implementation, run a new white-box audit and
   an independent blind black-box test from SPEC-25/29 acceptance criteria.

## Mandatory resume order

1. Inspect `git status` in the implementation worktree; preserve unrelated or
   pre-existing changes.
2. Finish SPEC-29 only; run its real Docker evidence and commit atomically.
3. White-box audit and blind black-box test SPEC-29/P1. A failure blocks P2.
4. Implement P2 exactly as SPEC-25 specifies: Spark reads `hdfs://`, produces
   immutable Silver/Gold outputs, and historical query reads bounded HDFS
   partitions. Do not use pandas/DuckDB/local downloaded copies as a success
   path.
5. Run white-box and blind acceptance for P2, including HDFS-01..HDFS-10 and
   any SPEC-29 criteria, then update the runbook with raw reproducible logs.

## Environmental notes

- Docker Desktop was confirmed running with `desktop-linux`, Linux engine,
  12 CPUs, and 7.57 GiB RAM. The sandbox needs escalation to access Docker's
  named pipe; an in-sandbox connection failure does not establish that Docker
  is down.
- Use elevated Docker checks/Compose only when needed. Do not weaken the
  private-network design solely to make a host HTTP request convenient.
