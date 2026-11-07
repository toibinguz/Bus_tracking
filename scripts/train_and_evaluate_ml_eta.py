"""
CLI Wrapper for Step 3.4: Train & Evaluate Multi-Route XGBoost ETA Models (TD-22).
"""

import os
import sys

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, BASE_DIR)

from module_3_bus_eta_prediction.step_3_3_machine_learning_models.eta_model_trainer import (
    run_step_3_4_ml_training_and_evaluation,
)

if __name__ == "__main__":
    run_step_3_4_ml_training_and_evaluation()
