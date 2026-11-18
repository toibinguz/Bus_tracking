# P1 live evidence: 2026-11-11

This directory is the immutable evidence set for the bounded P1 recovery
checks in `docs/HDFS_P1_RECOVERY_ADDENDUM.md`.  It was captured on
2026-11-11 in the `desktop-linux` Docker context.  The test payload is a
735-byte crawler-shaped JSONL fixture copied into a new closed spool file;
it contains no credentials or production data.

| Check | Raw record | Result |
| --- | --- | --- |
| NET-01 / NET-06 topology | `TOPOLOGY.md` | `hdfs-private` is internal; only loopback observation ports are exposed; two DataNodes live. |
| NET-04 failpoint, recovery, idempotency | `NET04.md` | Pass. |
| NET-05 NameNode outage | `NET05.md` | Pass. |

The HDFS checksum is HDFS's block checksum, not SHA-256.  The receipt records
the SHA-256 of the host spool file; the records in `NET04.md` show the same
digest before and after recovery.

Re-run commands are in the addendum.  `runtime/` is intentionally not tracked:
these records preserve the auditable snapshots that are otherwise transient.
