"""
Script: experiments/run_full_gold_sync_and_eval.py
Purpose: Complete execution of user request:
  1. Synchronize Gold Parquet Lakehouse for all 48 canonical routes with force_overwrite=True
     so all Stage 1 samples reflect the clean, non-clamped database.
  2. Run WP 2.2 Medallion Lakehouse & Weekly SLA Benchmark (`scripts/run_wp22_medallion_and_weekly_sla.py`).
  3. Run Station-Pair Evaluation (`benchmark_evaluator.py`) on Golden Demo Routes (02, 27)
     to persist `ml_station_pair_evaluation` and `ml_route_evaluation_summary`.
"""

import os
import sys
import time
import sqlite3

sys.path.insert(0, os.path.abspath("."))
sys.stdout.reconfigure(encoding="utf-8")

from config.system_config import DEFAULT_DB_PATH, DEFAULT_LAKEHOUSE_ROOT
from module_2_big_data_storage_and_lakehouse.step_2_2_parquet_medallion_lakehouse.lakehouse_exporter import (
    parallel_sync_all_routes_stage1_parquet,
)
import scripts.run_wp22_medallion_and_weekly_sla as wp22_sla
from module_3_bus_eta_prediction.step_3_4_evaluation_and_benchmarking.benchmark_evaluator import (
    evaluate_and_persist_all_routes,
)


def get_all_routes(db_path: str):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    routes = [
        str(r[0])
        for r in cur.execute(
            "SELECT DISTINCT route_code FROM route_projected_telemetry ORDER BY route_code"
        ).fetchall()
    ]
    conn.close()
    return routes


def main():
    t_start = time.time()
    all_routes = get_all_routes(DEFAULT_DB_PATH)
    print("=" * 88, flush=True)
    print(f"[STEP 1/3] SYNCING GOLD PARQUET SAMPLES FOR ALL {len(all_routes)} ROUTES (force_overwrite=True)", flush=True)
    print("=" * 88, flush=True)

    t0 = time.time()
    par_res = parallel_sync_all_routes_stage1_parquet(
        all_routes,
        db_path=DEFAULT_DB_PATH,
        lakehouse_root=DEFAULT_LAKEHOUSE_ROOT,
        force_overwrite=True,
        max_workers=8,
    )
    t_sync = time.time() - t0
    print(
        f"\n>>> Step 1 Complete: {par_res['total_samples']:,} samples across {len(all_routes)} routes "
        f"in {t_sync:.2f}s ({par_res['parallel_speedup_ratio']:.2f}x parallel speedup)!\n",
        flush=True,
    )

    print("=" * 88, flush=True)
    print("[STEP 2/3] RUNNING FULL WP 2.2 MEDALLION LAKEHOUSE & WEEKLY SLA BENCHMARK", flush=True)
    print("=" * 88, flush=True)
    t0 = time.time()
    wp22_sla.main()
    t_sla = time.time() - t0
    print(f"\n>>> Step 2 Complete in {t_sla:.2f}s!\n", flush=True)

    print("=" * 88, flush=True)
    print("[STEP 3/3] RUNNING STATION-PAIR DATABASE EVALUATION ON DEMO ROUTES (02, 27)", flush=True)
    print("=" * 88, flush=True)
    t0 = time.time()
    eval_res = evaluate_and_persist_all_routes(["02", "27"], force_retrain=True)
    t_eval = time.time() - t0
    print(f"\n>>> Step 3 Complete in {t_eval:.2f}s!\n", flush=True)

    print("=" * 88, flush=True)
    print(f"ALL 3 STEPS SUCCESSFULLY COMPLETED IN {time.time() - t_start:.2f}s!", flush=True)
    print("=" * 88, flush=True)


if __name__ == "__main__":
    main()

