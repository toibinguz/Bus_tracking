# SPEC-33: NameNode loopback observation decision

**Status:** accepted clarification of SPEC-29; no implementation is implied by
this document.

## 1. Decision

Keep the existing NameNode binding:

```text
127.0.0.1:9870:9870
```

It is a **loopback-only observation exception**, not an ingest endpoint.  It
may be used on the demonstration host to inspect the NameNode UI and health.
It must not be used by the crawler, spool writer, or host uploader to write or
read project telemetry.

The accepted ingest path remains:

```text
host crawler -> runtime/hdfs_spool bind mount -> ingest-runner
             -> http://namenode:9870 inside hdfs-private -> DataNodes
```

The NameNode, DataNodes, and ingest runner remain unreachable from another
machine.  The NameNode binding is not a permission to publish a DataNode port,
remove `hdfs-private.internal: true`, or add a host WebHDFS success path.

## 2. Reason

SPEC-29 section 3 already permits a NameNode UI that is bound only to loopback
for observation.  Its NET-01 criterion prohibits published DataNode and
ingest-runner ports; it does not prohibit that observation binding.  The
stricter statement in the resume note was therefore inaccurate.

WebHDFS is still not a valid host ingestion route: an operation started at the
NameNode redirects to a DataNode, whose endpoint remains private.  The runner
inside `hdfs-private` is consequently required for real upload and retry
evidence.

## 3. Acceptance interpretation for NET-01

NET-01 passes only when all of the following are shown:

1. `docker compose -f docker-compose.hdfs.yml config` reports
   `hdfs-private.internal: true`.
2. NameNode has at most the exact loopback binding `127.0.0.1:9870:9870`.
3. Neither DataNode nor `ingest-runner` has a `ports:` entry or a published
   port in `docker compose ps`.
4. The runner configuration names `http://namenode:9870`, not
   `http://127.0.0.1:9870` or a host address.
5. NET-03--NET-05 evidence is produced by the Compose `ingest-runner`, never
   by a host WebHDFS client.

Spark's loopback-bound UI/master ports remain governed by SPEC-29 section 3
and are outside the HDFS ingestion boundary.
