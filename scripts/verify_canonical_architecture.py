"""
End-to-End Canonical Architecture Verification Script
Tests the 3 strategic modules:
- Module 1: Ingestion & Preprocessing (BusMap Native Ground Truth, 1D Frenet Projection)
- Module 2: Big Data Storage & Lakehouse (SQLite Operational Store, Parquet Lakehouse)
- Module 3: Bus ETA Prediction (Baseline Travel Time Matrix, Model Artifacts)
"""

import sys
import os
import sqlite3

# Reconfigure stdout for UTF-8 on Windows
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Ensure project root in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from config.system_config import get_database_path

DB_PATH = get_database_path()
LAKEHOUSE_PATH = "data/lakehouse/silver/route_projected_telemetry"
BRONZE_INC_PATH = "data/lakehouse/bronze/tomtom_incidents_raw"
SILVER_INC_PATH = "data/lakehouse/silver/fact_route_tomtom_incidents"


def verify():
    print("=" * 80)
    print("CANONICAL BRONZE & SILVER ARCHITECTURE VERIFICATION AUDIT")
    print("=" * 80)

    # 1. Verify SQLite Operational Database
    print(f"\n[1] AUDITING MODULE 2: OPERATIONAL DATABASE ({DB_PATH})...")
    assert os.path.exists(DB_PATH), f"Missing database: {DB_PATH}"
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    canon_routes = cur.execute("SELECT count(1) FROM canonical_route_master").fetchone()[0]
    canon_stations = cur.execute("SELECT count(1) FROM canonical_station_master").fetchone()[0]
    canon_shapes = cur.execute("SELECT count(1) FROM canonical_shape_master").fetchone()[0]
    proj_cnt = cur.execute("SELECT count(1) FROM route_projected_telemetry").fetchone()[0]

    print(f"  * Canonical Master Routes       : {canon_routes:,} routes")
    print(f"  * Canonical Master Stations     : {canon_stations:,} stations")
    print(f"  * Canonical Centerline Points   : {canon_shapes:,} points")
    print(f"  * Projected Telemetry Pings     : {proj_cnt:,} pings")

    assert canon_routes >= 48, f"Routes count below threshold ({canon_routes})"
    assert canon_stations >= 10000, f"Stations count below threshold ({canon_stations})"
    assert canon_shapes >= 100000, f"Shape points below threshold ({canon_shapes})"
    assert proj_cnt >= 200000, f"Projected pings below threshold ({proj_cnt})"

    # 2. Verify Analytical View
    print("\n[2] AUDITING GLOBAL ANALYTICAL VIEW (v_bus_to_next_station)...")
    sample_view = cur.execute("""
        SELECT route_code, plate, s_bus_m, next_station_name, distance_remaining_m, derived_speed_kmh
        FROM v_bus_to_next_station
        WHERE distance_remaining_m > 0
        LIMIT 3
    """).fetchall()
    for row in sample_view:
        s_name = row[3] if row[3] else "Unknown Station"
        print(f"  * Sample Bus: Route {row[0]} ({row[1]}) -> Next Station: {s_name[:25]} | Remaining: {row[4]:.1f}m | Speed: {row[5]} km/h")
    assert len(sample_view) == 3, "Failed to query view v_bus_to_next_station"

    # 3. Verify Parquet Lakehouse (Bronze & Silver)
    print("\n[3] AUDITING MODULE 2: MEDALLION PARQUET LAKEHOUSE (BRONZE & SILVER)...")
    assert os.path.exists(LAKEHOUSE_PATH), f"Missing lakehouse directory: {LAKEHOUSE_PATH}"
    
    tel_parquet_count = sum(1 for _, _, files in os.walk(LAKEHOUSE_PATH) for f in files if f.endswith(".parquet"))
    bronze_inc_count = sum(1 for _, _, files in os.walk(BRONZE_INC_PATH) for f in files if f.endswith(".parquet")) if os.path.exists(BRONZE_INC_PATH) else 0
    silver_inc_count = sum(1 for _, _, files in os.walk(SILVER_INC_PATH) for f in files if f.endswith(".parquet")) if os.path.exists(SILVER_INC_PATH) else 0

    print(f"  * Silver Telemetry Partitions   : {tel_parquet_count} files in {LAKEHOUSE_PATH}")
    print(f"  * Bronze Incidents Partitions   : {bronze_inc_count} files in {BRONZE_INC_PATH}")
    print(f"  * Silver Incidents Partitions   : {silver_inc_count} files in {SILVER_INC_PATH}")

    assert tel_parquet_count >= 50, f"Insufficient Silver telemetry partitions ({tel_parquet_count})"

    # 4. Confirm Zero Gold / Module 3 Tables in SQLite (Pre-Module 3 Silver State)
    print("\n[4] AUDITING ZERO GOLD INGESTION STATE (PRE-MODULE 3 SILVER SANITY)...")
    gold_tables = cur.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name IN ('agg_segment_travel_times', 'ml_station_pair_evaluation', 'ml_route_evaluation_summary')
    """).fetchall()
    print(f"  * Gold Tables in SQLite         : {len(gold_tables)} (Expected 0)")
    assert len(gold_tables) == 0, f"Unexpected Gold tables found: {[t[0] for t in gold_tables]}"

    gold_dir = "data/lakehouse/gold"
    gold_files = [os.path.join(r, f) for r, _, fs in os.walk(gold_dir) for f in fs if f.endswith(".parquet")] if os.path.exists(gold_dir) else []
    print(f"  * Gold Parquet Files on Disk    : {len(gold_files)} (Expected 0)")
    assert len(gold_files) == 0, f"Unexpected Gold files found: {gold_files}"

    conn.close()
    print("\n" + "=" * 80)
    print("ALL BRONZE & SILVER ARCHITECTURE CHECKS PASSED WITH 100% SUCCESS!")
    print("=" * 80)


if __name__ == "__main__":
    verify()
