"""
Module 3: Bus ETA Prediction Engine
Subcomponent: step_3_4_evaluation_and_benchmarking
File: benchmark_evaluator.py

Multi-Route Benchmark & Evaluation Suite.
Evaluates and benchmarks ETA accuracy across multiple bus routes simultaneously,
producing an empirical comparison table of Baseline vs Machine Learning (XGBoost).
"""

import os
import sys
import time
import pandas as pd
from typing import List

# Ensure project root in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))
sys.path.insert(0, os.path.abspath("."))

from module_3_bus_eta_prediction.step_3_3_machine_learning_models.train_eta_model import (
    train_and_benchmark_route_eta
)


def evaluate_routes_benchmark(route_codes: List[str]):
    print("=" * 80)
    print("MULTI-ROUTE ETA MODEL BENCHMARK & EVALUATION SUITE")
    print(f"Target Routes: {', '.join(route_codes)}")
    print("=" * 80)

    for rc in route_codes:
        print(f"\n>>> Running Evaluation for Route {rc}...")
        try:
            train_and_benchmark_route_eta(rc)
        except Exception as e:
            print(f"Error evaluating Route {rc}: {e}")

    print("\n" + "=" * 80)
    print("ALL ROUTE BENCHMARKS COMPLETED!")
    print("=" * 80)


if __name__ == "__main__":
    target_routes = sys.argv[1:] if len(sys.argv) > 1 else ["02", "32", "01"]
    evaluate_routes_benchmark(target_routes)
