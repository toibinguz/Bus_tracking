"""Independent Spark oracle: no project implementation imports."""
import json
import sys
from pyspark.sql import SparkSession

spark = SparkSession.builder.appName("P3A-independent-query").getOrCreate()
try:
    frame = spark.read.parquet(sys.argv[1])
    frame.createOrReplaceTempView("selected_hdfs_silver")
    result = spark.sql("SELECT count(*) AS ping_count, avg(derived_speed_kmh) AS avg_speed_kmh FROM selected_hdfs_silver WHERE route_code='08A'").first().asDict()
    assert result["ping_count"] == 4, result
    assert abs(result["avg_speed_kmh"] - 16.53) < 1e-9, result
    print("P3A_INDEPENDENT_SPARK=" + json.dumps(result, sort_keys=True), flush=True)
finally:
    spark.stop()
