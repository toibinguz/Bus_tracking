# NET-05: NameNode outage

Captured: `2026-11-11T08:34:37+07:00` through `2026-11-11T08:35:14+07:00`

Fresh closed spool file:

```text
runtime/hdfs_spool/dt=2026-11-01/hr=11/ingest-audit-net05-20261111.jsonl
host SHA-256: f354b34572190ad64aadda6f61a3d4e51057123601fb0a7dc8d4f894ee2dc90d
HDFS path: /bus-eta/v1/bronze/telemetry/dt=2026-11-01/hr=11/ingest-audit-net05-20261111.jsonl
```

## A. Stop NameNode and run without dependencies

Commands:

```powershell
docker compose -f docker-compose.hdfs.yml stop namenode
docker compose -f docker-compose.hdfs.yml --profile ingest run --rm --no-deps ingest-runner
```

Raw result:

```text
stop_exit=0
urllib.error.URLError: <urlopen error [Errno -3] Temporary failure in name resolution>
runner_exit=1
spool_exists=True
receipt_exists=False
```

`--no-deps` prevents Compose from starting the stopped NameNode.  The runner
cannot resolve or contact `namenode`; it does not substitute a local target.

## B. Recover NameNode and verify no object was created

Commands:

```powershell
docker compose -f docker-compose.hdfs.yml start namenode
docker compose -f docker-compose.hdfs.yml exec namenode hdfs dfsadmin -safemode leave
docker compose -f docker-compose.hdfs.yml exec namenode hdfs dfsadmin -report
docker compose -f docker-compose.hdfs.yml exec namenode hdfs dfs -test -e $hdfsObject
```

Raw result:

```text
start_exit=0
safemode_exit=0
object_exists_exit=1
Live datanodes (2)
Under replicated blocks: 0
Blocks with corrupt replicas: 0
Missing blocks: 0
```

Exit `1` from `hdfs dfs -test -e` means the outage test object does not exist.
The closed spool file remains and no receipt or local-success marker was made.
