"""
Scripts: Build TimBus - BusMap Crosswalk Master Tables
Generates unified dimensional crosswalk tables (dim_route_crosswalk & dim_station_crosswalk)
establishing TimBus (TRAMOC / Hanoi DoT) as the authoritative Master Ground Truth.
"""

import json
import logging
import os
import sqlite3
import sys
import urllib.parse
import urllib.request

# Ensure project root in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

sys.stdout.reconfigure(encoding="utf-8")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

DB_PATH = "data/telemetry_audit_2026_10_17_18.db"
BUSMAP_ROUTES_PATH = "data/metadata/routes.json"
TIMBUS_URL = "http://timbus.vn/Engine/Business/Search/action.ashx"


def fetch_all_timbus_routes() -> list:
    """Fetch all official bus routes from TimBus API."""
    data = urllib.parse.urlencode({"act": "searchfull", "typ": "1", "key": ""}).encode("utf-8")
    req = urllib.request.Request(
        TIMBUS_URL,
        data=data,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "http://timbus.vn/"
        }
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        return res.get("dt", {}).get("Data", [])


def main():
    print("=" * 70)
    print("XAY DUNG BANG ANH XA CHUAN (DIM CROSSWALK) VOI TIMBUS LA MASTER GROUND TRUTH")
    print("=" * 70)

    # 1. Fetch TimBus routes
    print("[1/3] Dang tai danh ba 100% tuyen tu TimBus (Sở GTVT Hà Nội)...")
    tb_routes = fetch_all_timbus_routes()
    print(f"  -> Da tai {len(tb_routes)} tuyen tu TimBus")

    # 2. Load BusMap routes
    print("[2/3] Dang nap danh muc tuyen BusMap...")
    if not os.path.exists(BUSMAP_ROUTES_PATH):
        raise FileNotFoundError(f"Missing {BUSMAP_ROUTES_PATH}")
    with open(BUSMAP_ROUTES_PATH, "r", encoding="utf-8") as f:
        bm_routes = json.load(f)
    print(f"  -> Da nap {len(bm_routes)} tuyen tu BusMap")

    # Index BusMap routes by routeNo
    bm_by_code = {str(r.get("routeNo", "")).strip().upper(): r for r in bm_routes}

    # 3. Build dim_route_crosswalk
    print("[3/3] Dang khoi tao va cap nhat bang dim_route_crosswalk trong SQLite...")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("DROP TABLE IF EXISTS dim_route_crosswalk")
    cur.execute("""
    CREATE TABLE dim_route_crosswalk (
        route_code TEXT PRIMARY KEY,
        route_name TEXT NOT NULL,
        timbus_fleet_id INTEGER NOT NULL,
        busmap_route_id INTEGER,
        busmap_id INTEGER,
        enterprise TEXT,
        frequency TEXT,
        ticket_cost INTEGER,
        is_mapped_with_busmap INTEGER NOT NULL
    );
    """)

    crosswalk_rows = []
    mapped_count = 0

    for r in tb_routes:
        code = str(r.get("FleedCode", "")).strip()
        code_upper = code.upper()
        name = str(r.get("Name", "")).strip()
        tb_fid = int(r.get("ObjectID", 0))
        cost = int(r.get("Cost", 0)) if isinstance(r.get("Cost"), (int, float)) else 0
        freq = str(r.get("Frequency", "")).strip()

        bm_match = bm_by_code.get(code_upper)
        if bm_match:
            bm_route_id = bm_match.get("routeId")
            bm_id = bm_match.get("id")
            is_mapped = 1
            mapped_count += 1
        else:
            bm_route_id = None
            bm_id = None
            is_mapped = 0

        crosswalk_rows.append((
            code,
            name,
            tb_fid,
            bm_route_id,
            bm_id,
            "",
            freq,
            cost,
            is_mapped
        ))

    cur.executemany("""
    INSERT INTO dim_route_crosswalk VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, crosswalk_rows)

    # 4. Build dim_station_crosswalk (linking TimBus stations with telemetry)
    cur.execute("DROP TABLE IF EXISTS dim_station_crosswalk")
    cur.execute("""
    CREATE TABLE dim_station_crosswalk (
        route_code TEXT NOT NULL,
        direction TEXT NOT NULL,
        station_order INTEGER NOT NULL,
        station_id INTEGER NOT NULL,
        station_name TEXT NOT NULL,
        lat REAL NOT NULL,
        lon REAL NOT NULL,
        cum_distance_m REAL NOT NULL,
        source TEXT NOT NULL,
        PRIMARY KEY (route_code, direction, station_order)
    );
    """)

    # Populate from timbus_station_master
    cur.execute("""
    INSERT INTO dim_station_crosswalk
    SELECT route_code, direction, station_order, station_id, station_name, lat, lon, cum_distance_m, source
    FROM timbus_station_master
    """)

    conn.commit()

    print("\n" + "=" * 70)
    print("HOAN TAT THIET LAP BANG ANH XA MASTER CROSSWALK!")
    print("=" * 70)
    print(f"  Tong so tuyen TimBus da nap: {len(crosswalk_rows)}")
    print(f"  So tuyen khop 1-1 voi BusMap: {mapped_count} ({mapped_count/len(crosswalk_rows)*100:.1f}%)")
    
    # Check stations
    cur.execute("SELECT COUNT(*) FROM dim_station_crosswalk")
    st_count = cur.fetchone()[0]
    print(f"  Tong so trạm dung Master da nap vao dim_station_crosswalk: {st_count} tram")

    print("\n--- MAU 10 TUYEN DA ANH XA TRONG DB ---")
    print(f"{'Code':<8} | {'TimBus FID':<12} | {'BusMap routeId':<15} | {'BusMap ID':<12} | {'Ten Tuyen'}")
    print("-" * 75)
    for row in cur.execute("SELECT route_code, timbus_fleet_id, busmap_route_id, busmap_id, route_name FROM dim_route_crosswalk LIMIT 10"):
        print(f"{row[0]:<8} | {row[1]:<12} | {str(row[2]):<15} | {str(row[3]):<12} | {row[4][:30]}")

    conn.close()


if __name__ == "__main__":
    main()

