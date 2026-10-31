"""
Module 1: Data Ingestion & Preprocessing
Subcomponent: step_1_2_timbus_master_ground_truth
File: ingest_all_active_routes.py

Bulk ingestion pipeline to extract official transit ground truth (stations, shape polylines, metadata)
from TimBus (TRAMOC / Sở GTVT Hà Nội) for ALL active routes present in telemetry.
Enforces SHA256 data integrity, linear referencing, and full audit lineage in SQLite DB.
"""

import sys

from config.system_config import get_database_path, DEFAULT_DB_PATH
import os
import time
import sqlite3
import logging
from typing import Dict, Any, List

# Ensure project root in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
sys.path.insert(0, os.path.abspath("."))

from module_1_data_ingestion_and_preprocessing.step_1_2_timbus_master_ground_truth.timbus_pipeline import TimBusGroundTruthPipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def get_active_telemetry_routes(db_path: str) -> List[Dict[str, Any]]:
    """Query all routes that exist in vehicle_unique_pings and have a mapped timbus_fleet_id."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    query = """
    SELECT DISTINCT 
        c.route_code, 
        c.timbus_fleet_id, 
        c.route_name,
        c.busmap_route_id,
        count(t.vehicle_id) as ping_count
    FROM vehicle_unique_pings t
    JOIN dim_route_crosswalk c ON t.route_id = c.busmap_route_id
    WHERE c.timbus_fleet_id IS NOT NULL
    GROUP BY c.route_code, c.timbus_fleet_id, c.route_name, c.busmap_route_id
    ORDER BY ping_count DESC;
    """
    rows = cur.execute(query).fetchall()
    conn.close()

    routes = []
    for r in rows:
        routes.append({
            "route_code": r[0],
            "timbus_fleet_id": r[1],
            "route_name": r[2],
            "busmap_route_id": r[3],
            "ping_count": r[4]
        })
    return routes


def run_bulk_ingestion(db_path: Optional[str] = None):
    """Execute bulk ingestion for all active telemetry routes."""
    if sys.stdout.encoding != 'utf-8':
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except Exception:
            pass

    print("=" * 80)
    print("TIMBUS OFFICIAL GROUND TRUTH BULK INGESTION PIPELINE (ALL 48 ACTIVE ROUTES)")
    print("Authority: Trung tâm Quản lý Giao thông công cộng Hà Nội (TRAMOC / Sở GTVT Hà Nội)")
    print("=" * 80)

    routes = get_active_telemetry_routes(db_path)
    print(f"Discovered {len(routes)} active bus routes with telemetry in database.")
    print("-" * 80)

    pipeline = TimBusGroundTruthPipeline(db_path=db_path)

    total_stations = 0
    total_shapes = 0
    successful_routes = 0
    failed_routes = []

    start_time = time.time()

    for idx, r in enumerate(routes, start=1):
        fleet_id = r["timbus_fleet_id"]
        code = r["route_code"]
        name = r["route_name"]
        pings = r["ping_count"]

        print(f"[{idx:02d}/{len(routes)}] Ingesting Route {code:<6} (FleetID: {fleet_id:<5}, Telemetry Pings: {pings:,})...", end=" ", flush=True)

        try:
            res = pipeline.process_route(fleet_id)
            st_count = res["total_stations_ingested"]
            sh_count = res["total_shape_points_ingested"]
            sha256 = res["sha256_checksum"][:12]

            total_stations += st_count
            total_shapes += sh_count
            successful_routes += 1

            print(f"OK ({st_count} st, {sh_count} pts, SHA: {sha256}...)")
        except Exception as e:
            failed_routes.append((code, fleet_id, str(e)))
            print(f"FAILED: {e}")

        # Polite delay to respect server
        time.sleep(0.2)

    elapsed = time.time() - start_time

    print("=" * 80)
    print("BULK INGESTION EXECUTION SUMMARY:")
    print(f"- Processed Routes: {successful_routes}/{len(routes)} successful ({successful_routes/len(routes)*100:.1f}%)")
    print(f"- Total Stations Extracted: {total_stations:,} official stations (WGS84, both directions)")
    print(f"- Total Centerline Shape Points: {total_shapes:,} official geometry points")
    print(f"- Elapsed Time: {elapsed:.2f} seconds (Avg: {elapsed/len(routes):.2f}s per route)")
    print(f"- Target Database: {db_path}")

    if failed_routes:
        print("\nFailed routes:")
        for fc, fid, err in failed_routes:
            print(f"  - Route {fc} (ID {fid}): {err}")
    else:
        print("\nSUCCESS: 100% of active bus routes successfully ingested into Master Ground Truth!")
    print("=" * 80)


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else get_database_path()
    run_bulk_ingestion(db)
