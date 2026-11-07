"""
CLI Entry Point: Build Leak-Free Historical Baseline Travel Time Matrix (Module 3 - Step 3.1)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from module_3_bus_eta_prediction.step_3_1_historical_baseline_model.baseline_matrix_builder import (
    build_and_evaluate_baseline_matrix,
)

if __name__ == "__main__":
    build_and_evaluate_baseline_matrix()
