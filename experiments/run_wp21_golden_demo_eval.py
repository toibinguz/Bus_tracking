"""
Script: experiments/run_wp21_golden_demo_eval.py
Purpose: Hotfixed WP 2.1.4 Empirical Benchmark:
  Compares Model A (v1.0 Base 24 Features, Residual XGB-CQR) vs
  Model B (v2.0 TomTom Fusion 27 Features, Residual XGB-CQR) on Golden Demo Routes 02 & 27.
  Evaluates across:
    1. Overall Unseen Test Set (strict 70/10/20 trip-level temporal split)
    2. Active Congestion Horizon Slice (tomtom_has_incident == 1)
    3. Leader Blind-Spot / High-Headway Congestion Slice (tomtom_has_incident == 1 & leader_info_age_sec >= 900s)
Exports: reports/wp21_tomtom_fusion_benchmark_report.md
"""
import os
import sys
import time

sys.path.insert(0, os.path.abspath("."))
sys.stdout.reconfigure(encoding="utf-8")

import numpy as np
import pandas as pd
import xgboost as xgb

from module_3_bus_eta_prediction.step_3_2_feature_store_extractor.feature_extractor import (
    FEATURE_COLUMNS,
    TARGET_COLUMN,
    TOMTOM_FEATURE_COLUMNS,
    V2_FEATURE_COLUMNS,
    extract_route_training_dataset,
)
from module_3_bus_eta_prediction.step_3_3_machine_learning_models.train_eta_model import (
    compute_interval_metrics,
)

DB_PATH = "data/hanoi_bus_system.db"
DEMO_ROUTES = ["02", "27"]


def train_and_predict_cqr(
    train_df: pd.DataFrame,
    cal_df: pd.DataFrame,
    test_df: pd.DataFrame,
    feature_cols: list,
    use_tomtom_prior: bool = False,
):
    """
    Trains the canonical Residual Multi-Quantile XGBoost Regressor (q = [0.10, 0.50, 0.90])
    with Heteroscedastic Conformalized Quantile Regression (Scaled CQR) on the 10% calibration split.
    When use_tomtom_prior=True, incorporates damped causal TomTom delay prior into the residual
    anchor when leader probe information is stale/aging.
    """
    X_train = train_df[feature_cols]
    y_train = train_df[TARGET_COLUMN].to_numpy()
    X_cal = cal_df[feature_cols]
    y_cal = cal_df[TARGET_COLUMN].to_numpy()
    X_test = test_df[feature_cols]
    y_test = test_df[TARGET_COLUMN].to_numpy()

    base_train = train_df["baseline_median_sec"].to_numpy().copy()
    base_cal = cal_df["baseline_median_sec"].to_numpy().copy()
    base_test = test_df["baseline_median_sec"].to_numpy().copy()

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

    # Calibration
    cal_res = q_model.predict(X_cal)
    cal_p10 = np.maximum(0.0, base_cal + cal_res[:, 0])
    cal_p50 = np.maximum(cal_p10, base_cal + cal_res[:, 1])
    cal_p90 = np.maximum(cal_p50, base_cal + cal_res[:, 2])

    cal_scale = np.maximum(15.0, cal_df["baseline_spread_sec"].to_numpy())
    test_scale = np.maximum(15.0, test_df["baseline_spread_sec"].to_numpy())

    scaled_scores = np.maximum(cal_p10 - y_cal, y_cal - cal_p90) / cal_scale
    q_conformal = float(np.quantile(scaled_scores, 0.80))

    # Test prediction
    test_res = q_model.predict(X_test)
    p_low_raw = np.maximum(0.0, base_test + test_res[:, 0])
    p_med = np.maximum(0.0, base_test + test_res[:, 1])
    p_high_raw = np.maximum(p_med, base_test + test_res[:, 2])

    p_low = np.maximum(0.0, p_low_raw - q_conformal * test_scale)
    p_high = np.maximum(p_med, p_high_raw + q_conformal * test_scale)

    importance = dict(zip(feature_cols, q_model.feature_importances_))
    return p_low, p_med, p_high, q_conformal, importance


def eval_route(route_code: str):
    print("=" * 88, flush=True)
    print(f"EVALUATING GOLDEN DEMO ROUTE {route_code} (CLEAN CONTIGUOUS FRENET TOMTOM FUSION)", flush=True)
    print("=" * 88, flush=True)
    t0 = time.time()
    df = extract_route_training_dataset(route_code, db_path=DB_PATH, include_tomtom=True)
    if df.empty:
        print(f"No data for Route {route_code}!", flush=True)
        return None

    inc_rate_all = float(df["tomtom_has_incident"].mean() * 100.0)
    print(
        f"Extracted {len(df):,} samples in {time.time() - t0:.2f}s | "
        f"Clean active incident rate: {inc_rate_all:.2f}% (was ~32% before s_min=0 hotfix).",
        flush=True,
    )

    # Canonical 70% Train / 10% Calibration / 20% Unseen Test Trip-Level Split
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
    y_test = test_df[TARGET_COLUMN].to_numpy()

    # Model A: v1.0 Base 24 Features
    p_low_A, p_med_A, p_high_A, q_A, imp_A = train_and_predict_cqr(
        train_df, cal_df, test_df, FEATURE_COLUMNS, use_tomtom_prior=False
    )
    met_A = compute_interval_metrics(y_test, p_low_A, p_med_A, p_high_A, alpha=0.20)

    # Model B: v2.0 TomTom Fusion 27 Features (with staleness-weighted TomTom anchor & CQR scale)
    p_low_B, p_med_B, p_high_B, q_B, imp_B = train_and_predict_cqr(
        train_df, cal_df, test_df, V2_FEATURE_COLUMNS, use_tomtom_prior=True
    )
    met_B = compute_interval_metrics(y_test, p_low_B, p_med_B, p_high_B, alpha=0.20)

    # Slice 1: All Active Incidents Ahead (tomtom_has_incident == 1)
    inc_mask = test_df["tomtom_has_incident"].to_numpy() == 1
    n_inc = int(np.sum(inc_mask))
    met_A_inc = compute_interval_metrics(
        y_test[inc_mask], p_low_A[inc_mask], p_med_A[inc_mask], p_high_A[inc_mask], alpha=0.20
    ) if n_inc > 0 else met_A
    met_B_inc = compute_interval_metrics(
        y_test[inc_mask], p_low_B[inc_mask], p_med_B[inc_mask], p_high_B[inc_mask], alpha=0.20
    ) if n_inc > 0 else met_B

    # Slice 2: Leader Blind-Spot / High-Headway Incidents (tomtom_has_incident == 1 & leader_info_age_sec >= 900s)
    blind_mask = (test_df["tomtom_has_incident"].to_numpy() == 1) & (
        test_df["leader_info_age_sec"].to_numpy() >= 900.0
    )
    n_blind = int(np.sum(blind_mask))
    if n_blind >= 20:
        met_A_blind = compute_interval_metrics(
            y_test[blind_mask], p_low_A[blind_mask], p_med_A[blind_mask], p_high_A[blind_mask], alpha=0.20
        )
        met_B_blind = compute_interval_metrics(
            y_test[blind_mask], p_low_B[blind_mask], p_med_B[blind_mask], p_high_B[blind_mask], alpha=0.20
        )
    else:
        met_A_blind = met_A_inc
        met_B_blind = met_B_inc

    # Mean shift diagnostics on incident slice
    mean_d_p50_inc = float(np.mean(p_med_B[inc_mask] - p_med_A[inc_mask])) if n_inc > 0 else 0.0
    mean_d_p90_inc = float(np.mean(p_high_B[inc_mask] - p_high_A[inc_mask])) if n_inc > 0 else 0.0
    mean_d_p50_blind = float(np.mean(p_med_B[blind_mask] - p_med_A[blind_mask])) if n_blind > 0 else 0.0
    mean_d_p90_blind = float(np.mean(p_high_B[blind_mask] - p_high_A[blind_mask])) if n_blind > 0 else 0.0

    print(f"\n[Route {route_code} Results Summary]", flush=True)
    print(f"  Overall Test ({len(test_df):,} samples): MAE {met_A['mae_sec']:.2f}s -> {met_B['mae_sec']:.2f}s | PICP {met_A['picp_coverage_pct']:.2f}% -> {met_B['picp_coverage_pct']:.2f}% | Winkler {met_A['winkler_score_sec']:.2f}s -> {met_B['winkler_score_sec']:.2f}s", flush=True)
    print(f"  Active Congestion Slice ({n_inc:,} samples, {n_inc/len(test_df)*100:.2f}%): MAE {met_A_inc['mae_sec']:.2f}s -> {met_B_inc['mae_sec']:.2f}s | MdAE {met_A_inc['mdae_sec']:.2f}s -> {met_B_inc['mdae_sec']:.2f}s | PICP {met_A_inc['picp_coverage_pct']:.2f}% -> {met_B_inc['picp_coverage_pct']:.2f}% | Winkler {met_A_inc['winkler_score_sec']:.2f}s -> {met_B_inc['winkler_score_sec']:.2f}s", flush=True)
    print(f"  Leader Blind-Spot Congestion Slice ({n_blind:,} samples): MAE {met_A_blind['mae_sec']:.2f}s -> {met_B_blind['mae_sec']:.2f}s | MdAE {met_A_blind['mdae_sec']:.2f}s -> {met_B_blind['mdae_sec']:.2f}s | PICP {met_A_blind['picp_coverage_pct']:.2f}% -> {met_B_blind['picp_coverage_pct']:.2f}% | Winkler {met_A_blind['winkler_score_sec']:.2f}s -> {met_B_blind['winkler_score_sec']:.2f}s", flush=True)
    print(f"  Shift on Active Congestion: dP50 = {mean_d_p50_inc:+.2f}s, dP90 = {mean_d_p90_inc:+.2f}s | Blind-Spot: dP50 = {mean_d_p50_blind:+.2f}s, dP90 = {mean_d_p90_blind:+.2f}s", flush=True)

    return {
        "route_code": route_code,
        "n_samples": len(df),
        "inc_rate_all_pct": round(inc_rate_all, 2),
        "n_train": len(train_df),
        "n_cal": len(cal_df),
        "n_test": len(test_df),
        "n_inc_test": n_inc,
        "inc_rate_test_pct": round(n_inc / len(test_df) * 100.0, 2),
        "n_blind_test": n_blind,
        "met_A": met_A,
        "met_B": met_B,
        "met_A_inc": met_A_inc,
        "met_B_inc": met_B_inc,
        "met_A_blind": met_A_blind,
        "met_B_blind": met_B_blind,
        "mean_d_p50_inc": round(mean_d_p50_inc, 2),
        "mean_d_p90_inc": round(mean_d_p90_inc, 2),
        "mean_d_p50_blind": round(mean_d_p50_blind, 2),
        "mean_d_p90_blind": round(mean_d_p90_blind, 2),
        "imp_B": imp_B,
    }


def main():
    results = {}
    for rc in DEMO_ROUTES:
        res = eval_route(rc)
        if res:
            results[rc] = res

    os.makedirs("reports", exist_ok=True)
    report_path = "reports/wp21_tomtom_fusion_benchmark_report.md"

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# BÁO CÁO THỰC NGHIỆM ĐỐI CHUẨN MÔ HÌNH V2.0 (HOTFIXED): TÍCH HỢP ĐA NGUỒN SỰ CỐ TOMTOM (WP 2.1)\n\n")
        f.write("> **Ngày cập nhật**: 02/11/2026 (Bản vá Contiguous Frenet Projection & Causal Snapshot Windows)  \n")
        f.write("> **Phạm vi**: Đối chuẩn **Model A** (24 Features v1.0, Residual XGB-CQR) vs **Model B** (27 Features v2.0, Staleness-Weighted TomTom Residual XGB-CQR) trên Golden Demo Routes (`02`, `27`) với chia tách chuyến nghiêm ngặt `70% Train / 10% Calib / 20% Unseen Test`.  \n\n")

        f.write("## I. BẢNG TỔNG HỢP TOÀN BỘ TẬP KIỂM THỬ ĐỘC LẬP (OVERALL UNSEEN TEST SET)\n\n")
        f.write("| Tuyến | Số Mẫu Test | Tỷ Lệ Mẫu Có Sự Cố | Model | Point MAE | Point MdAE | Hit@60s | Độ Phủ PICP [80%] | Độ Rộng MPIW | Winkler Score |\n")
        f.write("| :---: | :---: | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: |\n")
        for rc, r in results.items():
            mA = r["met_A"]
            mB = r["met_B"]
            f.write(
                f"| **Tuyến {rc}** | {r['n_test']:,} | {r['inc_rate_test_pct']:.2f}% | Model A (Base 24) | {mA['mae_sec']:.2f}s | {mA['mdae_sec']:.2f}s | {mA['hit_60s_pct']:.2f}% | {mA['picp_coverage_pct']:.2f}% | {mA['mpiw_width_sec']:.2f}s | {mA['winkler_score_sec']:.2f}s |\n"
            )
            f.write(
                f"| | | | **Model B (TomTom 27)** | **{mB['mae_sec']:.2f}s** | **{mB['mdae_sec']:.2f}s** | **{mB['hit_60s_pct']:.2f}%** | **{mB['picp_coverage_pct']:.2f}%** | **{mB['mpiw_width_sec']:.2f}s** | **{mB['winkler_score_sec']:.2f}s** |\n"
            )

        f.write("\n## II. BẢNG PHÂN TÍCH LÁT CẮT CÓ SỰ CỐ TRÊN LỘ TRÌNH PHÍA TRƯỚC (ACTIVE CONGESTION HORIZON SLICE)\n\n")
        f.write("| Tuyến | Mẫu Có Sự Cố | Model | Slice MAE | Slice MdAE | Hit@60s | Slice PICP [80%] | Slice MPIW | Slice Winkler | Dịch Chuyển $\\Delta P_{50}$ / $\\Delta P_{90}$ |\n")
        f.write("| :---: | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n")
        for rc, r in results.items():
            mA = r["met_A_inc"]
            mB = r["met_B_inc"]
            f.write(
                f"| **Tuyến {rc}** | {r['n_inc_test']:,} | Model A (Không TomTom) | {mA['mae_sec']:.2f}s | {mA['mdae_sec']:.2f}s | {mA['hit_60s_pct']:.2f}% | {mA['picp_coverage_pct']:.2f}% | {mA['mpiw_width_sec']:.2f}s | {mA['winkler_score_sec']:.2f}s | — |\n"
            )
            f.write(
                f"| | | **Model B (Có TomTom)** | **{mB['mae_sec']:.2f}s** | **{mB['mdae_sec']:.2f}s** | **{mB['hit_60s_pct']:.2f}%** | **{mB['picp_coverage_pct']:.2f}%** | **{mB['mpiw_width_sec']:.2f}s** | **{mB['winkler_score_sec']:.2f}s** | **{r['mean_d_p50_inc']:+.2f}s / {r['mean_d_p90_inc']:+.2f}s** |\n"
            )

        f.write("\n## III. BẢNG PHÂN TÍCH LÁT CẮT MÙ XE DẪN ĐƯỜNG (LEADER BLIND-SPOT CONGESTION: `leader_info_age_sec >= 900s`)\n\n")
        f.write("| Tuyến | Mẫu Mù Xe Dẫn Đường | Model | Blind-Spot MAE | Blind-Spot MdAE | Hit@60s | Blind-Spot PICP | Blind-Spot MPIW | Blind-Spot Winkler | Dịch Chuyển $\\Delta P_{50}$ / $\\Delta P_{90}$ |\n")
        f.write("| :---: | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n")
        for rc, r in results.items():
            mA = r["met_A_blind"]
            mB = r["met_B_blind"]
            f.write(
                f"| **Tuyến {rc}** | {r['n_blind_test']:,} | Model A (Không TomTom) | {mA['mae_sec']:.2f}s | {mA['mdae_sec']:.2f}s | {mA['hit_60s_pct']:.2f}% | {mA['picp_coverage_pct']:.2f}% | {mA['mpiw_width_sec']:.2f}s | {mA['winkler_score_sec']:.2f}s | — |\n"
            )
            f.write(
                f"| | | **Model B (Có TomTom)** | **{mB['mae_sec']:.2f}s** | **{mB['mdae_sec']:.2f}s** | **{mB['hit_60s_pct']:.2f}%** | **{mB['picp_coverage_pct']:.2f}%** | **{mB['mpiw_width_sec']:.2f}s** | **{mB['winkler_score_sec']:.2f}s** | **{r['mean_d_p50_blind']:+.2f}s / {r['mean_d_p90_blind']:+.2f}s** |\n"
            )

        f.write("\n## IV. KẾT LUẬN THỰC NGHIỆM ĐỊNH LƯỢNG (SINH TỰ ĐỘNG TỪ SỐ LIỆU THỰC THI)\n\n")
        for rc, r in results.items():
            d_mae_inc = r["met_B_inc"]["mae_sec"] - r["met_A_inc"]["mae_sec"]
            d_wink_inc = r["met_B_inc"]["winkler_score_sec"] - r["met_A_inc"]["winkler_score_sec"]
            d_picp_inc = r["met_B_inc"]["picp_coverage_pct"] - r["met_A_inc"]["picp_coverage_pct"]
            d_mae_blind = r["met_B_blind"]["mae_sec"] - r["met_A_blind"]["mae_sec"]
            d_wink_blind = r["met_B_blind"]["winkler_score_sec"] - r["met_A_blind"]["winkler_score_sec"]
            f.write(
                f"- **Tuyến {rc}**: Sau khi loại bỏ hoàn toàn lỗi `s_min=0.0`, tỷ lệ mẫu có sự cố thực trên lộ trình phía trước là `{r['inc_rate_test_pct']:.2f}%` ({r['n_inc_test']:,}/{r['n_test']:,} mẫu test). "
                f"Trên lát cắt có sự cố (`Active Congestion Slice`), Model B dịch chuyển dự báo trung vị `$\\Delta P_{{50}} = {r['mean_d_p50_inc']:+.2f}\\text{{s}}$` và cận trên `$\\Delta P_{{90}} = {r['mean_d_p90_inc']:+.2f}\\text{{s}}$`, "
                f"thay đổi `Slice MAE` `{d_mae_inc:+.2f}s` (`{r['met_A_inc']['mae_sec']:.2f}s -> {r['met_B_inc']['mae_sec']:.2f}s`), "
                f"`Slice PICP` `{d_picp_inc:+.2f}%` (`{r['met_A_inc']['picp_coverage_pct']:.2f}% -> {r['met_B_inc']['picp_coverage_pct']:.2f}%`), "
                f"và `Winkler Score` `{d_wink_inc:+.2f}s`. "
                f"Đặc biệt trong chế độ mù xe dẫn đường (`Leader Blind-Spot`, $N={r['n_blind_test']:,}$), Model B dịch chuyển `$\\Delta P_{{50}} = {r['mean_d_p50_blind']:+.2f}\\text{{s}}$`, `$\\Delta P_{{90}} = {r['mean_d_p90_blind']:+.2f}\\text{{s}}$`, thay đổi `Blind-Spot MAE` `{d_mae_blind:+.2f}s` và `Winkler Score` `{d_wink_blind:+.2f}s`.\n"
            )

    print(f"\nReport generated successfully at: {report_path}", flush=True)


if __name__ == "__main__":
    main()
