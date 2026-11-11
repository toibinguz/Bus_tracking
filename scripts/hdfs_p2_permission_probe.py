"""Exercise the narrow SPEC-37 HDFS permission boundary as Spark user."""

from __future__ import annotations

import json


HDFS_ROOT = "/bus-eta/v1"
SPARK_WRITABLE_ROOTS = (
    f"{HDFS_ROOT}/silver",
    f"{HDFS_ROOT}/gold",
    f"{HDFS_ROOT}/_checkpoints/bronze_to_silver",
    f"{HDFS_ROOT}/_published/bronze_to_silver",
)
ROOT_WRITABLE_ROOTS = (f"{HDFS_ROOT}/bronze", f"{HDFS_ROOT}/reference")
PROBE_NAME = "permission-probe-p2"


def main() -> None:
    from pyspark.sql import SparkSession

    spark = SparkSession.builder.appName("bus-eta-hdfs-p2-permission-probe").getOrCreate()
    try:
        jvm = spark.sparkContext._jvm
        filesystem = jvm.org.apache.hadoop.fs.FileSystem.get(spark.sparkContext._jsc.hadoopConfiguration())
        path_type = jvm.org.apache.hadoop.fs.Path
        success_roots = []
        for root in SPARK_WRITABLE_ROOTS:
            path = path_type(f"{root}/{PROBE_NAME}")
            if filesystem.exists(path):
                raise RuntimeError(f"probe path unexpectedly exists: {path}")
            stream = filesystem.create(path, False)
            try:
                stream.write(bytearray(b"p2-permission-probe\n"))
            finally:
                stream.close()
            if spark.read.text(str(path)).collect()[0]["value"] != "p2-permission-probe":
                raise RuntimeError(f"Spark could not read its own HDFS probe: {path}")
            if not filesystem.delete(path, False):
                raise RuntimeError(f"Spark could not delete its own HDFS probe: {path}")
            success_roots.append(root)
        denied_roots = []
        for root in ROOT_WRITABLE_ROOTS:
            path = path_type(f"{root}/{PROBE_NAME}")
            try:
                stream = filesystem.create(path, False)
                stream.close()
            except Exception:
                denied_roots.append(root)
            else:
                filesystem.delete(path, False)
                raise RuntimeError(f"Spark unexpectedly wrote root-owned location: {root}")
        print(json.dumps({"denied_roots": denied_roots, "spark_writable_roots": success_roots}, sort_keys=True))
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
