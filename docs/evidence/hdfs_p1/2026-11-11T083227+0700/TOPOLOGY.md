# NET-01 / NET-06 topology snapshot

Captured: `2026-11-11T08:32:51+07:00`

Command:

```powershell
docker context show
docker compose -f docker-compose.hdfs.yml config
docker compose -f docker-compose.hdfs.yml ps
docker compose -f docker-compose.hdfs.yml exec namenode hdfs dfsadmin -report
```

Observed facts from the raw command output:

```text
desktop-linux
networks:
  hdfs-private:
    internal: true
namenode published port: 127.0.0.1:9870 -> 9870/tcp
datanode-1 published ports: none
datanode-2 published ports: none
ingest-runner published ports: none (profile-only service)
Live datanodes (2)
Under replicated blocks: 0
Blocks with corrupt replicas: 0
Missing blocks: 0
```

The loopback NameNode port is the observation exception defined in SPEC-33.
All ingest commands in NET-04 and NET-05 use the profile-only runner on the
private Compose network, never host WebHDFS.
