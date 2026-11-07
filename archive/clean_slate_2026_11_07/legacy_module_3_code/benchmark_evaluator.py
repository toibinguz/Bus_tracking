"""
Module 3: Bus ETA Prediction Engine
Subcomponent: step_3_4_evaluation_and_benchmarking
File: benchmark_evaluator.py

Full-Network Multi-Route Benchmark & Station-Pair Database Evaluation Suite.
Trains and evaluates Point & Interval ETA models across all 48 canonical routes
and persists both:
  1. `ml_station_pair_evaluation` (every station pair across all routes)
  2. `ml_route_evaluation_summary` (route-level summary across all 48 routes)
directly into `data/hanoi_bus_system.db`.
"""

import os
import sqlite3
import sys
import time
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import xgboost as xgb

# Ensure project root in sys.path and UTF-8 console output on Windows
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))
sys.path.insert(0, os.path.abspath("."))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from config.system_config import get_database_path
from module_3_bus_eta_prediction.step_3_2_feature_store_extractor.feature_extractor import (
    FEATURE_COLUMNS,
    TARGET_COLUMN,
    V2_FEATURE_COLUMNS,
    extract_route_training_dataset,
)
from module_3_bus_eta_prediction.step_3_3_machine_learning_models.train_eta_model import (
    MODEL_OUTPUT_DIR,
)


def _get_all_canonical_routes(conn: sqlite3.Connection) -> List[str]:
    cur = conn.cursor()
    cur.execute(
        "SELECT DISTINCT route_code FROM agg_segment_travel_times ORDER BY route_code ASC"
    )
    return [str(r[0]) for r in cur.fetchall()]


def _init_eval_tables(conn: sqlite3.Connection) -> None:
    """Create `ml_station_pair_evaluation` and `ml_route_evaluation_summary` tables."""
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS ml_station_pair_evaluation")
    cur.execute(
        """
        CREATE TABLE ml_station_pair_evaluation (
            route_code TEXT NOT NULL,
            direction TEXT NOT NULL,
            from_station_order INTEGER NOT NULL,
            to_station_order INTEGER NOT NULL,
            from_station_name TEXT,
            to_station_name TEXT,
            segment_distance_m REAL,
            test_sample_count INTEGER,
            actual_mean_sec REAL,
            predicted_mean_sec REAL,
            signed_bias_sec REAL,
            ml_mae_sec REAL,
            ml_wmape_pct REAL,
            ml_mape_pct REAL,
            ml_median_err_sec REAL,
            ml_median_err_pct REAL,
            baseline_3_1_mae_sec REAL,
            baseline_3_1_wmape_pct REAL,
            improvement_vs_3_1_pct REAL,
            pred_p10_mean_sec REAL,
            pred_p90_mean_sec REAL,
            interval_width_sec REAL,
            interval_coverage_picp_pct REAL,
            model_status TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (route_code, direction, from_station_order, to_station_order)
        )
        """
    )
    cur.execute("DROP TABLE IF EXISTS ml_route_evaluation_summary")
    cur.execute(
        """
        CREATE TABLE ml_route_evaluation_summary (
            route_code TEXT PRIMARY KEY,
            total_trips INTEGER,
            total_samples_1_to_5_stops INTEGER,
            test_samples_next_stop INTEGER,
            station_pair_count INTEGER,
            actual_mean_next_stop_sec REAL,
            ml_mae_next_stop_sec REAL,
            ml_wmape_next_stop_pct REAL,
            ml_median_err_next_stop_sec REAL,
            ml_median_err_next_stop_pct REAL,
            baseline_3_1_mae_next_stop_sec REAL,
            improvement_vs_3_1_pct REAL,
            multi_stop_1_to_5_mae_sec REAL,
            multi_stop_1_to_5_base_mae_sec REAL,
            interval_coverage_picp_pct REAL,
            interval_width_next_stop_sec REAL,
            model_artifact_path TEXT,
            model_status TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()


def evaluate_and_persist_all_routes(
    route_codes: Optional[List[str]] = None,
    db_path: Optional[str] = None,
    force_retrain: bool = False,
) -> List[Dict[str, object]]:
    """
    Train (if needed) and evaluate Point & Interval ETA models across all target routes,
    persisting station-pair and route-level results into `data/hanoi_bus_system.db`.
    """
    resolved_db = db_path or str(get_database_path())
    conn = sqlite3.connect(resolved_db)
    _init_eval_tables(conn)
    cur = conn.cursor()

    if not route_codes:
        route_codes = _get_all_canonical_routes(conn)

    os.makedirs(MODEL_OUTPUT_DIR, exist_ok=True)

    print("=" * 108)
    print(
        f"FULL-NETWORK ETA MODEL TRAINING & STATION-PAIR DB EVALUATION ({len(route_codes)} ROUTES)"
    )
    print(f"Database: {resolved_db}")
    print("=" * 108)

    all_pair_rows: List[tuple] = []
    all_route_rows: List[tuple] = []
    summary_list: List[Dict[str, object]] = []

    t_global = time.time()
    for idx_r, rc in enumerate(route_codes, 1):
        t0 = time.time()
        cur.execute(
            """
            SELECT direction, station_order, station_name, cum_distance_m
            FROM canonical_station_master
            WHERE route_code = ?
            ORDER BY direction, station_order ASC
            """,
            (rc,),
        )
        st_by_dir: Dict[str, List[tuple]] = {}
        for d, so, sname, cd in cur.fetchall():
            st_by_dir.setdefault(str(d), []).append((int(so), str(sname), float(cd)))

        total_pairs_on_route = sum(
            max(0, len(sts) - 1) for sts in st_by_dir.values()
        )

        df = extract_route_training_dataset(
            rc, db_path=resolved_db, max_stops_ahead=5, max_horizon_m=3500.0, include_tomtom=True
        )
        unique_trips = df["trip_id"].unique() if not df.empty else []
        n_trips = len(unique_trips)

        model_path = os.path.join(MODEL_OUTPUT_DIR, f"xgboost_eta_route_{rc}.json")

        # Check if route has enough independent trips for Train/Calib/Test split
        if df.empty or n_trips < 10 or len(df) < 100:
            for d in sorted(st_by_dir.keys()):
                sts = st_by_dir[d]
                for i in range(len(sts) - 1):
                    s_from_ord, s_from_name, s_from_d = sts[i]
                    s_to_ord, s_to_name, s_to_d = sts[i + 1]
                    seg_len = round(max(10.0, s_to_d - s_from_d), 2)
                    all_pair_rows.append(
                        (
                            rc,
                            d,
                            s_from_ord,
                            s_to_ord,
                            s_from_name,
                            s_to_name,
                            seg_len,
                            0,
                            None,
                            None,
                            None,
                            None,
                            None,
                            None,
                            None,
                            None,
                            None,
                            None,
                            None,
                            None,
                            None,
                            None,
                            None,
                            "AWAITING_MORE_CRAWLER_DATA",
                        )
                    )
            all_route_rows.append(
                (
                    rc,
                    n_trips,
                    len(df),
                    0,
                    total_pairs_on_route,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    "AWAITING_MORE_CRAWLER_DATA",
                )
            )
            print(
                f"  [{idx_r:02d}/{len(route_codes):02d}] Route {rc:<5} | Trips: {n_trips:4d} | Status: AWAITING_MORE_CRAWLER_DATA ({time.time()-t0:.1f}s)"
            )
            continue

        n_train = max(1, int(n_trips * 0.70))
        n_cal = max(n_train + 1, int(n_trips * 0.80))

        train_trips = set(unique_trips[:n_train])
        cal_trips = set(unique_trips[n_train:n_cal])
        test_trips = set(unique_trips[n_cal:])

        train_df = df[df["trip_id"].isin(train_trips)]
        cal_df_all = df[df["trip_id"].isin(cal_trips)]
        test_df_all = df[df["trip_id"].isin(test_trips)]

        active_features = V2_FEATURE_COLUMNS if "tomtom_has_incident" in df.columns else FEATURE_COLUMNS

        q_model = xgb.XGBRegressor()
        need_train = force_retrain or (not os.path.exists(model_path))
        if not need_train:
            try:
                q_model.load_model(model_path)
                if q_model.n_features_in_ != len(active_features):
                    need_train = True
            except Exception:
                need_train = True

        if need_train:
            X_train = train_df[active_features]
            r_train = (
                train_df[TARGET_COLUMN].to_numpy()
                - train_df["baseline_median_sec"].to_numpy()
            )
            q_model = xgb.XGBRegressor(
                objective="reg:quantileerror",
                quantile_alpha=np.array([0.10, 0.50, 0.90]),
                tree_method="hist",
                n_estimators=140,
                max_depth=6,
                learning_rate=0.06,
                subsample=0.85,
                colsample_bytree=0.85,
                min_child_weight=20,
                random_state=42,
                n_jobs=6,
            )
            q_model.fit(X_train, r_train)
            q_model.save_model(model_path)

        # Calibrate CQR scale on calibration trips
        cal_res = q_model.predict(cal_df_all[active_features])
        b_cal = cal_df_all["baseline_median_sec"].to_numpy()
        y_cal = cal_df_all[TARGET_COLUMN].to_numpy()
        cal_p50 = np.maximum(0.0, b_cal + cal_res[:, 1])
        cal_p10 = np.minimum(cal_p50, np.maximum(0.0, b_cal + cal_res[:, 0]))
        cal_p90 = np.maximum(cal_p50, b_cal + cal_res[:, 2])
        cal_scale = np.maximum(15.0, cal_df_all["baseline_spread_sec"].to_numpy())
        q_conf = float(
            np.quantile(
                np.maximum(cal_p10 - y_cal, y_cal - cal_p90) / cal_scale, 0.80
            )
        )

        # Multi-stop (1-5 stops) test evaluation
        res_all = q_model.predict(test_df_all[active_features])
        b_all = test_df_all["baseline_median_sec"].to_numpy()
        y_all = test_df_all[TARGET_COLUMN].to_numpy()
        p50_all = np.maximum(0.0, b_all + res_all[:, 1])
        multi_mae_ml = float(np.mean(np.abs(y_all - p50_all)))
        multi_mae_base = float(np.mean(np.abs(y_all - b_all)))

        # Next-stop (stops_ahead == 1) station-pair evaluation
        te_df = test_df_all[test_df_all["stops_ahead"] == 1].copy()
        te_res = q_model.predict(te_df[active_features])
        b_te = te_df["baseline_median_sec"].to_numpy()
        te_scale = np.maximum(15.0, te_df["baseline_spread_sec"].to_numpy())

        p10_raw = np.maximum(0.0, b_te + te_res[:, 0])
        p50 = np.maximum(p10_raw, b_te + te_res[:, 1])
        p90_raw = np.maximum(p50, b_te + te_res[:, 2])
        p10 = np.minimum(p50, np.maximum(0.0, p10_raw - q_conf * te_scale))
        p90 = np.maximum(p50, p90_raw + q_conf * te_scale)

        te_df["pred_p10"] = p10
        te_df["pred_p50"] = p50
        te_df["pred_p90"] = p90
        te_df["abs_err_ml"] = np.abs(te_df[TARGET_COLUMN] - te_df["pred_p50"])
        te_df["abs_err_base"] = np.abs(
            te_df[TARGET_COLUMN] - te_df["baseline_median_sec"]
        )
        te_df["mape_ml"] = (
            te_df["abs_err_ml"] / np.maximum(te_df[TARGET_COLUMN], 15.0)
        ) * 100.0
        te_df["in_interval"] = (
            (te_df[TARGET_COLUMN] >= te_df["pred_p10"])
            & (te_df[TARGET_COLUMN] <= te_df["pred_p90"])
        ).astype(float) * 100.0

        status_tag = (
            "PRODUCTION_READY" if n_trips >= 500 else "PROVISIONAL_LOW_SAMPLE"
        )

        for d in sorted(st_by_dir.keys()):
            sts = st_by_dir[d]
            for i in range(len(sts) - 1):
                s_from_ord, s_from_name, s_from_d = sts[i]
                s_to_ord, s_to_name, s_to_d = sts[i + 1]
                seg_len = round(max(10.0, s_to_d - s_from_d), 2)

                sub = te_df[
                    (te_df["direction"] == d)
                    & (te_df["target_station_order"] == s_to_ord)
                ]
                n_s = int(len(sub))
                if n_s == 0:
                    all_pair_rows.append(
                        (
                            rc,
                            d,
                            s_from_ord,
                            s_to_ord,
                            s_from_name,
                            s_to_name,
                            seg_len,
                            0,
                            None,
                            None,
                            None,
                            None,
                            None,
                            None,
                            None,
                            None,
                            None,
                            None,
                            None,
                            None,
                            None,
                            None,
                            None,
                            "NO_TEST_SAMPLES_ON_SEGMENT",
                        )
                    )
                    continue

                act_mean = float(sub[TARGET_COLUMN].mean())
                pred_mean = float(sub["pred_p50"].mean())
                bias_sec = pred_mean - act_mean

                mae_ml = float(sub["abs_err_ml"].mean())
                wmape_ml = (mae_ml / max(act_mean, 5.0)) * 100.0
                mape_ml = float(sub["mape_ml"].mean())

                mdae_ml = float(sub["abs_err_ml"].median())
                md_pct_ml = (mdae_ml / max(act_mean, 5.0)) * 100.0

                mae_base = float(sub["abs_err_base"].mean())
                wmape_base = (mae_base / max(act_mean, 5.0)) * 100.0
                improv_pct = ((mae_base - mae_ml) / max(mae_base, 0.1)) * 100.0

                p10_m = float(sub["pred_p10"].mean())
                p90_m = float(sub["pred_p90"].mean())
                width_m = p90_m - p10_m
                picp_m = float(sub["in_interval"].mean())

                all_pair_rows.append(
                    (
                        rc,
                        d,
                        s_from_ord,
                        s_to_ord,
                        s_from_name,
                        s_to_name,
                        seg_len,
                        n_s,
                        round(act_mean, 2),
                        round(pred_mean, 2),
                        round(bias_sec, 2),
                        round(mae_ml, 2),
                        round(wmape_ml, 2),
                        round(mape_ml, 2),
                        round(mdae_ml, 2),
                        round(md_pct_ml, 2),
                        round(mae_base, 2),
                        round(wmape_base, 2),
                        round(improv_pct, 2),
                        round(p10_m, 2),
                        round(p90_m, 2),
                        round(width_m, 2),
                        round(picp_m, 2),
                        status_tag,
                    )
                )

        act_all = float(te_df[TARGET_COLUMN].mean()) if len(te_df) > 0 else 1.0
        mae_all = float(te_df["abs_err_ml"].mean()) if len(te_df) > 0 else 0.0
        wmape_all = (mae_all / max(act_all, 5.0)) * 100.0
        mdae_all = float(te_df["abs_err_ml"].median()) if len(te_df) > 0 else 0.0
        md_pct_all = (mdae_all / max(act_all, 5.0)) * 100.0
        base_all = float(te_df["abs_err_base"].mean()) if len(te_df) > 0 else 0.0
        improv_all = ((base_all - mae_all) / max(base_all, 0.1)) * 100.0
        picp_all = float(te_df["in_interval"].mean()) if len(te_df) > 0 else 0.0
        width_all = (
            float((te_df["pred_p90"] - te_df["pred_p10"]).mean())
            if len(te_df) > 0
            else 0.0
        )

        all_route_rows.append(
            (
                rc,
                n_trips,
                len(df),
                len(te_df),
                total_pairs_on_route,
                round(act_all, 2),
                round(mae_all, 2),
                round(wmape_all, 2),
                round(mdae_all, 2),
                round(md_pct_all, 2),
                round(base_all, 2),
                round(improv_all, 2),
                round(multi_mae_ml, 2),
                round(multi_mae_base, 2),
                round(picp_all, 2),
                round(width_all, 2),
                model_path,
                status_tag,
            )
        )

        print(
            f"  [{idx_r:02d}/{len(route_codes):02d}] Route {rc:<5} | Trips:{n_trips:5,d} | "
            f"Stop1 MAE:{mae_all:5.1f}s ({wmape_all:4.1f}%) | MdAE:{mdae_all:4.1f}s ({md_pct_all:4.1f}%) | "
            f"Base:{base_all:5.1f}s ({improv_all:+5.1f}%) | 1-5Stop MAE:{multi_mae_ml:5.1f}s | "
            f"PICP:{picp_all:4.1f}% | {time.time()-t0:.1f}s"
        )
        summary_list.append({"route_code": rc, "trips": n_trips, "mae": mae_all})

    cur.executemany(
        """
        INSERT INTO ml_station_pair_evaluation (
            route_code, direction, from_station_order, to_station_order,
            from_station_name, to_station_name, segment_distance_m,
            test_sample_count, actual_mean_sec, predicted_mean_sec,
            signed_bias_sec, ml_mae_sec, ml_wmape_pct, ml_mape_pct,
            ml_median_err_sec, ml_median_err_pct,
            baseline_3_1_mae_sec, baseline_3_1_wmape_pct, improvement_vs_3_1_pct,
            pred_p10_mean_sec, pred_p90_mean_sec, interval_width_sec,
            interval_coverage_picp_pct, model_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        all_pair_rows,
    )
    cur.executemany(
        """
        INSERT INTO ml_route_evaluation_summary (
            route_code, total_trips, total_samples_1_to_5_stops,
            test_samples_next_stop, station_pair_count,
            actual_mean_next_stop_sec, ml_mae_next_stop_sec, ml_wmape_next_stop_pct,
            ml_median_err_next_stop_sec, ml_median_err_next_stop_pct,
            baseline_3_1_mae_next_stop_sec, improvement_vs_3_1_pct,
            multi_stop_1_to_5_mae_sec, multi_stop_1_to_5_base_mae_sec,
            interval_coverage_picp_pct, interval_width_next_stop_sec,
            model_artifact_path, model_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        all_route_rows,
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_ml_pair_eval_err ON ml_station_pair_evaluation(ml_mae_sec DESC)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_ml_pair_eval_pct ON ml_station_pair_evaluation(ml_wmape_pct DESC)"
    )
    conn.commit()
    conn.close()

    print("=" * 108)
    print(
        f"COMPLETED ALL {len(route_codes)} ROUTES IN {time.time() - t_global:.1f}s! "
        f"Persisted {len(all_pair_rows):,d} station pairs into `ml_station_pair_evaluation` "
        f"and {len(all_route_rows):,d} routes into `ml_route_evaluation_summary`."
    )
    print("=" * 108)
    return summary_list


if __name__ == "__main__":
    target_routes = sys.argv[1:] if len(sys.argv) > 1 else None
    evaluate_and_persist_all_routes(target_routes)
