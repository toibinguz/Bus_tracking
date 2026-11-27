"""Publish a validated, immutable Gold build through an atomic HDFS manifest switch."""

from uuid import uuid4


def publish_gold(spark, root, build_id, content):
    jvm = spark._jvm
    conf = spark._jsc.hadoopConfiguration()
    path = jvm.org.apache.hadoop.fs.Path
    fs = path(root).getFileSystem(conf)
    immutable = path(f"{root}/builds/{build_id}/manifest.json")
    stream = fs.create(immutable, False)
    try:
        stream.write(bytearray(content))
    finally:
        stream.close()

    temporary = path(f"{root}/.manifest-{uuid4().hex}")
    context = jvm.org.apache.hadoop.fs.FileContext.getFileContext(fs.getUri(), conf)
    options = spark.sparkContext._gateway.new_array(jvm.org.apache.hadoop.fs.Options.Rename, 1)
    options[0] = jvm.org.apache.hadoop.fs.Options.Rename.OVERWRITE
    try:
        stream = fs.create(temporary, False)
        try:
            stream.write(bytearray(content))
        finally:
            stream.close()
        context.rename(temporary, path(f"{root}/manifest.json"), options)
    finally:
        fs.delete(temporary, False)
