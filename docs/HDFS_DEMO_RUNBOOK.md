# HDFS academic simulation runbook

This cluster is a reproducible teaching experiment, not a 24/7 deployment.
It must use HDFS and Spark directly; a local-directory replacement is invalid.

## Start and verify

With Docker Desktop running in Linux-container mode:

```powershell
.\scripts\hdfs_demo.ps1 up
.\scripts\hdfs_demo.ps1 health
```

`health` passes only when HDFS reports two live DataNodes. The NameNode UI and
WebHDFS are exposed only on `127.0.0.1:9870`; DataNode ports are private.

## Required P1 evidence

1. Capture or replay one real crawler-shaped source window.
2. Use `hdfs_bronze_adapter` to create envelopes and `spool.write_closed_window`.
3. Upload its closed JSONL via `WebHdfsUploader` to `/bus-eta/v1/bronze/telemetry`.
4. Record the source-window ID, row count, local SHA-256, and `hdfs fsck` output.

Do not mark P1 complete until the HDFS runtime commands have succeeded. Docker
volumes are retained by `down`; remove them only for an intentional fresh demo.
