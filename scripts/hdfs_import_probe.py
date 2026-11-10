"""Verify the HDFS runtime import boundary inside the Spark container."""

import sys

import module_2_big_data_storage_and_lakehouse.step_2_4_hdfs_history.webhdfs  # noqa: F401


LEGACY_MODULES = {
    "module_2_big_data_storage_and_lakehouse.step_2_1_sqlite_operational_store.db_manager",
    "module_2_big_data_storage_and_lakehouse.step_2_2_parquet_medallion_lakehouse.lakehouse_exporter",
    "module_2_big_data_storage_and_lakehouse.step_2_2_parquet_medallion_lakehouse.silver_lakehouse_auditor",
}


if "pandas" in sys.modules or LEGACY_MODULES.intersection(sys.modules):
    raise SystemExit("HDFS import boundary violated")

print("IM-03 pass")
