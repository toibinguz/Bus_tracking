"""
CLI Entry Point: Bulk Ingestion of Raw Bus Telemetry into SQLite (Module 1 - Step 1.3)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from module_1_data_ingestion_and_preprocessing.step_1_3_telemetry_kinematic_sanitizer.bulk_ping_ingester import (
    main,
)

if __name__ == "__main__":
    main()
