"""
Module 3: Bus ETA Prediction Engine
Subcomponent: step_3_3_machine_learning_models
File: train_eta_model.py

Trains and evaluates XGBoost Point & Interval (Conformalized Quantile Regression P10/P50/P90)
ETA Prediction Models using a strict Trip-Based Temporal Holdout Split (0% ping leakage).

Benchmarks 3 tiers on both Point Metrics (MAE, MdAE, RMSE, MAPE, Hit@60s) and
Interval Metrics (PICP Coverage %, MPIW Interval Width, Winkler Interval Score, Pinball Loss):
  1. Naive Kinematic Speed Baseline (distance / median speed)
  2. Module 3.1 Historical Matrix Baseline (baseline_median_sec & [baseline_p10, baseline_p90])
  3. Module 3.3 XGBoost Point & Quantile Interval Models
"""

import json
import os
import sys
import time
from typing import Dict, Optional

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import mean_absolute_error, mean_pinball_loss, mean_squared_error

# Ensure project root in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))
sys.path.insert(0, os.path.abspath("."))

from config.system_config import get_database_path
from module_3_bus_eta_prediction.step_3_2_feature_store_extractor.feature_extractor import (
    FEATURE_COLUMNS,
    TARGET_COLUMN,
    extract_route_training_dataset,
)

MODEL_OUTPUT_DIR = "models"


def compute_interval_metrics(
    y_true: np.ndarray,
    y_low: np.ndarray,
    y_med: np.ndarray,
    y_high: np.ndarray,
    alpha: float = 0.20,
) -> Dict[str, float]:
    """
    Compute rigorous evaluation metrics for both Point and Interval ETA predictions.
    For an (1 - alpha) = 80% interval [P10, P90], alpha = 0.20.
    """
    y_true = np.asarray(y_true, dtype=float)
    y_low = np.maximum(0.0, np.asarray(y_low, dtype=float))
    y_med = np.maximum(y_low, np.asarray(y_med, dtype=float))
    y_high = np.maximum(y_med, np.asarray(y_high, dtype=float))

    abs_err = np.abs(y_true - y_med)
    mae = float(np.mean(abs_err))
    mdae = float(np.median(abs_err))
    rmse = float(np.sqrt(np.mean((y_true - y_med) ** 2)))
    mape = float(np.mean(abs_err / np.maximum(y_true, 30.0)) * 100.0)

    hit_30s = float(np.mean(abs_err <= 30.0) * 100.0)
    hit_60s = float(np.mean(abs_err <= 60.0) * 100.0)
    hit_90s = float(np.mean(abs_err <= 90.0) * 100.0)

    # Interval metrics
    in_bounds = (y_true >= y_low) & (y_true <= y_high)
    picp = float(np.mean(in_bounds) * 100.0)
    widths = y_high - y_low
    mpiw = float(np.mean(widths))
    median_width = float(np.median(widths))

    # Winkler / Interval Score (penalizes width + 2/alpha * out-of-bound distance)
    below_pen = (2.0 / alpha) * np.maximum(0.0, y_low - y_true)
    above_pen = (2.0 / alpha) * np.maximum(0.0, y_true - y_high)
    winkler_score = float(np.mean(widths + below_pen + above_pen))

    # Pinball loss across (0.10, 0.50, 0.90)
    pb_10 = float(mean_pinball_loss(y_true, y_low, alpha=0.10))
    pb_50 = float(mean_pinball_loss(y_true, y_med, alpha=0.50))
    pb_90 = float(mean_pinball_loss(y_true, y_high, alpha=0.90))
    mean_pinball = (pb_10 + pb_50 + pb_90) / 3.0

    # Operational risk rates
    missed_bus_rate = float(np.mean(y_true < y_low) * 100.0)
    late_exceed_rate = float(np.mean(y_true > y_high) * 100.0)

    return {
        "mae_sec": round(mae, 2),
        "mdae_sec": round(mdae, 2),
        "rmse_sec": round(rmse, 2),
        "mape_pct": round(mape, 2),
        "hit_30s_pct": round(hit_30s, 2),
        "hit_60s_pct": round(hit_60s, 2),
        "hit_90s_pct": round(hit_90s, 2),
        "picp_coverage_pct": round(picp, 2),
        "mpiw_width_sec": round(mpiw, 2),
        "median_width_sec": round(median_width, 2),
        "winkler_score_sec": round(winkler_score, 2),
        "pinball_loss_sec": round(mean_pinball, 2),
        "missed_bus_risk_pct": round(missed_bus_rate, 2),
        "late_exceed_risk_pct": round(late_exceed_rate, 2),
    }


def train_and_benchmark_route_eta(
    route_code: str = "02",
    db_path: Optional[str] = None,
    max_stops_ahead: int = 5,
    max_horizon_m: float = 3500.0,
) -> Optional[Dict[str, object]]:
    resolved_db = db_path or str(get_database_path())
    print("=" * 88)
    print(
        f"POINT & INTERVAL (P10/P50/P90) ETA MODEL TRAINING & BENCHMARK — ROUTE {route_code}"
    )
    print("=" * 88)

    t0 = time.time()
    df = extract_route_training_dataset(
        route_code,
        db_path=resolved_db,
        max_stops_ahead=max_stops_ahead,
        max_horizon_m=max_horizon_m,
    )
    if df.empty or len(df) < 100:
        print(
            f"Insufficient training samples for Route {route_code} (found {len(df)} samples)."
        )
        return None

    # Strict Trip-Level Temporal Split:
    # First 70% trips -> Train, Next 10% trips -> Conformal Calibration, Last 20% trips -> Unseen Test
    unique_trips = df["trip_id"].unique()
    n_trips = len(unique_trips)
    n_train = max(1, int(n_trips * 0.70))
    n_cal = max(1, int(n_trips * 0.80))

    train_trips = set(unique_trips[:n_train])
    cal_trips = set(unique_trips[n_train:n_cal])
    test_trips = set(unique_trips[n_cal:])

    train_df = df[df["trip_id"].isin(train_trips)]
    cal_df = df[df["trip_id"].isin(cal_trips)]
    test_df = df[df["trip_id"].isin(test_trips)]

    print(
        f"Dataset extracted in {time.time() - t0:.2f}s: {len(df):,} samples across {n_trips:,} independent trips."
    )
    print(
        f"Strict Trip Split -> Train: {len(train_df):,} ({len(train_trips)} trips) | "
        f"Calib: {len(cal_df):,} ({len(cal_trips)} trips) | "
        f"Unseen Test: {len(test_df):,} ({len(test_trips)} trips)"
    )

    X_train = train_df[FEATURE_COLUMNS]
    y_train = train_df[TARGET_COLUMN].to_numpy()

    X_cal = cal_df[FEATURE_COLUMNS]
    y_cal = cal_df[TARGET_COLUMN].to_numpy()

    X_test = test_df[FEATURE_COLUMNS]
    y_test = test_df[TARGET_COLUMN].to_numpy()

    # -------------------------------------------------------------------------
    # TIER 1 BENCHMARK: Naive Physical Speed Baseline (distance / median speed)
    # -------------------------------------------------------------------------
    avg_speed_mps = max(float(train_df["derived_speed_kmh"].median()) / 3.6, 3.5)
    naive_med = X_test["distance_remaining_m"].to_numpy() / avg_speed_mps
    naive_low = naive_med * 0.70
    naive_high = naive_med * 1.40
    naive_metrics = compute_interval_metrics(y_test, naive_low, naive_med, naive_high)

    # -------------------------------------------------------------------------
    # TIER 2 BENCHMARK: Module 3.1 Historical Segment Matrix Baseline
    # -------------------------------------------------------------------------
    m31_med = test_df["baseline_median_sec"].to_numpy()
    m31_low = test_df["baseline_p10_sec"].to_numpy()
    m31_high = test_df["baseline_p90_sec"].to_numpy()
    m31_metrics = compute_interval_metrics(y_test, m31_low, m31_med, m31_high)

    # -------------------------------------------------------------------------
    # TIER 3 MODEL: Residual XGBoost Multi-Quantile Regressor (P10, P50, P90)
    # Instead of wasting 90% of tree splits re-learning the linear identity y ~ baseline_median_sec,
    # predict the live kinematic residual: r = actual_remaining_sec - baseline_median_sec
    # -------------------------------------------------------------------------
    print(
        "Training Residual XGBoost Quantile Interval & Point Model (q = [0.10, 0.50, 0.90])..."
    )
    base_train = X_train["baseline_median_sec"].to_numpy()
    base_cal = X_cal["baseline_median_sec"].to_numpy()
    base_test = X_test["baseline_median_sec"].to_numpy()

    r_train = y_train - base_train

    quantiles = np.array([0.10, 0.50, 0.90])
    q_model = xgb.XGBRegressor(
        objective="reg:quantileerror",
        quantile_alpha=quantiles,
        tree_method="hist",
        n_estimators=160,
        max_depth=6,
        learning_rate=0.06,
        subsample=0.85,
        colsample_bytree=0.85,
        min_child_weight=20,
        random_state=42,
        n_jobs=6,
    )
    q_model.fit(X_train, r_train)

    # Heteroscedastic Conformalized Quantile Regression (Scaled CQR) on calibration trips
    cal_res = q_model.predict(X_cal)
    cal_p10 = np.maximum(0.0, base_cal + cal_res[:, 0])
    cal_p50 = np.maximum(cal_p10, base_cal + cal_res[:, 1])
    cal_p90 = np.maximum(cal_p50, base_cal + cal_res[:, 2])

    cal_scale = np.maximum(15.0, X_cal["baseline_spread_sec"].to_numpy())
    scaled_scores = np.maximum(cal_p10 - y_cal, y_cal - cal_p90) / cal_scale
    q_conformal_scale = float(np.quantile(scaled_scores, 0.80))

    # Predict on Unseen Test Trips
    test_res = q_model.predict(X_test)
    ml_low_raw = np.maximum(0.0, base_test + test_res[:, 0])
    ml_med = np.maximum(0.0, base_test + test_res[:, 1])
    ml_high_raw = np.maximum(ml_med, base_test + test_res[:, 2])

    # Apply Heteroscedastic Conformal Calibration adjustment
    test_scale = np.maximum(15.0, X_test["baseline_spread_sec"].to_numpy())
    ml_low = np.maximum(0.0, ml_low_raw - q_conformal_scale * test_scale)
    ml_high = np.maximum(ml_med, ml_high_raw + q_conformal_scale * test_scale)
    q_conformal = q_conformal_scale

    ml_metrics = compute_interval_metrics(y_test, ml_low, ml_med, ml_high)

    # Also compute single-stop (immediate next station: stops_ahead == 1) test metrics
    mask_stop1 = (X_test["stops_ahead"].to_numpy() == 1)
    stop1_metrics = compute_interval_metrics(
        y_test[mask_stop1], ml_low[mask_stop1], ml_med[mask_stop1], ml_high[mask_stop1]
    )
    m31_stop1_metrics = compute_interval_metrics(
        y_test[mask_stop1], m31_low[mask_stop1], m31_med[mask_stop1], m31_high[mask_stop1]
    )

    # Feature Importance
    importance = dict(zip(FEATURE_COLUMNS, q_model.feature_importances_))
    sorted_importance = sorted(importance.items(), key=lambda x: x[1], reverse=True)

    # Save Model Artifact
    os.makedirs(MODEL_OUTPUT_DIR, exist_ok=True)
    model_path = os.path.join(MODEL_OUTPUT_DIR, f"xgboost_eta_route_{route_code}.json")
    q_model.save_model(model_path)

    # Print Comparative Benchmark Table
    print("-" * 88)
    print(f"1. MULTI-STOP HORIZON BENCHMARK (1 to {max_stops_ahead} stops ahead, up to {max_horizon_m:.0f}m):")
    print(f"   Unseen Test Samples: {len(y_test):,} across {len(test_trips)} independent trips")
    print("-" * 88)
    print(
        f"{'Metric':<30} | {'Naive Speed':>14} | {'Mod 3.1 Matrix':>14} | {'Mod 3.3 XGB-CQR':>15}"
    )
    print("-" * 88)
    print(
        f"{'Point MAE (sec / min)':<30} | {naive_metrics['mae_sec']:>7.1f}s ({naive_metrics['mae_sec']/60:.1f}m) | "
        f"{m31_metrics['mae_sec']:>7.1f}s ({m31_metrics['mae_sec']/60:.1f}m) | "
        f"{ml_metrics['mae_sec']:>8.1f}s ({ml_metrics['mae_sec']/60:.1f}m)"
    )
    print(
        f"{'Point Median Error MdAE (sec)':<30} | {naive_metrics['mdae_sec']:>13.1f}s | "
        f"{m31_metrics['mdae_sec']:>13.1f}s | {ml_metrics['mdae_sec']:>14.1f}s"
    )
    print(
        f"{'Point RMSE (sec)':<30} | {naive_metrics['rmse_sec']:>13.1f}s | "
        f"{m31_metrics['rmse_sec']:>13.1f}s | {ml_metrics['rmse_sec']:>14.1f}s"
    )
    print(
        f"{'Hit Rate within +/- 60s (%)':<30} | {naive_metrics['hit_60s_pct']:>13.1f}% | "
        f"{m31_metrics['hit_60s_pct']:>13.1f}% | {ml_metrics['hit_60s_pct']:>14.1f}%"
    )
    print(
        f"{'Hit Rate within +/- 90s (%)':<30} | {naive_metrics['hit_90s_pct']:>13.1f}% | "
        f"{m31_metrics['hit_90s_pct']:>13.1f}% | {ml_metrics['hit_90s_pct']:>14.1f}%"
    )
    print("-" * 88)
    print(
        f"{'Interval Coverage PICP [80%]':<30} | {naive_metrics['picp_coverage_pct']:>13.1f}% | "
        f"{m31_metrics['picp_coverage_pct']:>13.1f}% | {ml_metrics['picp_coverage_pct']:>14.1f}%"
    )
    print(
        f"{'Mean Interval Width MPIW (s)':<30} | {naive_metrics['mpiw_width_sec']:>7.1f}s ({naive_metrics['mpiw_width_sec']/60:.1f}m) | "
        f"{m31_metrics['mpiw_width_sec']:>7.1f}s ({m31_metrics['mpiw_width_sec']/60:.1f}m) | "
        f"{ml_metrics['mpiw_width_sec']:>8.1f}s ({ml_metrics['mpiw_width_sec']/60:.1f}m)"
    )
    print(
        f"{'Winkler Interval Score (lower=better)':<30} | {naive_metrics['winkler_score_sec']:>13.1f}s | "
        f"{m31_metrics['winkler_score_sec']:>13.1f}s | {ml_metrics['winkler_score_sec']:>14.1f}s"
    )
    print(
        f"{'Pinball Quantile Loss (sec)':<30} | {naive_metrics['pinball_loss_sec']:>13.2f}s | "
        f"{m31_metrics['pinball_loss_sec']:>13.2f}s | {ml_metrics['pinball_loss_sec']:>14.2f}s"
    )
    print(
        f"{'Missed Bus Risk (y < P10) (%)':<30} | {naive_metrics['missed_bus_risk_pct']:>13.1f}% | "
        f"{m31_metrics['missed_bus_risk_pct']:>13.1f}% | {ml_metrics['missed_bus_risk_pct']:>14.1f}%"
    )
    print("-" * 88)
    print(
        f"2. IMMEDIATE NEXT STATION BENCHMARK (stops_ahead == 1, N={ int(np.sum(mask_stop1)) :,}):"
    )
    print(
        f"   * Module 3.1 Baseline -> MAE: {m31_stop1_metrics['mae_sec']:.2f}s | Hit@60s: {m31_stop1_metrics['hit_60s_pct']:.1f}% | "
        f"PICP: {m31_stop1_metrics['picp_coverage_pct']:.1f}% | MPIW: {m31_stop1_metrics['mpiw_width_sec']:.1f}s"
    )
    print(
        f"   * Module 3.3 XGB-CQR  -> MAE: {stop1_metrics['mae_sec']:.2f}s | Hit@60s: {stop1_metrics['hit_60s_pct']:.1f}% | "
        f"PICP: {stop1_metrics['picp_coverage_pct']:.1f}% | MPIW: {stop1_metrics['mpiw_width_sec']:.1f}s | "
        f"Winkler: {stop1_metrics['winkler_score_sec']:.1f}s"
    )
    print("-" * 88)
    print("Top 10 Feature Importance Rankings:")
    for feat, imp in sorted_importance[:10]:
        bar = "#" * int(float(imp) * 50)
        print(f"  - {feat:<26} : {float(imp)*100:>6.2f}% {bar}")
    print("=" * 88)

    return {
        "route_code": route_code,
        "n_samples": len(df),
        "n_trips": n_trips,
        "naive": naive_metrics,
        "m31_baseline": m31_metrics,
        "ml_xgb_cqr": ml_metrics,
        "stop1_ml": stop1_metrics,
        "stop1_m31": m31_stop1_metrics,
        "conformal_offset_sec": round(q_conformal, 2),
        "feature_importance": {k: round(float(v), 4) for k, v in sorted_importance},
    }


if __name__ == "__main__":
    rc = sys.argv[1] if len(sys.argv) > 1 else "02"
    train_and_benchmark_route_eta(rc)
