# P2 Spark/HDFS evidence

This directory records the bounded SPEC-35 P2 run. All telemetry inputs and
outputs below are `hdfs://namenode:8020/...`; no local telemetry mirror was
used by Spark.

## Runtime and permissions

- Dockerfile SHA-256: `7a8d36490420ea44299730f38ffdb79bf19083d93176042c2b76e0010f124485`.
- Base image: `apache/spark:3.5.4`; Python `3.8.10`; NumPy `1.24.4`.
- Spark master image digest: `sha256:479bf5e6ba9c68e54c7653b5ca6c08b0d9b4ef63a0884634c49e7894caef82f9`.
- `hdfs_p2_projection_probe.py` printed `DEP-03 projection-import=ok`.
- `hdfs_p2_provision_namespace.sh` provisioned root-owned Bronze/reference
  and Spark-owned Silver/Gold/checkpoint/publish roots with mode `755`.
- The `hdfs_p2_permission_probe.py` Spark application ran as `spark`, wrote,
  read and deleted an own child below every Spark-owned root, and was denied
  below Bronze and reference.

## Final P2 run

The accepted source revision produced job key
`d1d92e7be6a3fd9e9d5345871605bab93d5370c6ff7af3ad07dff263e247a173`.
The immutable checkpoint is:

```text
hdfs://namenode:8020/bus-eta/v1/_checkpoints/bronze_to_silver/d1d92e7be6a3fd9e9d5345871605bab93d5370c6ff7af3ad07dff263e247a173.json
```

It records 5 raw rows, one duplicate identity, 4 distinct/accepted Silver
rows, and Gold aggregate `08A, ping_count=4, speed_sample_count=3,
avg_speed_kmh=16.53`. The independent `spark-sql` command in
`scripts/hdfs_p2_gold_validation.sql` returned the same aggregate from Silver.
An unchanged second `spark-submit` printed `p2_checkpoint_noop` for the same
job key and created no second final run.

The earlier `051586...` HDFS run used a prior source revision that stored
relative output paths. It is retained as an immutable pre-acceptance run; the
final `d1d92...` checkpoint is the only run used by this evidence.
