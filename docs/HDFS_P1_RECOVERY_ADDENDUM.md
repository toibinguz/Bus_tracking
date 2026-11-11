# HDFS P1 recovery-runbook addendum

**Applies to:** SPEC-29 NET-04, NET-05, and NET-06; SPEC-34 interruption
test.  This file is the canonical bounded runbook for those checks until the
uncommitted `HDFS_DEMO_RUNBOOK.md` and `docker-compose.hdfs.yml` changes are
reviewed and reconciled.  It intentionally does not edit or validate the
legacy `ingest-test` / read-only-mount profile.

## Preconditions and topology check

Run from the repository root after Docker Desktop is running in the
`desktop-linux` context.  The NameNode loopback UI (`127.0.0.1:9870`) is an
observation exception under SPEC-33; it is not an ingest route.  The runner
must use `http://namenode:9870` from the private Compose network.

```powershell
docker context show
docker compose -f .\docker-compose.hdfs.yml config
docker compose -f .\docker-compose.hdfs.yml up -d namenode datanode-1 datanode-2
docker compose -f .\docker-compose.hdfs.yml exec namenode hdfs dfsadmin -report
```

Record the `config` output showing `hdfs-private: internal: true`, no
DataNode or `ingest-runner` published ports, and the report showing two live
DataNodes.  Keep the closed `$spoolFile` under `runtime\hdfs_spool`; never
use host WebHDFS or a local-directory substitute.

## NET-04: interrupted acknowledgement, recovery, and idempotency

Choose a **fresh, closed** `ingest-*.jsonl` file with no receipt and set its
path and declared HDFS object path below.  Capture the command output and all
exit codes.  The failpoint is test-only and must be absent outside this test.

```powershell
$spoolFile = 'runtime\hdfs_spool\dt=YYYY-MM-DD\hr=HH\ingest-UUID.jsonl'
$receiptFile = "$spoolFile.receipt.json"
$hdfsObject = '/bus-eta/v1/bronze/telemetry/dt=YYYY-MM-DD/hr=HH/ingest-UUID.jsonl'
Get-FileHash $spoolFile -Algorithm SHA256

docker compose -f .\docker-compose.hdfs.yml --profile ingest run --rm `
  -e HDFS_INGEST_FAULT=after_remote_commit_before_receipt ingest-runner
if ($LASTEXITCODE -eq 0) { throw 'failpoint unexpectedly succeeded' }
Test-Path $spoolFile
Test-Path $receiptFile
docker compose -f .\docker-compose.hdfs.yml exec namenode hdfs dfs -ls $hdfsObject
docker compose -f .\docker-compose.hdfs.yml exec namenode hdfs dfs -checksum $hdfsObject

# Recovery: recognize the committed object, then create the missing receipt.
docker compose -f .\docker-compose.hdfs.yml --profile ingest run --rm --no-deps ingest-runner
Get-Content $receiptFile

# Acknowledged retry must be a no-op for the same logical object.
docker compose -f .\docker-compose.hdfs.yml --profile ingest run --rm ingest-runner
docker compose -f .\docker-compose.hdfs.yml exec namenode hdfs dfs -ls $hdfsObject
```

Pass condition: failpoint run exits non-zero; the spool file remains, receipt
is absent, and exactly one matching remote object exists.  The normal recovery
creates the receipt after validating the existing object; the second normal
run leaves the object count, byte count, and checksum unchanged.

## NET-05: NameNode outage

Use another fresh closed spool file without a receipt.  Preserve its SHA-256
and receipt state before and after this bounded sequence.

```powershell
docker compose -f .\docker-compose.hdfs.yml stop namenode
docker compose -f .\docker-compose.hdfs.yml --profile ingest run --rm ingest-runner
if ($LASTEXITCODE -eq 0) { throw 'unexpected success while NameNode is stopped' }
Test-Path $spoolFile
Test-Path $receiptFile
docker compose -f .\docker-compose.hdfs.yml start namenode
docker compose -f .\docker-compose.hdfs.yml exec namenode hdfs dfsadmin -report
```

Pass condition: the runner reports an explicit failure, retains the closed
spool file, does not create a receipt or local-success marker, and creates no
HDFS object.  After restart, the HDFS report again shows two live DataNodes.

## Evidence to retain

Keep the Compose output, runner exit codes, spool SHA-256, HDFS `-ls` and
`-checksum` output, receipt contents, and `dfsadmin -report` output together
with the experiment date.  These records are the NET-04/NET-05/NET-06 P1
evidence.  Later, reconcile this addendum with the uncommitted legacy runbook
and Compose changes in a separate, reviewed documentation change; do not
silently restore the read-only-mount method.
