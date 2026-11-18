"""
CLI Entrypoint for Module 3 - Step 3.3: Unified Gold Feature Store Extractor
"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

if __name__ == "__main__":
    import argparse
    from module_3_bus_eta_prediction.step_3_2_feature_store_extractor import feature_store_builder as builder
    parser=argparse.ArgumentParser(description='Build features into a fresh output; existing evidence is never deleted')
    parser.add_argument('--output',required=True)
    parser.add_argument('--database',default=builder.DB_PATH)
    parser.add_argument('--silver',default=builder.SILVER_TEL_DIR)
    parser.add_argument('--incidents',default=builder.SILVER_INC_DIR)
    parser.add_argument('--workers',type=int,default=2)
    args=parser.parse_args()
    builder.DB_PATH=args.database;builder.SILVER_TEL_DIR=args.silver
    builder.SILVER_INC_DIR=args.incidents;builder.GOLD_FEATURE_DIR=args.output
    builder.build_gold_feature_store(max_workers=args.workers)
