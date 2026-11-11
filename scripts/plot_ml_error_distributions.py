"""
CLI Wrapper for SPEC-32: ML Model ETA Error Probability Distribution Visualizer & Quantile Auditor.
Strictly complies with AGENTS.md and docs/specs/32_ML_EVALUATION_ERROR_DISTRIBUTION_PLOTS_SPEC.md.
"""

import os
import sys

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, BASE_DIR)

from module_3_bus_eta_prediction.step_3_3_machine_learning_models.plot_eta_error_distributions import (
    run_ml_error_distribution_plots,
)

if __name__ == "__main__":
    result = run_ml_error_distribution_plots()
    sys.exit(0 if result.get("status") == "success" else 1)
