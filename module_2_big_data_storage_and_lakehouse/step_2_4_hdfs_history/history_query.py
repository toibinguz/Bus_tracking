"""Read published P2 Silver runs for bounded historical route-speed queries."""

from datetime import date, datetime, timedelta, timezone
import json
import re


ROOT = "hdfs://namenode:8020/bus-eta/v1"
PUBLISHED = ROOT + "/_published/bronze_to_silver"


def validate_request(route_code, date_from, date_to):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,16}", route_code or ""):
        raise ValueError("invalid route_code")
    try:
        start = date.fromisoformat(date_from)
        end = date.fromisoformat(date_to)
    except (TypeError, ValueError):
        raise ValueError("invalid date") from None
    if end < start or end - start >= timedelta(days=31):
        raise ValueError("date range must be between 1 and 31 days")
    return start, end


def validate_snapshot_id(snapshot_id):
    if not re.fullmatch(r'[0-9a-f]{64}', snapshot_id or ''):
        raise ValueError('invalid snapshot_id')


def load_history_snapshot(spark, snapshot_id):
    """Only publication manifests grant visibility; _runs alone is never read."""
    validate_snapshot_id(snapshot_id)
    def read(path):
        return bytes(spark.read.format('binaryFile').load(path).first().content)
    raw = read(ROOT+'/_published/history_snapshots/'+snapshot_id+'.json')
    manifest = json.loads(raw)
    prefix = ROOT+'/silver/history/_runs/snapshot='+snapshot_id+'/attempt='
    if manifest['snapshot_id'] != snapshot_id or not manifest['snapshot_path'].startswith(prefix):
        raise ValueError('invalid published snapshot path or identity')
    if manifest['silver_path'] != manifest['snapshot_path']+'/route_projected_telemetry':
        raise ValueError('invalid published Silver path')
    if read(manifest['snapshot_path']+'/snapshot.json') != raw:
        raise ValueError('publication does not match completed snapshot')
    return manifest


def query_snapshot_speed(spark, snapshot_id, route_code, date_from, date_to):
    from pyspark.sql import functions as F
    start, end = validate_request(route_code,date_from,date_to)
    manifest = load_history_snapshot(spark,snapshot_id)
    frame = spark.read.parquet(manifest['silver_path'])
    result = (frame.where((F.col('route_code')==F.lit(route_code)) & F.col('dt').between(start.isoformat(),end.isoformat()))
              .groupBy('dt').agg(F.count(F.lit(1)).alias('ping_count'),F.count('derived_speed_kmh').alias('speed_sample_count'),F.avg('derived_speed_kmh').alias('avg_speed_kmh')).orderBy('dt').collect())
    rows = [dict(row.asDict(),dt=str(row['dt'])) for row in result]
    return dict(route_code=route_code,date_from=date_from,date_to=date_to,rows=rows,storage='hdfs-silver',provenance='observed',snapshot_id=snapshot_id)


def query_route_speed(spark, route_code, date_from, date_to):
    """Read only published Silver paths; never interpret client input as SQL."""
    from pyspark.sql import functions as F

    start, end = validate_request(route_code, date_from, date_to)
    jvm = spark.sparkContext._jvm
    fs = jvm.org.apache.hadoop.fs.FileSystem.get(spark.sparkContext._jsc.hadoopConfiguration())
    published = jvm.org.apache.hadoop.fs.Path(PUBLISHED)
    if not fs.exists(published):
        raise RuntimeError("published manifest directory unavailable")
    paths = {}
    windows = {}
    for status in fs.listStatus(published):
        path = str(status.getPath().toString())
        if not status.isFile() or not path.endswith(".json"):
            continue
        manifest = json.loads(bytes(spark.read.format("binaryFile").load(path).first().content).decode("utf-8"))
        checkpoint_path = manifest["checkpoint_path"]
        if not checkpoint_path.startswith(ROOT + "/_checkpoints/bronze_to_silver/"):
            raise ValueError("invalid checkpoint path")
        checkpoint = json.loads(bytes(spark.read.format("binaryFile").load(checkpoint_path).first().content).decode("utf-8"))
        if checkpoint["job_key"] != manifest["job_key"]:
            raise ValueError("manifest checkpoint mismatch")
        silver = checkpoint["silver_path"]
        if not silver.startswith(ROOT + "/silver/route_projected_telemetry/"):
            raise ValueError("invalid Silver path")
        match = re.search(r"/dt=(\d{4}-\d{2}-\d{2})/", silver)
        if not match:
            raise ValueError("missing Silver partition date")
        day = date.fromisoformat(match.group(1))
        if start <= day <= end:
            window = checkpoint["source_window_id"]
            if window in windows and windows[window] != checkpoint["job_key"]:
                raise ValueError("multiple published runs for source window")
            windows[window] = checkpoint["job_key"]
            paths[silver] = day.isoformat()
    frames = [spark.read.parquet(path).select("route_code", "derived_speed_kmh").withColumn("dt", F.lit(day)) for path, day in paths.items()]
    rows = []
    if frames:
        combined = frames[0]
        for frame in frames[1:]:
            combined = combined.unionByName(frame)
        result = (combined.where(F.col("route_code") == F.lit(route_code))
                  .groupBy("dt").agg(F.count(F.lit(1)).alias("ping_count"), F.avg("derived_speed_kmh").alias("avg_speed_kmh"))
                  .orderBy("dt").collect())
        rows = [row.asDict() for row in result]
    return {"route_code": route_code, "date_from": date_from, "date_to": date_to,
            "rows": rows, "storage": "hdfs-silver", "generated_at": datetime.now(timezone.utc).isoformat()}
