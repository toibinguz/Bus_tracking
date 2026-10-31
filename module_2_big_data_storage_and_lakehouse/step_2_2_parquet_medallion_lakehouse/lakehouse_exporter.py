"""
Module 2: Big Data Storage & Lakehouse
Subcomponent: step_2_2_parquet_medallion_lakehouse
File: lakehouse_exporter.py

Exports clean projected telemetry from SQLite operational store into a high-performance
columnar Parquet Lakehouse (Medallion Silver Layer) partitioned by date and route_code.
Enforces Snappy compression, columnar memory efficiency, and PyArrow/DuckDB interoperability.
"""

import os
import sys

from config.system_config import get_database_path, DEFAULT_DB_PATH
import sqlite3
import time
import pandas as pd
from typing import Optional

# Ensure project root in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))
sys.path.insert(0, os.path.abspath("."))


# Centralized in config.system_config
# DEFAULT_DB_PATH is imported from config.system_config
DEFAULT_LAKEHOUSE_ROOT = "data/lakehouse"


def export_to_parquet_lakehouse(
    db_path: str = DEFAULT_DB_PATH,
    lakehouse_root: str = DEFAULT_LAKEHOUSE_ROOT,
    top_routes_only: Optional[int] = None
):
    """Export route_projected_telemetry to partitioned Parquet files."""
    print("=" * 80)
    print("MEDALLION LAKEHOUSE EXPORTER (BRONZE -> SILVER PARQUET)")
    print(f"Source DB: {db_path} | Target Lakehouse: {lakehouse_root}")
    print("=" * 80)

    silver_dir = os.path.join(lakehouse_root, "silver", "route_telemetry")
    os.makedirs(silver_dir, exist_ok=True)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Get list of routes
    routes_query = """
    SELECT route_code, count(ping_id) as pings
    FROM route_projected_telemetry
    GROUP BY route_code
    ORDER BY pings DESC;
    """
    routes = cur.execute(routes_query).fetchall()
    if top_routes_only:
        routes = routes[:top_routes_only]

    print(f"Found {len(routes)} routes in route_projected_telemetry.")
    t0 = time.time()
    total_exported_rows = 0
    total_files = 0

    for idx, (rc, p_count) in enumerate(routes, start=1):
        df = pd.read_sql_query("""
            SELECT 
                ping_id, route_code, route_id, vehicle_id, plate,
                device_update_time, device_epoch, direction,
                lat, lon, s_bus_m, cross_track_m, derived_speed_kmh, is_dwell,
                substr(device_update_time, 1, 10) as date_partition
            FROM route_projected_telemetry
            WHERE route_code = ?;
        """, conn, params=[rc])

        if df.empty:
            continue

        # Export partitioned by date_partition and route_code
        dates = df["date_partition"].unique()
        for d in dates:
            sub_df = df[df["date_partition"] == d].copy()
            # Drop partition column to avoid redundancy
            sub_df = sub_df.drop(columns=["date_partition"])

            out_dir = os.path.join(silver_dir, f"date={d}", f"route_code={rc}")
            os.makedirs(out_dir, exist_ok=True)
            out_file = os.path.join(out_dir, "data.parquet")

            # Write parquet with snappy compression
            sub_df.to_parquet(out_file, engine="pyarrow", compression="snappy", index=False)
            total_files += 1

        total_exported_rows += len(df)
        print(f"[{idx:02d}/{len(routes)}] Exported Route {rc:<6} ({len(df):,} rows -> {len(dates)} date partitions)")

    elapsed = time.time() - t0
    conn.close()

    print("=" * 80)
    print("MEDALLION EXPORT SUMMARY:")
    print(f"- Total Rows Exported: {total_exported_rows:,}")
    print(f"- Total Parquet Partitions Created: {total_files}")
    print(f"- Elapsed Time: {elapsed:.2f} seconds")
    print(f"- Storage Location: {silver_dir}")
    print("=" * 80)


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DB_PATH
    lake = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_LAKEHOUSE_ROOT
    export_to_parquet_lakehouse(db, lake)

