"""
Scripts: Ingest Official TimBus Routes
Facade CLI to extract official stations and shapes from TRAMOC / TimBus with full lineage.
"""

import argparse
import json
import logging
import os
import sys

from config.system_config import get_database_path, DEFAULT_DB_PATH

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from module_1_data_ingestion_and_preprocessing.step_1_2_timbus_master_ground_truth.timbus_pipeline import (
    TimBusGroundTruthPipeline
)

sys.stdout.reconfigure(encoding="utf-8")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def main():
    parser = argparse.ArgumentParser(description="Ingest official ground truth from TimBus (TRAMOC / Transerco)")
    parser.add_argument("--fid", type=str, default="2", help="Route fleet ID to ingest (default: 2)")
    parser.add_argument("--db-path", type=str, default=DEFAULT_DB_PATH, help="Target SQLite DB")
    parser.add_argument("--raw-dir", type=str, default="data/ground_truth/timbus_official/raw", help="Raw JSON storage dir")
    args = parser.parse_args()

    pipeline = TimBusGroundTruthPipeline(db_path=args.db_path, raw_storage_dir=args.raw_dir)
    print(f"[*] Bat dau ingest du lieu chinh thuc tu TimBus (Fleet ID: {args.fid})...")
    
    result = pipeline.process_route(args.fid)
    print("\n" + "=" * 60)
    print("KET QUA INGESTION VA TRACEABILITY (TRAMOC / TIMBUS)")
    print("=" * 60)
    for k, v in result.items():
        print(f"  {k:<30}: {v}")
    print("=" * 60)
    print("[SUCCESS] Da luu vao DB va tao log kiem toan du lieu thanh cong!")


if __name__ == "__main__":
    main()
