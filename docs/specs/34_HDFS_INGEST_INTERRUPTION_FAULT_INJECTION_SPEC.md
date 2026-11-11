# SPEC-34: Reproducible interruption between HDFS commit and receipt

**Status:** proposed.  This is a narrow acceptance aid for SPEC-29 NET-04.

## 1. Problem being tested

The ingest protocol has two durable actions:

1. write and verify an immutable Bronze object in HDFS;
2. write the local receipt that acknowledges the matching closed spool file.

An unexpected process stop can occur between those actions.  On the next run,
the uploader must retain the spool file, discover the already-written object by
its declared path/length/SHA-256, avoid creating a second logical object, then
write the missing receipt.  This is the recovery case required by SPEC-29
NET-04.

A Windows Docker bind mount declared read-only is not an acceptable way to
cause this event: Docker Desktop may not enforce that mount mode consistently
for this experiment.  The test therefore must not depend on filesystem
permissions.

## 2. Decision

Add one **test-only, opt-in failpoint** to the existing ingest runner/uploader:

```text
HDFS_INGEST_FAULT=after_remote_commit_before_receipt
```

The value has exactly this spelling.  Any absent or other value leaves normal
production behavior unchanged.  The runner reads the value only from its
environment; it is not an HTTP/API option and is not persisted in a receipt or
spool file.

When the value is set, the uploader must:

1. upload the closed spool object through normal WebHDFS;
2. run the normal remote length/SHA-256 verification;
3. emit one structured log line identifying the failpoint and spool/object
   identifiers;
4. terminate non-zero **before** creating or modifying the local receipt.

It must not delete, rename, truncate, or otherwise mutate the closed spool
file.  It must not write a local-success marker.  It must not bypass WebHDFS.

The failpoint is a deterministic test instrument, not a production recovery
mechanism.  It must be documented in the runbook as test-only and must not be
enabled by the default Compose service or normal command.

## 3. Required recovery demonstration

Use one fresh, closed spool file with a unique object name and perform the
following bounded sequence on the private `ingest-runner` network path:

| Step | Required observation |
| --- | --- |
| A | Run with the failpoint.  Exit is non-zero; HDFS contains exactly one matching Bronze object; spool remains; no receipt exists. |
| B | Run normally against the same spool file.  The runner recognizes the matching committed object by hash/length, writes the receipt, and does not create another logical Bronze object. |
| C | Run normally once more.  It is acknowledged/no-op; the object count and object SHA-256 remain unchanged. |

The evidence must record the spool SHA-256, HDFS checksum/byte count or
equivalent HDFS hash proof, receipt contents, object path, runner exit codes,
and object count after each step.  The runner must be invoked only through
Compose on `hdfs-private`; host WebHDFS and local-directory substitutes remain
forbidden.

## 4. Acceptance additions

NET-04 passes only when the Step A/B/C evidence above is present in the
runbook/logs and a focused automated test verifies that the failpoint cannot
write a receipt.  The existing ordinary acknowledged-rerun check remains
required; it does not replace the interrupted-then-recovered case.

No other failure injection is required by this decision.  NameNode-unavailable
behavior continues to be evaluated separately under NET-05.
