# SPEC-29: HDFS ingest network boundary

**Status:** proposed.  This is a narrow prerequisite to SPEC-25 P1 following
SPEC-27 and SPEC-28.

## 1. Decision

Keep `hdfs-private` as an `internal: true` Compose network.  Do **not** make
the NameNode or DataNode WebHDFS endpoints reachable from the Windows host and
do not remove `internal: true` merely to make a host Python process connect.

Instead, the host owns only the durable spool directory.  A dedicated,
unpublished Compose **ingest runner** joins `hdfs-private`, bind-mounts that
same directory read/write, and executes the existing WebHDFS uploader against
the in-network NameNode endpoint.  It may be invoked as a bounded Compose
one-shot command for the academic demo; it is not an always-on service.

The runner may consume only fully closed spool files and must use the existing
receipt/idempotency protocol.  It cannot read a host-local HDFS substitute.
The crawler/spool writer remains a host process; moving the uploader's process
into the private network does not change the canonical envelope, partition
path, receipt format, or retry semantics.

## 2. Rationale and rejected alternatives

An internal Docker network intentionally has no host-external route.  Binding
the NameNode UI to `127.0.0.1` is not sufficient for host WebHDFS writes:
WebHDFS redirects a create/read request to a DataNode, whose container address
is deliberately private.  Publishing only port 9870 would therefore either
fail on redirect or tempt an implementation to expose DataNode endpoints.

Rejected alternatives:

- Removing `internal: true` or publishing DataNode WebHDFS ports: expands the
  attack/demo surface and does not add an academic property.
- A host-only local-directory success path: violates SPEC-25.
- Copying the spool file into a container with `docker cp`: creates an
  undocumented second delivery mechanism and weakens restart evidence.
- Installing a proxy or external gateway: unnecessary infrastructure for the
  student experiment.

## 3. Required topology and ownership

```text
host crawler -> runtime/hdfs_spool/ (bind mount) <- ingest-runner (private)
                                                -> WebHDFS -> NameNode/DataNodes
```

`runtime/hdfs_spool/` is the only shared host/container state.  The runner
must not have published ports.  NameNode UI may stay loopback-bound only for
observation; Spark UI/master may likewise remain loopback-bound.  DataNode
ports remain unexposed.

The runner uses the standard Spark/container Python environment that already
passed SPEC-27/28 import probes.  It imports the concrete uploader module,
not an eager package facade, and it derives no `dt`/`hr`; those components are
already fixed by the host spool path.

## 4. Acceptance evidence

| ID | Required evidence |
| --- | --- |
| NET-01 | `docker compose config` shows `hdfs-private.internal: true`; no DataNode ports and no ingest-runner ports are published. |
| NET-02 | A host-created, atomically closed spool file is visible to the runner through the bind mount; a `.tmp` file is ignored. |
| NET-03 | The runner uploads that closed file by real in-network WebHDFS to the declared Bronze `hdfs://` path.  HDFS hash, byte count, and local receipt match. |
| NET-04 | Re-running the runner after its acknowledgement creates no second logical Bronze object; interrupting before acknowledgement leaves the original spool artifact recoverable. |
| NET-05 | Stopping the NameNode makes the runner fail explicitly and preserve the spool artifact/receipt state; it does not report a local success. |
| NET-06 | The P1 runbook contains the bounded Compose command and the exact `hdfs dfs`/hash commands used to verify NET-03--05. |

Passing NET-01--NET-06 replaces the host-network portion of SPEC-28 TZ-04.
TZ-01, TZ-02, TZ-03, and TZ-05 remain mandatory.  No Spark Silver/Gold work
may be accepted before NET-01--NET-06 and the existing P1 Bronze evidence
pass.
