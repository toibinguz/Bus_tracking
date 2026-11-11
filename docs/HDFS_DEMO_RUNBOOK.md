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

## NET-04: retry and interrupted acknowledgement

Pick one closed file and retain the same `$spoolFile` value for every command
in this subsection.  The file must remain under `runtime/hdfs_spool`; do not
copy it into a container.

```powershell
$spoolFile = Get-ChildItem .\runtime\hdfs_spool -Recurse -Filter 'ingest-*.jsonl' |
  Select-Object -First 1
$receiptFile = "$($spoolFile.FullName).receipt.json"
Get-Content $receiptFile
docker compose -f .\docker-compose.hdfs.yml --profile ingest run --rm ingest-runner
docker compose -f .\docker-compose.hdfs.yml exec namenode hdfs dfs -ls /bus-eta/v1/bronze/telemetry/dt=YYYY-MM-DD/hr=HH
```

The second runner invocation must report the same HDFS path already stored in
the receipt.  The `hdfs dfs -ls` output must still contain exactly one object
with that `ingest-UUID.jsonl` name.

To exercise recovery before acknowledgement, create a fresh closed spool file,
start the runner, and interrupt its process before it returns.  The exact file
must still exist locally and must have no receipt:

```powershell
# In one terminal; stop it with Ctrl+C before it prints uploaded=...
docker compose -f .\docker-compose.hdfs.yml --profile ingest run --rm ingest-runner

# In another terminal, for the chosen fresh file:
Test-Path $spoolFile.FullName
Test-Path "$($spoolFile.FullName).receipt.json"
```

Re-run the bounded runner after the interruption.  It must either create the
one immutable HDFS object or recognize the byte-identical object left by the
interrupted attempt; it then writes one receipt.  A second object for the same
spool filename is a failure.

## NET-05: NameNode outage

Use a fresh closed spool file without a receipt.  Stop only the NameNode, run
the private uploader, and require a non-zero exit.  The spool file must remain
and no receipt may be created:

```powershell
docker compose -f .\docker-compose.hdfs.yml stop namenode
docker compose -f .\docker-compose.hdfs.yml --profile ingest run --rm ingest-runner
if ($LASTEXITCODE -eq 0) { throw 'unexpected upload success while NameNode is stopped' }
Test-Path $spoolFile.FullName
Test-Path "$($spoolFile.FullName).receipt.json"
docker compose -f .\docker-compose.hdfs.yml start namenode
docker compose -f .\docker-compose.hdfs.yml exec namenode hdfs dfsadmin -report
```

Do not create a receipt or a local success marker in this outage case.

Do not mark P1 complete until the HDFS runtime commands have succeeded. Docker
volumes are retained by `down`; remove them only for an intentional fresh demo.
