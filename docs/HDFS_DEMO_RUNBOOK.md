# HDFS academic simulation runbook

This cluster is a reproducible teaching experiment, not a 24/7 deployment.
It must use HDFS and Spark directly; a local-directory replacement is invalid.

## Start and verify

With Docker Desktop running in Linux-container mode:

```powershell
.\scripts\hdfs_demo.ps1 up
.\scripts\hdfs_demo.ps1 health
```

`health` passes only when HDFS reports two live DataNodes. The NameNode UI is
loopback-bound only; DataNode and WebHDFS paths are private.

## Required P1 evidence

1. Capture or replay one real crawler-shaped source window.
2. Use `hdfs_bronze_adapter` to create envelopes and `spool.write_closed_window`.
3. Run the bounded private-network uploader:

```powershell
docker compose -f .\docker-compose.hdfs.yml run --rm ingest-runner
```

4. Verify the receipt and HDFS object without a host WebHDFS connection:

```powershell
docker compose -f .\docker-compose.hdfs.yml exec namenode hdfs dfs -cat /bus-eta/v1/bronze/telemetry/dt=YYYY-MM-DD/hr=HH/ingest-UUID.jsonl
docker compose -f .\docker-compose.hdfs.yml exec namenode hdfs dfs -checksum /bus-eta/v1/bronze/telemetry/dt=YYYY-MM-DD/hr=HH/ingest-UUID.jsonl
Get-FileHash .\runtime\hdfs_spool\dt=YYYY-MM-DD\hr=HH\ingest-UUID.jsonl -Algorithm SHA256
```

The runner ignores `*.tmp`, preserves an unacknowledged spool artifact when
the NameNode is unavailable, and records a receipt only after WebHDFS accepts
the immutable object. Re-run the same Compose command to verify idempotency.

Do not mark P1 complete until the HDFS runtime commands have succeeded. Docker
volumes are retained by `down`; remove them only for an intentional fresh demo.
