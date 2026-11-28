def spark_schema(fields):
    from pyspark.sql import types as T
    types = {"string": T.StringType, "int32": T.IntegerType, "int64": T.LongType,
             "float32": T.FloatType, "float64": T.DoubleType}
    return T.StructType([T.StructField(name, types[kind](), nullable) for name, kind, nullable in fields])
