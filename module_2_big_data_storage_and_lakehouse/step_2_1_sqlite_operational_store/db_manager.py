"""
Module 2: Big Data Storage & Lakehouse
Subcomponent: step_2_1_sqlite_operational_store
File: db_manager.py

Unified operational database manager for SQLite (`data/hanoi_bus_system.db`).
Provides data access APIs, integrity checks, automated views, and analytical indexing.
"""

import os
import sys
import sqlite3
from typing import Optional, List, Dict, Any

# Ensure project root in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
sys.path.insert(0, os.path.abspath("."))
from config.system_config import get_database_path, DEFAULT_DB_PATH


class OperationalDatabaseManager:
    """Manages the operational SQLite database holding clean telemetry and TimBus Master tables."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or get_database_path()
        db_dir = os.path.dirname(os.path.abspath(self.db_path))
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        self.ensure_unified_views()

    def get_connection(self) -> sqlite3.Connection:
        """Get a standard SQLite connection with row factory."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def ensure_unified_views(self):
        """Create or replace global analytical views for ETA and monitoring."""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            # 1. Global View: Bus to Next Station for ALL routes
            cur.execute("""
            CREATE VIEW IF NOT EXISTS v_bus_to_next_station AS
            SELECT 
                t.ping_id,
                t.route_code,
                t.route_id,
                t.vehicle_id,
                t.plate,
                t.device_update_time,
                t.device_epoch,
                t.direction,
                t.lat AS bus_lat,
                t.lon AS bus_lon,
                t.s_bus_m,
                t.cross_track_m,
                t.derived_speed_kmh,
                t.is_dwell,
                s.station_order AS next_station_order,
                s.station_id AS next_station_id,
                s.station_name AS next_station_name,
                s.cum_distance_m AS next_station_s,
                ROUND(s.cum_distance_m - t.s_bus_m, 2) AS distance_remaining_m
            FROM route_projected_telemetry t
            JOIN dim_station_crosswalk s
              ON t.route_code = s.route_code
             AND t.direction = s.direction 
             AND s.cum_distance_m = (
                 SELECT MIN(s2.cum_distance_m)
                 FROM dim_station_crosswalk s2
                 WHERE s2.route_code = t.route_code
                   AND s2.direction = t.direction 
                   AND s2.cum_distance_m >= t.s_bus_m
             );
            """)

            # 2. Global View: Active Fleet Health Summary
            cur.execute("""
            CREATE VIEW IF NOT EXISTS v_active_fleet_summary AS
            SELECT 
                route_code,
                count(DISTINCT vehicle_id) as active_buses,
                count(ping_id) as total_projected_pings,
                round(avg(cross_track_m), 2) as avg_cross_track_m,
                round(avg(derived_speed_kmh), 2) as avg_speed_kmh,
                sum(is_dwell) as total_dwell_events
            FROM route_projected_telemetry
            GROUP BY route_code
            ORDER BY total_projected_pings DESC;
            """)
            conn.commit()

    def get_route_telemetry_df(self, route_code: str, direction: Optional[str] = None):
        """Fetch pandas DataFrame of projected telemetry for a specific route (requires pandas)."""
        import pandas as pd
        query = "SELECT * FROM route_projected_telemetry WHERE route_code = ?"
        params = [route_code]
        if direction:
            query += " AND direction = ?"
            params.append(direction)
        query += " ORDER BY vehicle_id, device_epoch;"

        with sqlite3.connect(self.db_path) as conn:
            return pd.read_sql_query(query, conn, params=params)

    def get_route_stations(self, route_code: str, direction: str = "go") -> List[Dict[str, Any]]:
        """Fetch list of official stations in sequence for a route."""
        query = """
        SELECT station_order, station_id, station_name, lat, lon, cum_distance_m
        FROM dim_station_crosswalk
        WHERE route_code = ? AND direction = ?
        ORDER BY station_order;
        """
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            rows = cur.execute(query, (route_code, direction)).fetchall()
            return [dict(r) for r in rows]

    def get_database_statistics(self) -> Dict[str, Any]:
        """Compute comprehensive storage statistics across all tables."""
        stats = {}
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            for t in tables:
                stats[t] = cur.execute(f"SELECT count(1) FROM {t}").fetchone()[0]
        return stats


if __name__ == "__main__":
    if sys.stdout.encoding != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    mgr = OperationalDatabaseManager()
    print(f"Connecting to database: {mgr.db_path}")
    stats = mgr.get_database_statistics()
    print("Database Tables & Row Counts:")
    for t, cnt in stats.items():
        print(f"  {t:<35} : {cnt:,} rows")
