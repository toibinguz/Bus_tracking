"""Thin CLI entrypoint for training causal-eta.v1 from Silver Parquet."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from module_3_bus_eta_prediction.step_3_3_machine_learning_models.silver_replay_trainer import main

if __name__ == "__main__":
    main()
