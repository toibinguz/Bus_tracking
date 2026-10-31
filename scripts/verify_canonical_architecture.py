"""
End-to-End Canonical Architecture Verification Script
Tests the 3 strategic modules:
- Module 1: Ingestion & Preprocessing (TimBus Ground Truth, 1D Frenet Projection)
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
LAKEHOUSE_PATH = "data/lakehouse/silver/route_telemetry"


def verify():
    print("=" * 80)
    print("CANONICAL 3-TIER ARCHITECTURE VERIFICATION AUDIT")
    print("=" * 80)

    # 1. Verify SQLite Operational Database
    print(f"\n[1] AUDITING MODULE 2: OPERATIONAL DATABASE ({DB_PATH})...")
    assert os.path.exists(DB_PATH), f"Missing database: {DB_PATH}"
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    routes_cnt = cur.execute("SELECT count(1) FROM timbus_route_master").fetchone()[0]
    stations_cnt = cur.execute("SELECT count(1) FROM timbus_station_master").fetchone()[0]
    shapes_cnt = cur.execute("SELECT count(1) FROM timbus_shape_master").fetchone()[0]
    crosswalk_cnt = cur.execute("SELECT count(1) FROM dim_station_crosswalk").fetchone()[0]
    proj_cnt = cur.execute("SELECT count(1) FROM route_projected_telemetry").fetchone()[0]

    print(f"  * Master Routes Extracted       : {routes_cnt} routes (Target: 48)")
    print(f"  * Master Stations WGS84         : {stations_cnt:,} stations")
    print(f"  * Master Centerline Polyline    : {shapes_cnt:,} points")
    print(f"  * Station Crosswalk Records     : {crosswalk_cnt:,} records")
    print(f"  * Projected Telemetry Pings     : {proj_cnt:,} pings")

    assert routes_cnt >= 40, "Routes count below threshold"
    assert stations_cnt >= 3000, "Stations count below threshold"
    assert proj_cnt >= 200000, "Projected pings below threshold"

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

    # 3. Verify Parquet Lakehouse
    print("\n[3] AUDITING MODULE 2: MEDALLION PARQUET LAKEHOUSE...")
    assert os.path.exists(LAKEHOUSE_PATH), f"Missing lakehouse directory: {LAKEHOUSE_PATH}"
    parquet_count = 0
    for root, dirs, files in os.walk(LAKEHOUSE_PATH):
        for f in files:
            if f.endswith(".parquet"):
                parquet_count += 1
    print(f"  * Parquet Partitions Created    : {parquet_count} files in {LAKEHOUSE_PATH}")
    assert parquet_count >= 50, "Insufficient Parquet partitions"

    # 4. Verify Model Artifacts
    print("\n[4] AUDITING MODULE 3: BUS ETA TRAINED MODELS & ARTIFACTS...")
    model_file = "models/xgboost_eta_route_02.json"
    assert os.path.exists(model_file), f"Missing model artifact: {model_file}"
    model_size_kb = os.path.getsize(model_file) / 1024
    print(f"  * Model Artifact Found          : {model_file} ({model_size_kb:.1f} KB)")

    # 5. Check Gold Matrix Schema
    has_matrix_table = cur.execute("SELECT count(1) FROM sqlite_master WHERE type='table' AND name='agg_segment_travel_times'").fetchone()[0]
    print(f"  * Gold Travel Time Matrix Table : {'Present' if has_matrix_table else 'Missing'}")
    assert has_matrix_table == 1, "Missing Gold table agg_segment_travel_times"

    conn.close()
    print("\n" + "=" * 80)
    print("ALL VERIFICATION CHECKS PASSED WITH 100% SUCCESS!")
    print("=" * 80)


if __name__ == "__main__":
    verify()
