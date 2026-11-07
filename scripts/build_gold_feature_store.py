"""
CLI Entrypoint for Module 3 - Step 3.3: Unified Gold Feature Store Extractor
"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from module_3_bus_eta_prediction.step_3_2_feature_store_extractor.feature_store_builder import (
    build_gold_feature_store,
)

if __name__ == "__main__":
    build_gold_feature_store()
