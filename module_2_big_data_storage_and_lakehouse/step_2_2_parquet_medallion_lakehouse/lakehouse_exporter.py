"""
Module 2: Big Data Storage & Lakehouse
Subcomponent: step_2_2_parquet_medallion_lakehouse
File: lakehouse_exporter.py

Implements Medallion Lakehouse Architecture (Bronze & Silver Tiers)
using Apache Parquet with Snappy compression and Hive-style partitioning:
  1. Bronze Layer:
     - bronze/tomtom_incidents_raw/dt=YYYY-MM-DD/part-00000.snappy.parquet
  2. Silver Layer:
     - silver/route_projected_telemetry/route_code=XX/dt=YYYY-MM-DD/part-00000.snappy.parquet
       (Strict on-corridor constraint: cross_track_m <= 35.0m, monotonic progression, GTFS direction)
     - silver/fact_route_tomtom_incidents/route_code=XX/part-00000.snappy.parquet
"""

import glob
import json
import os
import re
import sqlite3
import sys
import time
from typing import Dict, List, Optional, Set, Tuple

import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds_pa
import pyarrow.parquet as pq

# Ensure project root in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))
sys.path.insert(0, os.path.abspath("."))

from config.system_config import (
    DEFAULT_DB_PATH,
    DEFAULT_LAKEHOUSE_ROOT,
    RAW_DATA_DIR,
    MAX_CORRIDOR_CROSS_TRACK_M,
    get_database_path,
)

INCIDENTS_GLOB = f"{RAW_DATA_DIR}/*/incidents/*.jsonl"


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
    Exports Bronze and Silver operational tables to Apache Parquet with Snappy compression
    and Hive-style partitioning (route_code=XX/dt=YYYY-MM-DD).
    Strictly filters out off-corridor pings (cross_track_m <= 35.0m).
    """
    print("=" * 84, flush=True)
    print("MEDALLION LAKEHOUSE EXPORTER (BRONZE & SILVER APACHE PARQUET)", flush=True)
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

    for d in (silver_tel_dir, silver_inc_dir):
        os.makedirs(d, exist_ok=True)

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
        if not missing_dates and not force_overwrite:
            # Read existing partition row count quickly
            for d_val in db_dates:
                p_file = os.path.join(route_dir, f"dt={d_val}", "part-00000.snappy.parquet")
                if os.path.exists(p_file):
                    total_tel_rows += pq.read_metadata(p_file).num_rows
                    total_tel_files += 1
            continue

        df = pd.read_sql_query(
            """
            SELECT ping_id, route_id, vehicle_id, plate,
                   device_update_time, device_epoch, direction,
                   lat, lon, s_bus_m, cross_track_m, derived_speed_kmh,
                   substr(device_update_time, 1, 10) AS dt
            FROM route_projected_telemetry
            WHERE route_code = ? AND cross_track_m <= ?
            """,
            conn,
            params=[rc, MAX_CORRIDOR_CROSS_TRACK_M],
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

    conn.close()
    elapsed = time.time() - t0
    print("=" * 84, flush=True)
    print(
        f"[Silver Summary] Telemetry: {total_tel_rows:,} rows across {total_tel_files} partitions "
        f"({new_tel_files} newly written) | Incidents: {total_inc_rows:,} rows | Elapsed: {elapsed:.2f}s",
        flush=True,
    )
    print("=" * 84, flush=True)
    return {
        "bronze": bronze_stats,
        "silver_telemetry_rows": total_tel_rows,
        "silver_telemetry_partitions": total_tel_files,
        "silver_incident_rows": total_inc_rows,
        "elapsed_sec": round(elapsed, 2),
    }


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else DEFAULT_DB_PATH
    lake = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else DEFAULT_LAKEHOUSE_ROOT
    force = "--force" in sys.argv
    export_to_parquet_lakehouse(db, lake, force_overwrite=force)
