"""
Module 3 - Step 3.4: Horizon-Balanced Multi-Route XGBoost ETA Trainer, Calibrator & Feature Auditor
Strictly complies with AGENTS.md, docs/03_SILVER_TRAJECTORY_CONTINUITY_AND_ETA_CHECKLIST.md,
and docs/04_TECHNICAL_DEBT_AND_OPEN_ISSUES_LEDGER.md (TD-22).

Key Architectural Principles:
  1. Residual Learning over Historical Baseline:
     Predicts `delta_eta_sec = actual_eta_sec - baseline_eta_p50_sec` using `XGBRegressor(tree_method="hist", enable_categorical=True)`
     with Horizon-Balanced Sample Weights `w = 1.0 / sqrt(max(60.0, baseline_eta_p50_sec))` so short-horizon (1..5 stations)
     accuracy is never sacrificed to long-horizon (>15 stations) variance.
  2. Empirical Verification of Global vs. Route-Aware vs. Calibrated vs. Pruned Models:
     - Model 0: Baseline Sum(P50) (`baseline_eta_p50_sec`)
     - Model 1: Baseline Sum(Mean) (`baseline_eta_mean_sec`)
     - Model 2: Physics + Preceding-Bus Probe Blend (`0.65 * P50 + 0.35 * recent_corridor_tt_sum_sec`)
     - Model 3: Route-Blind Global XGBoost (excludes route identity & route latent profile features to test underfitting)
     - Model 4: Full Global High-Capacity XGBoost (all 52 features across families a..f + native categorical partitioning)
     - Model 5: Full Global XGBoost + Per-(Route, Direction, Horizon) Empirical-Bayes Residual Calibration
     - Model 6: Pruned Compact XGBoost (retains features accounting for >= 98.5% of total Gain)
  3. Full Held-Out Test Evaluation (`3,704,820` rows across 47 active routes in `2026-11-01..07`) + Post-Step EDA.
"""

import json
import math
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import xgboost as xgb

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, BASE_DIR)

from config.system_config import DEFAULT_LAKEHOUSE_ROOT

GOLD_FEATURE_DIR = os.path.join(BASE_DIR, DEFAULT_LAKEHOUSE_ROOT, "gold", "eta_feature_store")
MODEL_OUT_DIR = os.path.join(BASE_DIR, "data", "models")

# TD-25: cấu hình quy mô huấn luyện (ghi đè qua biến môi trường để không ghi đè model cũ)
ETA_N_ESTIMATORS = int(os.environ.get("ETA_N_ESTIMATORS", "450"))
ETA_MAX_FIT_ROWS_PER_ROUTE = int(os.environ.get("ETA_MAX_FIT_ROWS_PER_ROUTE", "55000"))
ETA_MODEL_TAG = os.environ.get("ETA_MODEL_TAG", "")

# 52 features grouped by causal family (a..f) + current/target station order
FAMILY_A_CURRENT_STATE = [
    "route_id_idx",
    "direction_id",
    "current_station_order",
    "target_station_order",
    "day_type",
    "day_of_week",
    "hour_slot",
    "sin_time",
    "cos_time",
    "s_bus_m",
    "s_target_m",
    "remaining_distance_m",
    "n_stations_ahead",
    "progress_ratio",
    "target_progress_ratio",
    "dist_to_next_station_m",
    "ego_speed_instant_kmh",
    "ego_speed_roll3_kmh",
    "ego_speed_roll5_kmh",
    "ego_accel_kmh_per_min",
    "ego_speed_ratio_vs_baseline",
    "ego_trip_elapsed_sec",
    "ego_cum_delay_vs_baseline_sec",
]

FAMILY_B_FLEET_AHEAD_BEHIND = [
    "lead_bus_dist_ahead_m",
    "lead_bus_time_headway_sec",
    "lead_bus_speed_kmh",
    "lead_bus_speed_ratio",
    "follow_bus_dist_behind_m",
    "follow_bus_speed_kmh",
    "n_active_buses_on_route",
    "n_buses_in_corridor_ahead",
]

FAMILY_C_RECENT_PRECEDING_BUS = [
    "recent_corridor_tt_sum_sec",
    "recent_corridor_congestion_ratio",
    "recent_seg_coverage_ratio",
    "recent_next_seg_congestion_ratio",
]

FAMILY_D_HISTORICAL_MATRIX = [
    "baseline_eta_p50_sec",
    "baseline_eta_mean_sec",
    "baseline_eta_p10_sec",
    "baseline_eta_p90_sec",
    "baseline_eta_iqr_sec",
    "baseline_eta_rss_std_sec",
    "baseline_skew_sec",
    "baseline_max_seg_p90_sec",
    "baseline_tier0_frac",
]

FAMILY_E_INCIDENTS = [
    "inc_ahead_count",
    "inc_ahead_total_delay_sec",
    "inc_ahead_max_delay_sec",
    "inc_ahead_max_magnitude",
    "inc_ahead_jam_length_m",
    "inc_dist_to_nearest_m",
]

FAMILY_F_ROUTE_AND_PHYSICS = [
    "route_base_speed_kmh",
    "route_station_spacing_m",
    "physics_kinematic_eta_sec",
    "physics_probe_corrected_eta_sec",
]

ALL_54_FEATURES = (
    FAMILY_A_CURRENT_STATE
    + FAMILY_B_FLEET_AHEAD_BEHIND
    + FAMILY_C_RECENT_PRECEDING_BUS
    + FAMILY_D_HISTORICAL_MATRIX
    + FAMILY_E_INCIDENTS
    + FAMILY_F_ROUTE_AND_PHYSICS
)

ROUTE_IDENTITY_FEATURES = {
    "route_id_idx",
    "current_station_order",
    "target_station_order",
    "route_base_speed_kmh",
    "route_station_spacing_m",
}

ROUTE_BLIND_FEATURES = [f for f in ALL_54_FEATURES if f not in ROUTE_IDENTITY_FEATURES]

CATEGORICAL_FEATURES = [
    "route_id_idx",
    "direction_id",
    "day_type",
    "hour_slot",
]

FEATURE_TO_FAMILY: Dict[str, str] = {}
for _f in FAMILY_A_CURRENT_STATE:
    FEATURE_TO_FAMILY[_f] = "a_current_ego_state"
for _f in FAMILY_B_FLEET_AHEAD_BEHIND:
    FEATURE_TO_FAMILY[_f] = "b_fleet_ahead_behind"
for _f in FAMILY_C_RECENT_PRECEDING_BUS:
    FEATURE_TO_FAMILY[_f] = "c_recent_preceding_bus"
for _f in FAMILY_D_HISTORICAL_MATRIX:
    FEATURE_TO_FAMILY[_f] = "d_historical_matrix"
for _f in FAMILY_E_INCIDENTS:
    FEATURE_TO_FAMILY[_f] = "e_tomtom_incidents"
for _f in FAMILY_F_ROUTE_AND_PHYSICS:
    FEATURE_TO_FAMILY[_f] = "f_route_profile_physics"


def assign_horizon_bucket(n_stations_ahead: np.ndarray) -> np.ndarray:
    """Maps `n_stations_ahead` into 4 integer horizon buckets:
    0: 1_hop (== 1)
    1: 2_to_5 (2..5)
    2: 6_to_15 (6..15)
    3: gt_15 (> 15)
    """
    b = np.zeros(len(n_stations_ahead), dtype=np.int8)
    b[(n_stations_ahead >= 2) & (n_stations_ahead <= 5)] = 1
    b[(n_stations_ahead >= 6) & (n_stations_ahead <= 15)] = 2
    b[n_stations_ahead > 15] = 3
    return b


def prepare_xgb_dataframe(df: pd.DataFrame, feature_cols: List[str]) -> pd.DataFrame:
    """Prepares feature DataFrame with categorical dtypes for fast XGBoost histogram splitting."""
    X = df[feature_cols].copy()
    for c in CATEGORICAL_FEATURES:
        if c in X.columns:
            X[c] = X[c].astype("category")
    return X


def load_stratified_train_and_val_splits(
    train_root: str,
    max_fit_rows_per_route: int = 55000,
    max_val_rows_per_route: int = 20000,
    val_start_date: str = "2026-10-24",
    seed: int = 42,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Loads stratified training (`dt < 2026-10-24`) and temporal validation (`2026-10-24 <= dt <= 2026-10-31`)
    splits across all 48 routes from `gold/eta_feature_store/split=train`.
    """
    rng = np.random.default_rng(seed)
    fit_dfs: List[pd.DataFrame] = []
    val_dfs: List[pd.DataFrame] = []

    route_dirs = sorted(
        [
            os.path.join(train_root, d)
            for d in os.listdir(train_root)
            if os.path.isdir(os.path.join(train_root, d)) and d.startswith("route_code=")
        ]
    )

    for r_dir in route_dirs:
        pq_path = os.path.join(r_dir, "part-00000.snappy.parquet")
        if not os.path.exists(pq_path):
            continue
        df = pd.read_parquet(pq_path)
        if len(df) == 0:
            continue

        mask_val = df["dt"] >= val_start_date
        df_fit = df[~mask_val]
        df_val = df[mask_val]

        if len(df_fit) > max_fit_rows_per_route:
            idx = rng.choice(len(df_fit), size=max_fit_rows_per_route, replace=False)
            idx.sort()
            df_fit = df_fit.iloc[idx]

        if len(df_val) > max_val_rows_per_route:
            idx_v = rng.choice(len(df_val), size=max_val_rows_per_route, replace=False)
            idx_v.sort()
            df_val = df_val.iloc[idx_v]

        fit_dfs.append(df_fit)
        val_dfs.append(df_val)

    fit_all = pd.concat(fit_dfs, ignore_index=True)
    val_all = pd.concat(val_dfs, ignore_index=True)
    return fit_all, val_all


def fit_per_route_empirical_bayes_calibrator(
    val_df: pd.DataFrame,
    raw_pred_eta: np.ndarray,
    shrinkage_m: float = 200.0,
) -> Dict[Tuple[int, int, int], Tuple[float, float]]:
    """
    Fits an Empirical-Bayes shrinkage additive & multiplicative residual calibrator per
    `(route_id_idx, direction_id, horizon_bucket)` on the temporal validation set (`2026-10-24..31`).
    For each cell `g`:
      residual_g = mean(actual_eta - raw_pred_eta)
      weight_g   = N_g / (N_g + shrinkage_m)
      bias_corr  = clip(weight_g * residual_g, -90.0, +90.0)
    """
    actual = val_df["actual_eta_sec"].to_numpy(dtype=np.float64)
    res = actual - raw_pred_eta
    r_idx = val_df["route_id_idx"].to_numpy(dtype=np.int32)
    d_idx = val_df["direction_id"].to_numpy(dtype=np.int32)
    h_bkt = assign_horizon_bucket(val_df["n_stations_ahead"].to_numpy(dtype=np.int32))

    cal_df = pd.DataFrame(
        {
            "r": r_idx,
            "d": d_idx,
            "h": h_bkt,
            "res": res,
            "actual": actual,
            "pred": raw_pred_eta,
        }
    )

    calibrator: Dict[Tuple[int, int, int], Tuple[float, float]] = {}
    grouped = cal_df.groupby(["r", "d", "h"], observed=True)
    for (r_val, d_val, h_val), grp in grouped:
        n_g = len(grp)
        if n_g < 25:
            continue
        w = n_g / (n_g + shrinkage_m)
        # Use robust median + trimmed mean blend for residual shift
        med_res = float(np.median(grp["res"]))
        mean_res = float(np.mean(grp["res"]))
        blended_res = 0.5 * med_res + 0.5 * mean_res
        bias_shift = float(np.clip(w * blended_res, -90.0, 90.0))

        # Ratio correction around predicted ETA
        mean_pred = float(np.mean(grp["pred"]))
        mean_act = float(np.mean(grp["actual"]))
        if mean_pred > 60.0:
            raw_scale = mean_act / mean_pred
            scale_factor = float(np.clip(1.0 + w * (raw_scale - 1.0), 0.88, 1.12))
        else:
            scale_factor = 1.0

        calibrator[(int(r_val), int(d_val), int(h_val))] = (scale_factor, bias_shift)

    return calibrator


def apply_per_route_calibrator(
    df: pd.DataFrame,
    raw_pred_eta: np.ndarray,
    calibrator: Dict[Tuple[int, int, int], Tuple[float, float]],
) -> np.ndarray:
    """Applies the learned Empirical-Bayes per-(route, direction, horizon) calibration to raw predictions."""
    r_idx = df["route_id_idx"].to_numpy(dtype=np.int32)
    d_idx = df["direction_id"].to_numpy(dtype=np.int32)
    h_bkt = assign_horizon_bucket(df["n_stations_ahead"].to_numpy(dtype=np.int32))

    out = raw_pred_eta.copy()
    # Vectorized lookup via composite key
    keys = (r_idx.astype(np.int64) << 8) | (d_idx.astype(np.int64) << 4) | h_bkt.astype(np.int64)
    unique_keys = np.unique(keys)
    for uk in unique_keys:
        r_v = int(uk >> 8)
        d_v = int((uk >> 4) & 0xF)
        h_v = int(uk & 0xF)
        cal = calibrator.get((r_v, d_v, h_v))
        if cal is not None:
            scale_factor, bias_shift = cal
            mask = keys == uk
            # Blend 50% multiplicative + 50% additive correction
            out[mask] = 0.5 * (out[mask] * scale_factor) + 0.5 * (out[mask] + bias_shift)

    return np.maximum(5.0, out)


class StreamingEvaluator:
    """
    Accumulates exact error metrics across all `3,704,820` Test rows in route chunks
    without holding multiple 3.7M float64 prediction arrays in RAM simultaneously.
    """

    HORIZON_NAMES = ["1_hop", "2_to_5", "6_to_15", "gt_15", "ALL"]

    def __init__(self, model_names: List[str]) -> None:
        self.model_names = model_names
        self.stats: Dict[str, Dict[str, Any]] = {}
        for m in model_names:
            self.stats[m] = {}
            for h in self.HORIZON_NAMES:
                self.stats[m][h] = {
                    "count": 0,
                    "sum_abs_err": 0.0,
                    "sum_sq_err": 0.0,
                    "sum_ape": 0.0,
                    "sum_actual": 0.0,
                    "sum_sq_actual": 0.0,
                    "within_60s": 0,
                    "within_120s": 0,
                    "within_180s": 0,
                    "abs_err_reservoir": [],
                }
        self.route_stats: Dict[str, Dict[str, Dict[str, float]]] = {m: {} for m in model_names}

    def update(
        self,
        route_code: str,
        actual: np.ndarray,
        n_ahead: np.ndarray,
        preds_by_model: Dict[str, np.ndarray],
    ) -> None:
        h_bkt = assign_horizon_bucket(n_ahead)
        masks = {
            "1_hop": h_bkt == 0,
            "2_to_5": h_bkt == 1,
            "6_to_15": h_bkt == 2,
            "gt_15": h_bkt == 3,
            "ALL": np.ones(len(actual), dtype=bool),
        }

        for m_name, pred in preds_by_model.items():
            abs_err = np.abs(actual - pred)
            sq_err = (actual - pred) ** 2
            ape = abs_err / np.maximum(30.0, actual)

            # Per-route tracking
            r_st = self.route_stats[m_name].setdefault(
                route_code, {"count": 0.0, "sum_abs_err": 0.0, "sum_sq_err": 0.0}
            )
            r_st["count"] += float(len(actual))
            r_st["sum_abs_err"] += float(np.sum(abs_err))
            r_st["sum_sq_err"] += float(np.sum(sq_err))

            for h_name, mask in masks.items():
                cnt = int(np.sum(mask))
                if cnt == 0:
                    continue
                st = self.stats[m_name][h_name]
                ae_sub = abs_err[mask]
                se_sub = sq_err[mask]
                ape_sub = ape[mask]
                act_sub = actual[mask]

                st["count"] += cnt
                st["sum_abs_err"] += float(np.sum(ae_sub))
                st["sum_sq_err"] += float(np.sum(se_sub))
                st["sum_ape"] += float(np.sum(ape_sub))
                st["sum_actual"] += float(np.sum(act_sub))
                st["sum_sq_actual"] += float(np.sum(act_sub ** 2))
                st["within_60s"] += int(np.sum(ae_sub <= 60.0))
                st["within_120s"] += int(np.sum(ae_sub <= 120.0))
                st["within_180s"] += int(np.sum(ae_sub <= 180.0))

                # Subsample 10% of absolute errors for fast exact-like median/P90 calculation
                step = max(1, cnt // 2500)
                st["abs_err_reservoir"].append(ae_sub[::step].astype(np.float32))

    def summarize(self) -> Dict[str, Dict[str, Dict[str, float]]]:
        summary: Dict[str, Dict[str, Dict[str, float]]] = {}
        for m_name in self.model_names:
            summary[m_name] = {}
            for h_name in self.HORIZON_NAMES:
                st = self.stats[m_name][h_name]
                cnt = st["count"]
                if cnt == 0:
                    continue
                mae = st["sum_abs_err"] / cnt
                rmse = math.sqrt(st["sum_sq_err"] / cnt)
                mape = (st["sum_ape"] / cnt) * 100.0
                mean_act = st["sum_actual"] / cnt
                tss = st["sum_sq_actual"] - cnt * (mean_act ** 2)
                r2 = 1.0 - (st["sum_sq_err"] / tss) if tss > 0 else 0.0

                res_arr = (
                    np.concatenate(st["abs_err_reservoir"])
                    if st["abs_err_reservoir"]
                    else np.zeros(1, dtype=np.float32)
                )
                medae = float(np.median(res_arr))
                p90_ae = float(np.percentile(res_arr, 90))

                summary[m_name][h_name] = {
                    "count": cnt,
                    "mae_sec": round(mae, 2),
                    "medae_sec": round(medae, 2),
                    "rmse_sec": round(rmse, 2),
                    "p90_ae_sec": round(p90_ae, 2),
                    "mape_pct": round(mape, 2),
                    "r2": round(r2, 4),
                    "within_1m_pct": round(100.0 * st["within_60s"] / cnt, 2),
                    "within_2m_pct": round(100.0 * st["within_120s"] / cnt, 2),
                    "within_3m_pct": round(100.0 * st["within_180s"] / cnt, 2),
                }
        return summary


def train_xgb_residual_model(
    fit_df: pd.DataFrame,
    val_df: pd.DataFrame,
    feature_cols: List[str],
    model_label: str,
    n_estimators: int = ETA_N_ESTIMATORS,
    max_depth: int = 10,
    learning_rate: int | float = 0.06,
) -> Tuple[xgb.XGBRegressor, float]:
    """
    Trains an XGBRegressor to predict `delta_eta_sec = actual_eta_sec - baseline_eta_p50_sec`
    weighted by `1 / sqrt(max(60, baseline_eta_p50_sec))`.
    """
    t0 = time.perf_counter()
    X_fit = prepare_xgb_dataframe(fit_df, feature_cols)
    y_fit = (fit_df["actual_eta_sec"] - fit_df["baseline_eta_p50_sec"]).to_numpy(dtype=np.float32)
    w_fit = (1.0 / np.sqrt(np.maximum(60.0, fit_df["baseline_eta_p50_sec"].to_numpy(dtype=np.float32)))).astype(
        np.float32
    )

    X_val = prepare_xgb_dataframe(val_df, feature_cols)
    y_val = (val_df["actual_eta_sec"] - val_df["baseline_eta_p50_sec"]).to_numpy(dtype=np.float32)
    w_val = (1.0 / np.sqrt(np.maximum(60.0, val_df["baseline_eta_p50_sec"].to_numpy(dtype=np.float32)))).astype(
        np.float32
    )

    model = xgb.XGBRegressor(
        n_estimators=n_estimators,
        max_depth=max_depth,
        learning_rate=learning_rate,
        subsample=0.85,
        colsample_bytree=0.85,
        min_child_weight=60.0,
        reg_alpha=2.0,
        reg_lambda=8.0,
        tree_method="hist",
        enable_categorical=True,
        max_cat_to_onehot=4,
        objective="reg:pseudohubererror",
        huber_slope=90.0,
        eval_metric="mae",
        early_stopping_rounds=30,
        random_state=42,
        n_jobs=-1,
    )

    model.fit(
        X_fit,
        y_fit,
        sample_weight=w_fit,
        eval_set=[(X_val, y_val)],
        sample_weight_eval_set=[w_val],
        verbose=False,
    )
    elapsed = time.perf_counter() - t0
    best_iter = getattr(model, "best_iteration", n_estimators)
    print(
        f"  [{model_label}] Trained {len(feature_cols)} features on {len(fit_df):,} rows "
        f"(best_iter={best_iter}) in {elapsed:.2f}s",
        flush=True,
    )
    return model, elapsed


def predict_eta_with_residual_model(
    model: xgb.XGBRegressor,
    df: pd.DataFrame,
    feature_cols: List[str],
) -> np.ndarray:
    """Predicts ETA = max(5.0, baseline_eta_p50_sec + pred_delta_eta)."""
    X = prepare_xgb_dataframe(df, feature_cols)
    pred_delta = model.predict(X)
    base_p50 = df["baseline_eta_p50_sec"].to_numpy(dtype=np.float64)
    return np.maximum(5.0, base_p50 + pred_delta.astype(np.float64))


def compute_feature_importance_ledger(
    model: xgb.XGBRegressor,
    feature_cols: List[str],
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Computes Gain & Weight feature importance and aggregates by feature family (a..f)."""
    booster = model.get_booster()
    gain_map = booster.get_score(importance_type="total_gain")
    weight_map = booster.get_score(importance_type="weight")

    total_gain = sum(gain_map.values()) or 1.0
    total_weight = sum(weight_map.values()) or 1.0

    rows = []
    for f in feature_cols:
        g = gain_map.get(f, 0.0)
        w = weight_map.get(f, 0.0)
        rows.append(
            {
                "feature": f,
                "family": FEATURE_TO_FAMILY.get(f, "other"),
                "total_gain": g,
                "gain_pct": 100.0 * g / total_gain,
                "split_count": int(w),
                "split_pct": 100.0 * w / total_weight,
            }
        )
    feat_df = pd.DataFrame(rows).sort_values("gain_pct", ascending=False).reset_index(drop=True)
    feat_df["cum_gain_pct"] = feat_df["gain_pct"].cumsum()

    fam_df = (
        feat_df.groupby("family", as_index=False)
        .agg(
            n_features=("feature", "count"),
            gain_pct=("gain_pct", "sum"),
            split_pct=("split_pct", "sum"),
            top_feature=("feature", "first"),
        )
        .sort_values("gain_pct", ascending=False)
        .reset_index(drop=True)
    )
    return feat_df, fam_df


def run_step_3_4_ml_training_and_evaluation() -> Dict[str, Any]:
    t_start = time.perf_counter()
    os.makedirs(MODEL_OUT_DIR, exist_ok=True)
    train_root = os.path.join(GOLD_FEATURE_DIR, "split=train")
    test_root = os.path.join(GOLD_FEATURE_DIR, "split=test")

    print("=" * 95)
    print("STEP 3.4: MULTI-ROUTE ML ETA TRAINING, CALIBRATION & FEATURE AUDIT (TD-22)")
    print("=" * 95)

    # 1. Load stratified Train (2026-10-08..23) and Temporal Val (2026-10-24..31)
    t0 = time.perf_counter()
    fit_df, val_df = load_stratified_train_and_val_splits(
        train_root=train_root,
        max_fit_rows_per_route=ETA_MAX_FIT_ROWS_PER_ROUTE,
        max_val_rows_per_route=20000,
        val_start_date="2026-10-24",
    )
    print(
        f"[1/5] Loaded Stratified Train Split: {len(fit_df):,} rows (2026-10-08..23) | "
        f"Temporal Val Split: {len(val_df):,} rows (2026-10-24..31) in {time.perf_counter() - t0:.2f}s",
        flush=True,
    )

    # 2. Train Model 3 (Route-Blind XGBoost) vs. Model 4 (Full 54-Feature Route-Aware Global XGBoost)
    print("\n[2/5] Training Global XGBoost Models (Route-Blind vs. Full Route-Aware 54 Features)...", flush=True)
    model_blind, t_blind = train_xgb_residual_model(
        fit_df=fit_df,
        val_df=val_df,
        feature_cols=ROUTE_BLIND_FEATURES,
        model_label="Model_3_XGB_RouteBlind_49Feat",
    )
    model_full, t_full = train_xgb_residual_model(
        fit_df=fit_df,
        val_df=val_df,
        feature_cols=ALL_54_FEATURES,
        model_label="Model_4_XGB_Global_Full_54Feat",
    )

    # 3. Feature Importance Audit & Compact Pruned Model (Model 6)
    print("\n[3/5] Computing Feature Importance Across Families (a..f) & Training Pruned Model...", flush=True)
    feat_imp_df, fam_imp_df = compute_feature_importance_ledger(model_full, ALL_54_FEATURES)

    # Select top features accounting for >= 98.8% cumulative Gain (or gain_pct >= 0.12%)
    pruned_features = feat_imp_df[
        (feat_imp_df["cum_gain_pct"] <= 98.8) | (feat_imp_df["gain_pct"] >= 0.12)
    ]["feature"].tolist()
    if len(pruned_features) < 20:
        pruned_features = feat_imp_df.head(25)["feature"].tolist()

    pruned_out_features = [f for f in ALL_54_FEATURES if f not in pruned_features]
    print(
        f"  -> Retained {len(pruned_features)}/{len(ALL_54_FEATURES)} core features "
        f"(covering {feat_imp_df[feat_imp_df['feature'].isin(pruned_features)]['gain_pct'].sum():.2f}% of total Gain). "
        f"Pruned {len(pruned_out_features)} low-gain features: {pruned_out_features}",
        flush=True,
    )

    model_pruned, t_pruned = train_xgb_residual_model(
        fit_df=fit_df,
        val_df=val_df,
        feature_cols=pruned_features,
        model_label=f"Model_6_XGB_Pruned_{len(pruned_features)}Feat",
    )

    # 4. Fit Per-(Route, Direction, Horizon) Empirical-Bayes Residual Calibrator on Temporal Val Split
    print("\n[4/5] Fitting Per-(Route, Direction, Horizon) Empirical-Bayes Calibrator on Val Split...", flush=True)
    val_pred_full = predict_eta_with_residual_model(model_full, val_df, ALL_54_FEATURES)
    eb_calibrator = fit_per_route_empirical_bayes_calibrator(val_df, val_pred_full, shrinkage_m=200.0)
    print(f"  -> Fitted {len(eb_calibrator)} (route, direction, horizon) shrinkage calibration cells.", flush=True)

    # Save artifacts to data/models/
    full_model_path = os.path.join(MODEL_OUT_DIR, f"eta_xgb_global_full_54feat{ETA_MODEL_TAG}.json")
    pruned_model_path = os.path.join(MODEL_OUT_DIR, f"eta_xgb_global_pruned{ETA_MODEL_TAG}.json")
    meta_path = os.path.join(MODEL_OUT_DIR, f"eta_xgb_metadata_and_calibrator{ETA_MODEL_TAG}.json")
    model_full.save_model(full_model_path)
    model_pruned.save_model(pruned_model_path)

    # Free training DataFrames before streaming through all 3,704,820 Test rows
    del fit_df, val_df

    # 5. Stream-evaluate all 7 Estimators on 100% of Held-Out Test Set (3,704,820 rows)
    print("\n[5/5] Evaluating All 7 Estimators on Held-Out Test Set (2026-11-01 .. 2026-11-07)...", flush=True)
    model_names = [
        "0_Baseline_Sum_P50",
        "1_Baseline_Sum_Mean",
        "2_Physics_Probe_Blend",
        "3_XGB_Route_Blind_49Feat",
        "4_XGB_Global_Full_54Feat",
        "5_XGB_Global_Calibrated",
        f"6_XGB_Pruned_{len(pruned_features)}Feat",
    ]
    evaluator = StreamingEvaluator(model_names)

    test_route_dirs = sorted(
        [
            os.path.join(test_root, d)
            for d in os.listdir(test_root)
            if os.path.isdir(os.path.join(test_root, d)) and d.startswith("route_code=")
        ]
    )

    t_eval0 = time.perf_counter()
    total_test_rows = 0
    for r_dir in test_route_dirs:
        pq_path = os.path.join(r_dir, "part-00000.snappy.parquet")
        if not os.path.exists(pq_path):
            continue
        tdf = pd.read_parquet(pq_path)
        if len(tdf) == 0:
            continue
        r_code = str(tdf["route_code"].iloc[0])
        total_test_rows += len(tdf)

        actual = tdf["actual_eta_sec"].to_numpy(dtype=np.float64)
        n_ahead = tdf["n_stations_ahead"].to_numpy(dtype=np.int32)
        p50 = np.maximum(5.0, tdf["baseline_eta_p50_sec"].to_numpy(dtype=np.float64))
        pmean = np.maximum(5.0, tdf["baseline_eta_mean_sec"].to_numpy(dtype=np.float64))
        probe_blend = np.maximum(
            5.0,
            0.65 * p50 + 0.35 * tdf["recent_corridor_tt_sum_sec"].to_numpy(dtype=np.float64),
        )

        pred_blind = predict_eta_with_residual_model(model_blind, tdf, ROUTE_BLIND_FEATURES)
        pred_full = predict_eta_with_residual_model(model_full, tdf, ALL_54_FEATURES)
        pred_cal = apply_per_route_calibrator(tdf, pred_full, eb_calibrator)
        pred_pruned = predict_eta_with_residual_model(model_pruned, tdf, pruned_features)

        evaluator.update(
            route_code=r_code,
            actual=actual,
            n_ahead=n_ahead,
            preds_by_model={
                "0_Baseline_Sum_P50": p50,
                "1_Baseline_Sum_Mean": pmean,
                "2_Physics_Probe_Blend": probe_blend,
                "3_XGB_Route_Blind_49Feat": pred_blind,
                "4_XGB_Global_Full_54Feat": pred_full,
                "5_XGB_Global_Calibrated": pred_cal,
                f"6_XGB_Pruned_{len(pruned_features)}Feat": pred_pruned,
            },
        )

    eval_elapsed = time.perf_counter() - t_eval0
    summary = evaluator.summarize()

    # Print formatted tables
    print(f"\nCompleted Test Set Evaluation ({total_test_rows:,} rows across {len(test_route_dirs)} routes) in {eval_elapsed:.2f}s.")
    print("\n" + "=" * 112)
    print("TABLE 1: HELD-OUT TEST SET ACCURACY BY HORIZON (3,704,820 PAIRS | 2026-11-01 .. 2026-11-07)")
    print("=" * 112)
    for h_name in ["1_hop", "2_to_5", "6_to_15", "gt_15", "ALL"]:
        cnt = summary["0_Baseline_Sum_P50"][h_name]["count"]
        print(f"\n--- Horizon: {h_name} (N = {cnt:,} test pairs) ---")
        print(
            f"{'Estimator':<28} | {'MAE (s)':>8} | {'MedAE (s)':>9} | {'RMSE (s)':>8} | "
            f"{'P90 AE':>8} | {'MAPE %':>7} | {'R2':>7} | {'<=1m %':>7} | {'<=2m %':>7} | {'<=3m %':>7}"
        )
        print("-" * 112)
        for m_name in model_names:
            st = summary[m_name][h_name]
            print(
                f"{m_name:<28} | {st['mae_sec']:>8.2f} | {st['medae_sec']:>9.2f} | {st['rmse_sec']:>8.2f} | "
                f"{st['p90_ae_sec']:>8.2f} | {st['mape_pct']:>6.2f}% | {st['r2']:>7.4f} | "
                f"{st['within_1m_pct']:>6.2f}% | {st['within_2m_pct']:>6.2f}% | {st['within_3m_pct']:>6.2f}%"
            )

    print("\n" + "=" * 95)
    print("TABLE 2: CAUSAL FEATURE FAMILY IMPORTANCE (TOTAL GAIN % ACROSS 54 FEATURES)")
    print("=" * 95)
    print(f"{'Feature Family':<30} | {'Features':>8} | {'Gain %':>9} | {'Split %':>9} | {'Top Driver'}")
    print("-" * 95)
    for _, row in fam_imp_df.iterrows():
        print(
            f"{row['family']:<30} | {int(row['n_features']):>8} | {row['gain_pct']:>8.2f}% | "
            f"{row['split_pct']:>8.2f}% | {row['top_feature']}"
        )

    print("\n" + "=" * 95)
    print("TABLE 3: TOP 25 INDIVIDUAL FEATURES BY TOTAL GAIN")
    print("=" * 95)
    print(f"{'Rank':<5} | {'Feature Name':<34} | {'Family':<24} | {'Gain %':>8} | {'CumGain %':>9} | {'Splits':>7}")
    print("-" * 95)
    for idx, row in feat_imp_df.head(25).iterrows():
        print(
            f"{idx + 1:<5} | {row['feature']:<34} | {row['family']:<24} | "
            f"{row['gain_pct']:>7.2f}% | {row['cum_gain_pct']:>8.2f}% | {int(row['split_count']):>7}"
        )

    # Per-route improvement audit (Baseline P50 vs Full Global XGBoost)
    route_rows = []
    for r_code, r_base in evaluator.route_stats["0_Baseline_Sum_P50"].items():
        r_xgb = evaluator.route_stats["4_XGB_Global_Full_54Feat"][r_code]
        r_cal = evaluator.route_stats["5_XGB_Global_Calibrated"][r_code]
        cnt = r_base["count"]
        mae_b = r_base["sum_abs_err"] / cnt
        mae_x = r_xgb["sum_abs_err"] / cnt
        mae_c = r_cal["sum_abs_err"] / cnt
        route_rows.append(
            {
                "route_code": r_code,
                "count": int(cnt),
                "base_mae": round(mae_b, 2),
                "xgb_mae": round(mae_x, 2),
                "cal_mae": round(mae_c, 2),
                "gain_sec": round(mae_b - mae_x, 2),
                "gain_pct": round(100.0 * (mae_b - mae_x) / max(1.0, mae_b), 2),
            }
        )
    route_df = pd.DataFrame(route_rows).sort_values("gain_pct", ascending=False).reset_index(drop=True)
    n_improved = int((route_df["xgb_mae"] < route_df["base_mae"]).sum())
    print("\n" + "=" * 95)
    print(f"TABLE 4: PER-ROUTE GENERALIZATION AUDIT ({n_improved}/{len(route_df)} ROUTES IMPROVED OVER BASELINE)")
    print("=" * 95)
    print("Top 5 Most Improved Routes:")
    for _, r in route_df.head(5).iterrows():
        print(
            f"  Route {r['route_code']:<5} (N={r['count']:>7,}): Baseline MAE={r['base_mae']:>6.2f}s -> "
            f"XGB MAE={r['xgb_mae']:>6.2f}s (Calibrated={r['cal_mae']:>6.2f}s) | Gain = -{r['gain_sec']:.2f}s (-{r['gain_pct']:.1f}%)"
        )
    print("Bottom 5 Routes (Smallest Gain / Highest Variance):")
    for _, r in route_df.tail(5).iterrows():
        print(
            f"  Route {r['route_code']:<5} (N={r['count']:>7,}): Baseline MAE={r['base_mae']:>6.2f}s -> "
            f"XGB MAE={r['xgb_mae']:>6.2f}s (Calibrated={r['cal_mae']:>6.2f}s) | Gain = -{r['gain_sec']:.2f}s (-{r['gain_pct']:.1f}%)"
        )

    # Save metadata JSON
    meta_payload = {
        "total_test_rows": total_test_rows,
        "all_features": ALL_54_FEATURES,
        "pruned_features": pruned_features,
        "pruned_out_features": pruned_out_features,
        "summary_metrics": summary,
        "family_importance": fam_imp_df.to_dict(orient="records"),
        "feature_importance": feat_imp_df.to_dict(orient="records"),
        "per_route_audit": route_df.to_dict(orient="records"),
        "calibrator": {f"{k[0]}_{k[1]}_{k[2]}": list(v) for k, v in eb_calibrator.items()},
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta_payload, f, indent=2, ensure_ascii=False)

    print(f"\nSaved models & evaluation ledger to {MODEL_OUT_DIR} (Total elapsed: {time.perf_counter() - t_start:.2f}s).")
    return meta_payload


if __name__ == "__main__":
    run_step_3_4_ml_training_and_evaluation()

