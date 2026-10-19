"""
Module 3: Bus ETA Prediction Engine
Subcomponent: step_3_3_machine_learning_models
File: train_eta_model.py

Trains and evaluates Gradient Boosted Trees (XGBoost Regressor) for predicting downstream Station ETA.
Computes evaluation metrics (MAE in seconds/minutes, RMSE, MAPE) against Ground Truth arrival times
and benchmarks performance against the Historical Segment Average baseline.
"""

import os
import sys
import json
import time
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, mean_squared_error
import xgboost as xgb

# Ensure project root in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))
sys.path.insert(0, os.path.abspath("."))

from module_3_bus_eta_prediction.step_3_2_feature_store_extractor.feature_extractor import extract_route_training_dataset


FEATURE_COLUMNS = [
    "direction_encoded",
    "next_station_order",
    "s_bus_m",
    "cross_track_m",
    "derived_speed_kmh",
    "is_dwell",
    "distance_remaining_m",
    "hour",
    "minute"
]
TARGET_COLUMN = "actual_remaining_sec"
MODEL_OUTPUT_DIR = "models"


def train_and_benchmark_route_eta(route_code: str = "02", db_path: str = "data/telemetry_audit_2026_10_17_18.db"):
    print("=" * 80)
    print(f"XGBOOST BUS ETA MODEL TRAINING & BENCHMARK FOR ROUTE {route_code}")
    print("=" * 80)

    # 1. Extract Training Data
    t0 = time.time()
    df = extract_route_training_dataset(route_code, db_path)
    if df.empty or len(df) < 50:
        print(f"Insufficient training samples for Route {route_code} (found {len(df)} samples).")
        return

    print(f"Dataset extracted: {len(df):,} supervised samples across Route {route_code}.")

    X = df[FEATURE_COLUMNS]
    y = df[TARGET_COLUMN]

    # 2. Train / Test Split (80% Train, 20% Holdout Test)
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.20, random_state=42)

    # 3. Baseline Model (Simple Physical Speed + Median Segment Time Benchmark)
    # Physical Baseline: distance / (average speed)
    avg_speed_mps = max(df["derived_speed_kmh"].median() / 3.6, 2.5)  # min 2.5 m/s (~9 km/h)
    baseline_preds = X_test["distance_remaining_m"] / avg_speed_mps
    baseline_mae = mean_absolute_error(y_test, baseline_preds)
    baseline_rmse = np.sqrt(mean_squared_error(y_test, baseline_preds))
    baseline_mape = np.mean(np.abs((y_test - baseline_preds) / np.maximum(y_test, 10.0))) * 100

    # 4. Train XGBoost Model
    print("Training XGBoost Regressor (n_estimators=100, max_depth=6, learning_rate=0.08)...")
    regressor = xgb.XGBRegressor(
        n_estimators=100,
        max_depth=6,
        learning_rate=0.08,
        subsample=0.85,
        colsample_bytree=0.85,
        random_state=42,
        n_jobs=-1
    )
    regressor.fit(X_train, y_train)

    # 5. Evaluate XGBoost on Holdout Test Set
    ml_preds = regressor.predict(X_test)
    ml_preds = np.maximum(ml_preds, 0.0)  # non-negative time

    ml_mae = mean_absolute_error(y_test, ml_preds)
    ml_rmse = np.sqrt(mean_squared_error(y_test, ml_preds))
    ml_mape = np.mean(np.abs((y_test - ml_preds) / np.maximum(y_test, 10.0))) * 100

    # Feature Importance
    importance = dict(zip(FEATURE_COLUMNS, regressor.feature_importances_))
    sorted_importance = sorted(importance.items(), key=lambda x: x[1], reverse=True)

    # 6. Save Model Artifact
    os.makedirs(MODEL_OUTPUT_DIR, exist_ok=True)
    model_path = os.path.join(MODEL_OUTPUT_DIR, f"xgboost_eta_route_{route_code}.json")
    regressor.save_model(model_path)

    elapsed = time.time() - t0

    # 7. Print Comprehensive Benchmark Report
    print("-" * 80)
    print("MODEL BENCHMARK RESULTS:")
    print(f"  * Holdout Test Samples : {len(y_test):,}")
    print(f"  * Baseline Model MAE   : {baseline_mae:.2f} seconds ({baseline_mae/60:.2f} minutes)")
    print(f"  * Baseline Model RMSE  : {baseline_rmse:.2f} seconds")
    print(f"  * Baseline Model MAPE  : {baseline_mape:.1f} %")
    print("-" * 40)
    print(f"  * XGBoost Model MAE    : {ml_mae:.2f} seconds ({ml_mae/60:.2f} minutes)")
    print(f"  * XGBoost Model RMSE   : {ml_rmse:.2f} seconds")
    print(f"  * XGBoost Model MAPE   : {ml_mape:.1f} %")
    print("-" * 40)
    improvement = ((baseline_mae - ml_mae) / baseline_mae) * 100
    print(f"  * MAE Accuracy Improvement: +{improvement:.2f} % over Baseline!")
    print(f"  * Saved Model File: {model_path}")

    print("\nFeature Importance Rankings:")
    for feat, imp in sorted_importance:
        bar = "#" * int(imp * 40)
        print(f"  - {feat:<22} : {imp*100:>5.2f}% {bar}")
    print("=" * 80)


if __name__ == "__main__":
    rc = sys.argv[1] if len(sys.argv) > 1 else "02"
    train_and_benchmark_route_eta(rc)
