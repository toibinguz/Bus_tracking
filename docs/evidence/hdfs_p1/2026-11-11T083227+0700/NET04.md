# NET-04: interrupted acknowledgement, recovery, and idempotency

Captured: `2026-11-11T08:32:27+07:00` through `2026-11-11T08:33:12+07:00`

Fresh closed spool file:

```text
runtime/hdfs_spool/dt=2026-11-01/hr=10/ingest-audit-net04-20261111.jsonl
host SHA-256: f354b34572190ad64aadda6f61a3d4e51057123601fb0a7dc8d4f894ee2dc90d
HDFS path: /bus-eta/v1/bronze/telemetry/dt=2026-11-01/hr=10/ingest-audit-net04-20261111.jsonl
```

## A. Stop after remote commit, before local acknowledgement

Command:

```powershell
docker compose -f docker-compose.hdfs.yml --profile ingest run --rm `
  -e HDFS_INGEST_FAULT=after_remote_commit_before_receipt ingest-runner
```

Raw result:

```text
{"event":"hdfs_ingest_failpoint","fault":"after_remote_commit_before_receipt",
 "hdfs_path":"/bus-eta/v1/bronze/telemetry/dt=2026-11-01/hr=10/ingest-audit-net04-20261111.jsonl",
 "spool_file":"ingest-audit-net04-20261111.jsonl"}
RuntimeError: HDFS_INGEST_FAULT after_remote_commit_before_receipt
runner_exit=1
spool_exists=True
receipt_exists=False
```

Immediately after the non-zero exit:

```text
hdfs dfs -ls:
-rw-r--r-- 2 root supergroup 735 2026-11-11 01:32
  /bus-eta/v1/bronze/telemetry/dt=2026-11-01/hr=10/ingest-audit-net04-20261111.jsonl

hdfs dfs -checksum:
MD5-of-0MD5-of-512CRC32C 000002000000000000000000209997489f73abbd0dd7e0318c4d75b0

hdfs fsck:
735 bytes, replication=2, Live_repl=2, Status: HEALTHY
locations: datanode-1 and datanode-2
```

## B. Normal recovery

Command:

```powershell
docker compose -f docker-compose.hdfs.yml --profile ingest run --rm ingest-runner
```

Raw result:

```text
recovery_exit=0
spool_exists=True
receipt_exists=True
receipt={"hdfs_path":"/bus-eta/v1/bronze/telemetry/dt=2026-11-01/hr=10/ingest-audit-net04-20261111.jsonl",
         "sha256":"f354b34572190ad64aadda6f61a3d4e51057123601fb0a7dc8d4f894ee2dc90d"}
```

## C. Acknowledged retry

Command and result:

```powershell
docker compose -f docker-compose.hdfs.yml --profile ingest run --rm ingest-runner
```

```text
retry_exit=0
matching HDFS object count=1
HDFS checksum unchanged:
MD5-of-0MD5-of-512CRC32C 000002000000000000000000209997489f73abbd0dd7e0318c4d75b0
```
