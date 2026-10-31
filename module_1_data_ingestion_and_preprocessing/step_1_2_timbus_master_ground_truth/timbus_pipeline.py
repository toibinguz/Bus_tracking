"""
Module 2: OpenStreetMap Ground-Truth & Official Road Network Layer
Subcomponent: step_2_4_timbus_official_ground_truth_extractor
File: timbus_pipeline.py

Pipeline orchestrator for extracting official bus station catalogs and road polylines
from TimBus (TRAMOC / Transerco), enforcing auditability, data contracts, and traceability.
"""

from datetime import datetime, timezone
import hashlib
import json
import logging
import math
import os

from config.system_config import get_database_path, DEFAULT_DB_PATH
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from .timbus_client import TimBusClient

logger = logging.getLogger(__name__)

EARTH_RADIUS_METERS = 6371000.0


def haversine_distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate Great Circle distance between two points in meters."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (math.sin(delta_phi / 2.0) ** 2 +
         math.cos(phi1) * math.cos(phi2) * (math.sin(delta_lambda / 2.0) ** 2))
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return EARTH_RADIUS_METERS * c


class TimBusGroundTruthPipeline:
    """
    Ingestion pipeline for official transit stations & route shapes with full lineage.
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        raw_storage_dir: str = "data/ground_truth/timbus_official/raw",
        client: Optional[TimBusClient] = None,
    ):
        self.db_path = db_path
        self.raw_storage_dir = raw_storage_dir
        self.client = client or TimBusClient()
        os.makedirs(self.raw_storage_dir, exist_ok=True)
        self._init_sqlite_schema()

    def _init_sqlite_schema(self) -> None:
        """Create normalized master tables and audit log if not existing."""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()

            # 1. Route Master Table
            cur.execute("""
            CREATE TABLE IF NOT EXISTS timbus_route_master (
                fleet_id INTEGER PRIMARY KEY,
                route_code TEXT NOT NULL,
                route_name TEXT NOT NULL,
                enterprise TEXT,
                operations_time TEXT,
                frequency TEXT,
                bus_count INTEGER,
                ticket_cost TEXT,
                first_station TEXT,
                last_station TEXT,
                extracted_at TEXT NOT NULL,
                raw_sha256 TEXT NOT NULL,
                source TEXT NOT NULL
            );
            """)

            # 2. Station Master Table (Dimensional Table for ETA & Map-Matching)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS timbus_station_master (
                route_code TEXT NOT NULL,
                direction TEXT NOT NULL,
                station_order INTEGER NOT NULL,
                station_id INTEGER NOT NULL,
                station_code TEXT,
                station_name TEXT NOT NULL,
                fleet_over TEXT,
                lat REAL NOT NULL,
                lon REAL NOT NULL,
                cum_distance_m REAL,
                extracted_at TEXT NOT NULL,
                raw_sha256 TEXT NOT NULL,
                source TEXT NOT NULL,
                PRIMARY KEY (route_code, direction, station_order)
            );
            """)

            # 3. Shape Polyline Master Table (Road Centerline)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS timbus_shape_master (
                route_code TEXT NOT NULL,
                direction TEXT NOT NULL,
                point_order INTEGER NOT NULL,
                lat REAL NOT NULL,
                lon REAL NOT NULL,
                cum_distance_m REAL NOT NULL,
                PRIMARY KEY (route_code, direction, point_order)
            );
            """)

            # 4. Data Lineage Audit Log (Mandatory Governance & Traceability)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS pipeline_data_lineage_audit (
                audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                pipeline_name TEXT NOT NULL,
                source_system TEXT NOT NULL,
                source_endpoint TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                records_count INTEGER NOT NULL,
                checksum_sha256 TEXT NOT NULL,
                file_path TEXT NOT NULL,
                execution_timestamp TEXT NOT NULL,
                execution_status TEXT NOT NULL,
                notes TEXT
            );
            """)
            conn.commit()

    def process_route(self, fleet_id: str | int) -> Dict[str, Any]:
        """
        Extract, validate, persist raw JSON with envelope, compute linear geometries,
        and upsert into master database with complete audit trail.
        """
        extracted_at = datetime.now(timezone.utc).isoformat()
        res = self.client.fetch_fleet_detail(fleet_id)
        raw_text = res["raw_text"]
        dt = res["data"]

        # Calculate cryptographic checksum for integrity verification
        sha256_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()

        route_code = str(dt.get("Code", str(fleet_id))).strip()
        route_name = str(dt.get("Name", "")).strip()

        # Build raw storage payload with provenance metadata
        raw_filename = f"route_{route_code}.json"
        raw_filepath = os.path.join(self.raw_storage_dir, raw_filename)

        envelope = {
            "lineage_metadata": {
                "source_system": "TRAMOC / TimBus (Transerco - So GTVT Ha Noi)",
                "source_endpoint": self.client.endpoint_url,
                "action": "fleetdetail",
                "fleet_id": str(fleet_id),
                "route_code": route_code,
                "route_name": route_name,
                "extracted_at_utc": extracted_at,
                "sha256_checksum": sha256_hash,
                "pipeline_version": "1.0.0",
                "purpose": "Ground-truth station locations & official route centerline for ETA prediction"
            },
            "raw_payload": dt
        }

        with open(raw_filepath, "w", encoding="utf-8") as f:
            json.dump(envelope, f, ensure_ascii=False, indent=2)

        # Process Directions: 'Go' (Forward) and 'Re' (Backward)
        directions_data = [
            ("go", dt.get("Go", {})),
            ("re", dt.get("Re", {}))
        ]

        total_stations = 0
        total_points = 0

        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()

            # Upsert Route Master
            cur.execute("""
            INSERT INTO timbus_route_master (
                fleet_id, route_code, route_name, enterprise, operations_time,
                frequency, bus_count, ticket_cost, first_station, last_station,
                extracted_at, raw_sha256, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(fleet_id) DO UPDATE SET
                route_code=excluded.route_code,
                route_name=excluded.route_name,
                enterprise=excluded.enterprise,
                operations_time=excluded.operations_time,
                frequency=excluded.frequency,
                bus_count=excluded.bus_count,
                ticket_cost=excluded.ticket_cost,
                first_station=excluded.first_station,
                last_station=excluded.last_station,
                extracted_at=excluded.extracted_at,
                raw_sha256=excluded.raw_sha256,
                source=excluded.source;
            """, (
                int(dt.get("FleetID", fleet_id)),
                route_code,
                route_name,
                dt.get("Enterprise", ""),
                dt.get("OperationsTime", ""),
                dt.get("Frequency", ""),
                int(dt.get("BusCount") or 0),
                dt.get("Cost", ""),
                dt.get("FirstStation", ""),
                dt.get("LastStation", ""),
                extracted_at,
                sha256_hash,
                "TRAMOC/TimBus"
            ))

            for dir_name, dir_obj in directions_data:
                if not dir_obj:
                    continue

                # 1. Process Shape Polyline and calculate cumulative distances
                geo_points = dir_obj.get("Geo", [])
                shape_records = []
                cum_dist = 0.0

                for p_idx, pt in enumerate(geo_points):
                    p_lat = float(pt.get("Lat", 0.0))
                    p_lon = float(pt.get("Lng", 0.0))

                    if p_idx > 0:
                        prev_lat = shape_records[-1][3]
                        prev_lon = shape_records[-1][4]
                        cum_dist += haversine_distance_meters(prev_lat, prev_lon, p_lat, p_lon)

                    shape_records.append((
                        route_code,
                        dir_name,
                        p_idx,
                        p_lat,
                        p_lon,
                        round(cum_dist, 2)
                    ))

                # Clear and insert shape
                cur.execute("DELETE FROM timbus_shape_master WHERE route_code=? AND direction=?",
                            (route_code, dir_name))
                cur.executemany("""
                INSERT INTO timbus_shape_master (
                    route_code, direction, point_order, lat, lon, cum_distance_m
                ) VALUES (?, ?, ?, ?, ?, ?);
                """, shape_records)
                total_points += len(shape_records)

                # 2. Process Stations and project along the centerline
                stations = dir_obj.get("Station", [])
                station_records = []

                for s_idx, st in enumerate(stations):
                    s_id = int(st.get("ObjectID", 0))
                    s_code = str(st.get("Code", "")).strip()
                    s_name = str(st.get("Name", "")).strip()
                    s_fleet_over = str(st.get("FleetOver", "")).strip()
                    s_geo = st.get("Geo", {})
                    s_lat = float(s_geo.get("Lat", 0.0))
                    s_lon = float(s_geo.get("Lng", 0.0))

                    # Find closest point on shape polyline for linear referencing s_k
                    s_cum_dist = 0.0
                    if shape_records:
                        min_dist = float("inf")
                        best_cum = 0.0
                        for shp in shape_records:
                            d = haversine_distance_meters(s_lat, s_lon, shp[3], shp[4])
                            if d < min_dist:
                                min_dist = d
                                best_cum = shp[5]
                        s_cum_dist = best_cum

                    station_records.append((
                        route_code,
                        dir_name,
                        s_idx,
                        s_id,
                        s_code,
                        s_name,
                        s_fleet_over,
                        s_lat,
                        s_lon,
                        s_cum_dist,
                        extracted_at,
                        sha256_hash,
                        "TRAMOC/TimBus"
                    ))

                cur.execute("DELETE FROM timbus_station_master WHERE route_code=? AND direction=?",
                            (route_code, dir_name))
                cur.executemany("""
                INSERT INTO timbus_station_master (
                    route_code, direction, station_order, station_id, station_code,
                    station_name, fleet_over, lat, lon, cum_distance_m,
                    extracted_at, raw_sha256, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, station_records)
                total_stations += len(station_records)

            # Record audit lineage entry
            cur.execute("""
            INSERT INTO pipeline_data_lineage_audit (
                pipeline_name, source_system, source_endpoint, entity_type,
                entity_id, records_count, checksum_sha256, file_path,
                execution_timestamp, execution_status, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                "TimBusOfficialGroundTruthPipeline",
                "TRAMOC/Transerco",
                self.client.endpoint_url,
                "BusRouteGroundTruth",
                route_code,
                total_stations + total_points,
                sha256_hash,
                raw_filepath,
                extracted_at,
                "SUCCESS",
                f"Ingested {total_stations} stations and {total_points} centerline points for Route {route_code} ({route_name})"
            ))
            conn.commit()

        summary = {
            "status": "SUCCESS",
            "fleet_id": fleet_id,
            "route_code": route_code,
            "route_name": route_name,
            "extracted_at": extracted_at,
            "sha256_checksum": sha256_hash,
            "raw_filepath": raw_filepath,
            "total_stations_ingested": total_stations,
            "total_shape_points_ingested": total_points
        }
        logger.info("Successfully ingested Route %s: %s", route_code, summary)
        return summary

