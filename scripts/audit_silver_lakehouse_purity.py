"""
CLI Entry Point: Independent Quality & Purity Audit of Silver Parquet Lakehouse (Module 2 - Step 2.2)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from module_2_big_data_storage_and_lakehouse.step_2_2_parquet_medallion_lakehouse.silver_lakehouse_auditor import (
    audit_silver,
)

if __name__ == "__main__":
    audit_silver()
