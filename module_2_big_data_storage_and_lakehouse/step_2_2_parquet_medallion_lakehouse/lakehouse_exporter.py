"""
Module 2: Big Data Storage & Lakehouse
Subcomponent: step_2_2_parquet_medallion_lakehouse
File: lakehouse_exporter.py

Implements the 3-Tier Medallion Lakehouse Architecture (Bronze -> Silver -> Gold)
using Apache Parquet with Snappy compression and Hive-style partitioning:
  1. Bronze Layer:
     - bronze/bus_gps_raw/dt=YYYY-MM-DD/hr=HH/part-00000.snappy.parquet
     - bronze/tomtom_incidents_raw/dt=YYYY-MM-DD/part-00000.snappy.parquet
  2. Silver Layer:
     - silver/route_projected_telemetry/route_code=XX/dt=YYYY-MM-DD/part-00000.snappy.parquet
     - silver/fact_route_tomtom_incidents/route_code=XX/part-00000.snappy.parquet
  3. Gold Layer (Two-Stage Decoupled Feature Store for Weekly Retraining SLA):
     - gold/batch_view_travel_times/part-00000.snappy.parquet
     - gold/tomtom_vs_bus_kinematics/part-00000.snappy.parquet
     - gold/kinematic_horizon_samples/route_code=XX/dt=YYYY-MM-DD/part-00000.snappy.parquet
       (Stage 1 Immutable Physical Kinematics with Weekly Delta-Partition Catch-Up +
        Stage 2 Dynamic Weekly Matrix Re-binding in <0.12s/route).
"""

import glob
import json
import os
import re
import sqlite3
import sys
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Set, Tuple

import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds_pa
import pyarrow.parquet as pq

# Ensure project root in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))
sys.path.insert(0, os.path.abspath("."))

from config.system_config import DEFAULT_DB_PATH, DEFAULT_LAKEHOUSE_ROOT, get_database_path
from module_3_bus_eta_prediction.step_3_2_feature_store_extractor.feature_extractor import (
    bind_stage2_dynamic_matrix,
    extract_route_training_dataset,
)

INCIDENTS_GLOB = "data/temp_hf_sync/raw_data/*/incidents/*.jsonl"


def export_bronze_tomtom_incidents(
    lakehouse_root: str = DEFAULT_LAKEHOUSE_ROOT,
    incidents_glob: str = INCIDENTS_GLOB,
    force_overwrite: bool = False,
) -> Dict[str, float]:
    """
    Exports raw TomTom JSONL incident batches into Bronze Parquet partitions:
    data/lakehouse/bronze/tomtom_incidents_raw/dt=YYYY-MM-DD/part-00000.snappy.parquet
    """
    bronze_inc_dir = os.path.join(lakehouse_root, "bronze", "tomtom_incidents_raw")
    os.makedirs(bronze_inc_dir, exist_ok=True)

    t0 = time.time()
    files = sorted(glob.glob(incidents_glob))
    by_date: Dict[str, List[str]] = {}
    for fpath in files:
        parts = os.path.normpath(fpath).split(os.sep)
        dt_val = next((p for p in parts if len(p) == 10 and re.match(r"^\d{4}-\d{2}-\d{2}$", p)), None)
        if dt_val:
            by_date.setdefault(dt_val, []).append(fpath)

    total_rows = 0
    new_partitions = 0
    raw_json_bytes = 0

    for dt_val, dt_files in sorted(by_date.items()):
        for fp in dt_files:
            raw_json_bytes += os.path.getsize(fp)

        out_dir = os.path.join(bronze_inc_dir, f"dt={dt_val}")
        out_file = os.path.join(out_dir, "part-00000.snappy.parquet")
        if os.path.exists(out_file) and not force_overwrite:
            total_rows += pq.read_metadata(out_file).num_rows
            continue

        rows = []
        for fp in dt_files:
            with open(fp, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                        rows.append(
                            {
                                "incident_id": str(r.get("incident_id") or ""),
                                "timestamp": str(r.get("timestamp") or ""),
                                "icon_category": int(r.get("icon_category") or 0),
                                "magnitude_of_delay": int(r.get("magnitude_of_delay") or 0),
                                "delay_seconds": int(r.get("delay_seconds") or 0),
                                "length_meters": float(r.get("length_meters") or 0.0),
                                "from_location": str(r.get("from_location") or ""),
                                "to_location": str(r.get("to_location") or ""),
                                "road_numbers": json.dumps(r.get("road_numbers") or [], ensure_ascii=False),
                                "description": str(r.get("description") or ""),
                                "coordinates_json": json.dumps(r.get("coordinates") or []),
                            }
                        )
                    except Exception:
                        pass

        if rows:
            os.makedirs(out_dir, exist_ok=True)
            df = pd.DataFrame(rows)
            df.to_parquet(out_file, engine="pyarrow", compression="snappy", index=False)
            total_rows += len(df)
            new_partitions += 1

    parquet_bytes = sum(
        os.path.getsize(os.path.join(r, fn))
        for r, _, fns in os.walk(bronze_inc_dir)
        for fn in fns
        if fn.endswith(".parquet")
    )
    return {
        "total_rows": total_rows,
        "new_partitions": new_partitions,
        "raw_json_mb": round(raw_json_bytes / (1024 * 1024), 2),
        "parquet_mb": round(parquet_bytes / (1024 * 1024), 2),
        "elapsed_sec": round(time.time() - t0, 2),
    }


def export_to_parquet_lakehouse(
    db_path: str = DEFAULT_DB_PATH,
    lakehouse_root: str = DEFAULT_LAKEHOUSE_ROOT,
    top_routes_only: Optional[int] = None,
    force_overwrite: bool = False,
) -> Dict[str, object]:
    """
    Exports Silver and Gold operational tables to Apache Parquet with Snappy compression
    and Hive-style partitioning (route_code=XX/dt=YYYY-MM-DD).
    Supports incremental partition skipping when force_overwrite=False.
    """
    print("=" * 84, flush=True)
    print("MEDALLION LAKEHOUSE EXPORTER (BRONZE -> SILVER -> GOLD APACHE PARQUET)", flush=True)
    print(f"Source DB: {db_path} | Target Lakehouse: {lakehouse_root}", flush=True)
    print("=" * 84, flush=True)

    t0 = time.time()
    bronze_stats = export_bronze_tomtom_incidents(
        lakehouse_root=lakehouse_root, force_overwrite=force_overwrite
    )
    print(
        f"[Bronze] TomTom Incidents Raw: {bronze_stats['total_rows']:,} rows | "
        f"Raw JSONL: {bronze_stats['raw_json_mb']:.2f} MB -> Snappy Parquet: {bronze_stats['parquet_mb']:.2f} MB "
        f"({bronze_stats['elapsed_sec']:.2f}s)",
        flush=True,
    )

    silver_tel_dir = os.path.join(lakehouse_root, "silver", "route_projected_telemetry")
    silver_inc_dir = os.path.join(lakehouse_root, "silver", "fact_route_tomtom_incidents")
    gold_batch_dir = os.path.join(lakehouse_root, "gold", "batch_view_travel_times")
    gold_xval_dir = os.path.join(lakehouse_root, "gold", "tomtom_vs_bus_kinematics")

    for d in (silver_tel_dir, silver_inc_dir, gold_batch_dir, gold_xval_dir):
        os.makedirs(d, exist_ok=True)

    batch_file = os.path.join(gold_batch_dir, "part-00000.snappy.parquet")
    xval_file = os.path.join(gold_xval_dir, "part-00000.snappy.parquet")

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    routes_query = """
    SELECT route_code, COUNT(ping_id) AS pings
    FROM route_projected_telemetry
    GROUP BY route_code
    ORDER BY pings DESC;
    """
    routes = cur.execute(routes_query).fetchall()
    if top_routes_only:
        routes = routes[:top_routes_only]

    total_tel_rows = 0
    total_tel_files = 0
    new_tel_files = 0

    for idx, (rc, p_count) in enumerate(routes, start=1):
        route_dir = os.path.join(silver_tel_dir, f"route_code={rc}")
        os.makedirs(route_dir, exist_ok=True)

        # Incremental check: find which dates exist in DB vs on disk
        cur.execute(
            """
            SELECT DISTINCT substr(device_update_time, 1, 10)
            FROM route_projected_telemetry
            WHERE route_code = ?
            """,
            (rc,),
        )
        db_dates = {r[0] for r in cur.fetchall() if r[0]}
        existing_dates = set()
        if not force_overwrite:
            for d_val in db_dates:
                p_file = os.path.join(route_dir, f"dt={d_val}", "part-00000.snappy.parquet")
                if os.path.exists(p_file):
                    existing_dates.add(d_val)

        missing_dates = db_dates - existing_dates
        if not missing_dates:
            total_tel_rows += int(p_count)
            total_tel_files += len(db_dates)
            continue

        df = pd.read_sql_query(
            """
            SELECT ping_id, route_id, vehicle_id, plate,
                   device_update_time, device_epoch, direction,
                   lat, lon, s_bus_m, cross_track_m, derived_speed_kmh, is_dwell,
                   substr(device_update_time, 1, 10) AS dt
            FROM route_projected_telemetry
            WHERE route_code = ? AND cross_track_m <= 35.0
            """,
            conn,
            params=[rc],
        )

        for d_val, sub_df in df.groupby("dt"):
            out_dir = os.path.join(route_dir, f"dt={d_val}")
            os.makedirs(out_dir, exist_ok=True)
            out_file = os.path.join(out_dir, "part-00000.snappy.parquet")
            if d_val in missing_dates or force_overwrite:
                clean_sub = sub_df.drop(columns=["dt"])
                clean_sub.to_parquet(out_file, engine="pyarrow", compression="snappy", index=False)
                new_tel_files += 1
            total_tel_files += 1

        total_tel_rows += len(df)
        if idx % 10 == 0 or idx == len(routes):
            print(
                f"  [Silver Telemetry {idx:02d}/{len(routes)}] Route {rc:<6} synced ({len(db_dates)} date partitions)",
                flush=True,
            )

    # Export Silver fact_route_tomtom_incidents partitioned by route_code
    existing_inc_files = glob.glob(os.path.join(silver_inc_dir, "route_code=*", "*.parquet"))
    if force_overwrite or len(existing_inc_files) == 0:
        df_inc = pd.read_sql_query("SELECT * FROM fact_route_tomtom_incidents", conn)
        for rc, sub_inc in df_inc.groupby("route_code"):
            inc_r_dir = os.path.join(silver_inc_dir, f"route_code={rc}")
            os.makedirs(inc_r_dir, exist_ok=True)
            sub_inc.drop(columns=["route_code"]).to_parquet(
                os.path.join(inc_r_dir, "part-00000.snappy.parquet"),
                engine="pyarrow",
                compression="snappy",
                index=False,
            )
        total_inc_rows = len(df_inc)
    else:
        total_inc_rows = sum(pq.read_metadata(fp).num_rows for fp in existing_inc_files)

    # Export Gold batch_view_travel_times & tomtom_vs_bus_kinematics
    if force_overwrite or new_tel_files > 0 or not os.path.exists(batch_file):
        df_batch = pd.read_sql_query("SELECT * FROM agg_segment_travel_times", conn)
        df_batch.to_parquet(
            batch_file,
            engine="pyarrow",
            compression="snappy",
            index=False,
        )
        total_batch_rows = len(df_batch)
    else:
        total_batch_rows = pq.read_metadata(batch_file).num_rows

    if force_overwrite or new_tel_files > 0 or not os.path.exists(xval_file):
        df_xval = pd.read_sql_query("SELECT * FROM agg_tomtom_vs_bus_kinematics", conn)
        df_xval.to_parquet(
            xval_file,
            engine="pyarrow",
            compression="snappy",
            index=False,
        )
        total_xval_rows = len(df_xval)
    else:
        total_xval_rows = pq.read_metadata(xval_file).num_rows

    conn.close()
    elapsed = time.time() - t0
    print("=" * 84, flush=True)
    print(
        f"[Silver & Gold Summary] Telemetry: {total_tel_rows:,} rows across {total_tel_files} partitions "
        f"({new_tel_files} newly written) | Incidents: {total_inc_rows:,} rows | "
        f"Batch View: {total_batch_rows:,} cells | Elapsed: {elapsed:.2f}s",
        flush=True,
    )
    print("=" * 84, flush=True)
    return {
        "bronze": bronze_stats,
        "silver_telemetry_rows": total_tel_rows,
        "silver_telemetry_partitions": total_tel_files,
        "silver_incident_rows": total_inc_rows,
        "gold_batch_cells": total_batch_rows,
        "gold_xval_pairs": total_xval_rows,
        "elapsed_sec": round(elapsed, 2),
    }


def sync_route_stage1_kinematic_parquet(
    route_code: str,
    db_path: Optional[str] = None,
    lakehouse_root: str = DEFAULT_LAKEHOUSE_ROOT,
    force_overwrite: bool = False,
) -> Dict[str, object]:
    """
    Stage 1 Weekly Delta-Partition Catch-Up:
    Checks which dates `dt=YYYY-MM-DD` exist in Silver `route_projected_telemetry/route_code=XX`
    (with fallback to SQLite if Silver Parquet is not materialized yet)
    vs. which `dt=YYYY-MM-DD` partitions are already materialized in:
      `data/lakehouse/gold/kinematic_horizon_samples/route_code=XX/dt=YYYY-MM-DD/part-00000.snappy.parquet`
    Extracts Stage 1 immutable physical kinematics ONLY for missing dates!
    """
    t0 = time.time()
    resolved_db = db_path or str(get_database_path())
    route_gold_dir = os.path.join(
        lakehouse_root, "gold", "kinematic_horizon_samples", f"route_code={route_code}"
    )
    os.makedirs(route_gold_dir, exist_ok=True)

    silver_route_dir = os.path.join(
        lakehouse_root, "silver", "route_projected_telemetry", f"route_code={route_code}"
    )
    silver_dt_dirs = sorted(glob.glob(os.path.join(silver_route_dir, "dt=*")))
    if silver_dt_dirs:
        db_dates = [
            os.path.basename(d).replace("dt=", "")
            for d in silver_dt_dirs
            if os.path.exists(os.path.join(d, "part-00000.snappy.parquet"))
        ]
    else:
        conn = sqlite3.connect(resolved_db)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT DISTINCT substr(device_update_time, 1, 10)
            FROM route_projected_telemetry
            WHERE route_code = ? AND cross_track_m <= 35.0
            ORDER BY 1 ASC
            """,
            (route_code,),
        )
        db_dates = [r[0] for r in cur.fetchall() if r[0]]
        conn.close()

    existing_dates: Set[str] = set()
    if not force_overwrite:
        for d_val in db_dates:
            dt_dir = os.path.join(route_gold_dir, f"dt={d_val}")
            p_file = os.path.join(dt_dir, "part-00000.snappy.parquet")
            empty_marker = os.path.join(dt_dir, "_EMPTY_PARTITION")
            if os.path.exists(p_file) or os.path.exists(empty_marker):
                existing_dates.add(d_val)

    missing_dates = set(db_dates) - existing_dates
    newly_written_rows = 0

    if missing_dates:
        df_new = extract_route_training_dataset(
            route_code,
            db_path=resolved_db,
            include_tomtom=True,
            target_dates=missing_dates,
            lakehouse_root=lakehouse_root,
        )
        written_dates: Set[str] = set()
        if not df_new.empty:
            for d_val, sub_df in df_new.groupby("dt"):
                out_dir = os.path.join(route_gold_dir, f"dt={d_val}")
                os.makedirs(out_dir, exist_ok=True)
                out_file = os.path.join(out_dir, "part-00000.snappy.parquet")
                sub_df.to_parquet(out_file, engine="pyarrow", compression="snappy", index=False)
                newly_written_rows += len(sub_df)
                written_dates.add(str(d_val))
        # Mark any date in missing_dates that had <5 valid corridor pings with _EMPTY_PARTITION
        # so subsequent calls never re-run extraction on empty dates (fixes Route E05 / E06).
        for d_val in missing_dates - written_dates:
            out_dir = os.path.join(route_gold_dir, f"dt={d_val}")
            os.makedirs(out_dir, exist_ok=True)
            empty_marker = os.path.join(out_dir, "_EMPTY_PARTITION")
            with open(empty_marker, "w", encoding="utf-8") as mf:
                mf.write("0\n")

    return {
        "route_code": route_code,
        "total_dates": len(db_dates),
        "cached_dates": len(existing_dates),
        "missing_dates_processed": len(missing_dates),
        "newly_written_rows": newly_written_rows,
        "elapsed_sec": round(time.time() - t0, 3),
    }


def load_route_dataset_from_lakehouse(
    route_code: str,
    db_path: Optional[str] = None,
    lakehouse_root: str = DEFAULT_LAKEHOUSE_ROOT,
    rebind_latest_matrix: bool = True,
    min_date: Optional[str] = None,
    columns: Optional[List[str]] = None,
    skip_sync: bool = False,
) -> Tuple[pd.DataFrame, Dict[str, float]]:
    """
    Loads Stage 1 immutable physical kinematic samples from Apache Parquet partitions
    using PyArrow C++ multi-threaded Dataset reader (materializing any missing dates
    first via `sync_route_stage1_kinematic_parquet`), and runs Stage 2 Dynamic Matrix
    Re-binding (`bind_stage2_dynamic_matrix`) so that all samples reflect the latest
    Weekly `agg_segment_travel_times` matrix!
    """
    resolved_db = db_path or str(get_database_path())
    if skip_sync:
        sync_info = {"elapsed_sec": 0.0, "missing_dates_processed": 0}
    else:
        sync_info = sync_route_stage1_kinematic_parquet(
            route_code, db_path=resolved_db, lakehouse_root=lakehouse_root
        )

    t_read = time.time()
    route_gold_dir = os.path.join(
        lakehouse_root, "gold", "kinematic_horizon_samples", f"route_code={route_code}"
    )
    parquet_files = [
        fp for fp in sorted(glob.glob(os.path.join(route_gold_dir, "dt=*", "*.parquet")))
        if os.path.getsize(fp) > 2048
    ]
    if min_date:
        parquet_files = [
            fp for fp in parquet_files
            if os.path.basename(os.path.dirname(fp)).replace("dt=", "") >= min_date
        ]

    if parquet_files:
        dataset_pa = ds_pa.dataset(parquet_files, format="parquet")
        table_pa = dataset_pa.to_table(columns=columns, use_threads=True)
        df = table_pa.to_pandas()
    else:
        df = pd.DataFrame()
    read_sec = time.time() - t_read

    t_bind = time.time()
    if rebind_latest_matrix and not df.empty:
        df = bind_stage2_dynamic_matrix(df, route_code, db_path=resolved_db, inplace=True)
    bind_sec = time.time() - t_bind

    timing = {
        "delta_sync_sec": float(sync_info["elapsed_sec"]),
        "missing_dates_processed": int(sync_info["missing_dates_processed"]),
        "parquet_read_sec": round(read_sec, 4),
        "stage2_matrix_bind_sec": round(bind_sec, 4),
        "total_load_and_bind_sec": round(read_sec + bind_sec, 4),
    }
    return df, timing


def _worker_sync_and_benchmark_route(args: Tuple[str, str, str, bool]) -> Dict[str, object]:
    """
    Worker function for parallel execution across routes:
      1. Syncs Stage 1 Parquet partitions (or forces full rebuild if force_overwrite=True)
      2. Loads Parquet via PyArrow Dataset + runs Stage 2 Dynamic Matrix Re-binding
      3. Returns exact row counts, partition counts, and timing breakdown.
    """
    rc, db_path, lakehouse_root, force_overwrite = args
    t0 = time.time()
    sync_res = sync_route_stage1_kinematic_parquet(
        rc, db_path=db_path, lakehouse_root=lakehouse_root, force_overwrite=force_overwrite
    )
    df, load_timing = load_route_dataset_from_lakehouse(
        rc, db_path=db_path, lakehouse_root=lakehouse_root, rebind_latest_matrix=True, skip_sync=True
    )
    return {
        "route_code": rc,
        "n_samples": len(df),
        "total_dates": int(sync_res["total_dates"]),
        "missing_dates_processed": int(sync_res["missing_dates_processed"]),
        "stage1_sync_sec": float(sync_res["elapsed_sec"]),
        "parquet_read_sec": float(load_timing["parquet_read_sec"]),
        "stage2_bind_sec": float(load_timing["stage2_matrix_bind_sec"]),
        "total_load_and_bind_sec": float(load_timing["total_load_and_bind_sec"]),
        "worker_wall_sec": round(time.time() - t0, 3),
    }


def parallel_sync_all_routes_stage1_parquet(
    routes: List[str],
    db_path: str = DEFAULT_DB_PATH,
    lakehouse_root: str = DEFAULT_LAKEHOUSE_ROOT,
    max_workers: Optional[int] = None,
    force_overwrite: bool = False,
) -> Dict[str, object]:
    """
    Executes Stage 1 Parquet sync and Stage 2 dynamic matrix re-binding across
    multiple routes in parallel. Uses ProcessPoolExecutor when extracting raw
    Python kinematics (`force_overwrite=True`) and ThreadPoolExecutor when reading
    cached Parquet + running NumPy C++/SIMD Stage 2 matrix re-binding (`force_overwrite=False`)
    to avoid Windows process spawn & IPC pickling overhead.
    """
    workers = max_workers or min(8, os.cpu_count() or 4)
    t_wall = time.time()
    tasks = [(rc, db_path, lakehouse_root, force_overwrite) for rc in routes]
    results: List[Dict[str, object]] = []

    executor_cls = ProcessPoolExecutor if force_overwrite else ThreadPoolExecutor
    with executor_cls(max_workers=workers) as pool:
        futures = {pool.submit(_worker_sync_and_benchmark_route, t): t[0] for t in tasks}
        for idx, fut in enumerate(as_completed(futures), start=1):
            res = fut.result()
            results.append(res)
            if idx % 8 == 0 or idx == len(routes):
                print(
                    f"  [Parallel Stage 1+2 {idx:02d}/{len(routes)}] Route {res['route_code']:<6} | "
                    f"Samples: {res['n_samples']:>7,} | Sync: {res['stage1_sync_sec']:.2f}s | "
                    f"Read+Bind: {res['total_load_and_bind_sec']:.3f}s",
                    flush=True,
                )

    wall_sec = time.time() - t_wall
    sum_cpu_sync_sec = sum(float(r["stage1_sync_sec"]) for r in results)
    sum_cpu_load_bind_sec = sum(float(r["total_load_and_bind_sec"]) for r in results)
    total_samples = sum(int(r["n_samples"]) for r in results)

    return {
        "n_routes": len(routes),
        "max_workers": workers,
        "total_samples": total_samples,
        "wall_sec": round(wall_sec, 2),
        "sum_single_thread_sync_sec": round(sum_cpu_sync_sec, 2),
        "sum_single_thread_load_bind_sec": round(sum_cpu_load_bind_sec, 2),
        "parallel_speedup_ratio": round((sum_cpu_sync_sec + sum_cpu_load_bind_sec) / max(wall_sec, 0.01), 2),
        "per_route": sorted(results, key=lambda x: int(x["n_samples"]), reverse=True),
    }


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DB_PATH
    lake = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_LAKEHOUSE_ROOT
    force = "--force" in sys.argv
    export_to_parquet_lakehouse(db, lake, force_overwrite=force)
