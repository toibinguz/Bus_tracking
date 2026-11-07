"""
High-Performance Bulk Ingestion of All Bus Telemetry Batches into SQLite
Loads and deduplicates all dates from data/raw/*/bus/*.jsonl
into vehicle_unique_pings.
"""

import os
import sys
import glob
import json
import time
import sqlite3
from datetime import datetime

# UTF-8 stdout
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)

from config.system_config import (
    DEFAULT_DB_PATH,
    RAW_DATA_DIR as CFG_RAW_DATA_DIR,
    CANONICAL_START_DATE,
    HANOI_BBOX,
)

DB_PATH = os.path.join(BASE_DIR, DEFAULT_DB_PATH)
RAW_DATA_DIR = os.path.join(BASE_DIR, CFG_RAW_DATA_DIR)

def main():
    print("=" * 70)
    print("🚀 HIGH-PERFORMANCE BULK BUS TELEMETRY INGESTION")
    print(f"📁 Source: {RAW_DATA_DIR}")
    print(f"💾 Database: {DB_PATH}")
    print("=" * 70)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Turbo PRAGMA settings for bulk loading
    cur.execute("PRAGMA journal_mode = WAL;")
    cur.execute("PRAGMA synchronous = OFF;")
    cur.execute("PRAGMA cache_size = -1048576;")  # 1 GB cache
    cur.execute("PRAGMA temp_store = MEMORY;")

    # Find all available date directories
    if not os.path.exists(RAW_DATA_DIR):
        print(f"[ERROR] Source directory not found: {RAW_DATA_DIR}")
        return

    all_dates = sorted([
        d for d in os.listdir(RAW_DATA_DIR)
        if os.path.isdir(os.path.join(RAW_DATA_DIR, d)) and d >= CANONICAL_START_DATE
    ])
    print(f"📅 Found {len(all_dates)} date directories: {all_dates}")

    # Check already ingested dates
    cur.execute("SELECT date_tag, COUNT(*) FROM vehicle_unique_pings GROUP BY date_tag")
    existing_date_counts = dict(cur.fetchall())
    print(f"📊 Existing dates in DB: {existing_date_counts}")

    insert_query = """
    INSERT INTO vehicle_unique_pings (
        date_tag, vehicle_id, plate, route_id, device_update_time, device_epoch,
        first_crawled_at, first_crawled_epoch, poll_count, lat, lon, speed,
        direction, heading_deg, current_station_id, next_station_id, is_moving, latency_sec
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    total_inserted = 0
    start_total_time = time.time()

    for date_tag in all_dates:
        bus_dir = os.path.join(RAW_DATA_DIR, date_tag, "bus")
        if not os.path.exists(bus_dir):
            continue

        files = glob.glob(os.path.join(bus_dir, "*.jsonl"))
        if not files:
            continue

        # If date already has > 100k pings in DB, check if we need to skip or deduplicate
        existing_count = existing_date_counts.get(date_tag, 0)
        if existing_count > 100_000:
            print(f"⏭️ Skipping {date_tag}: Already ingested ({existing_count:,} pings in DB).")
            continue

        t0 = time.time()
        # In-memory deduplication set: (vehicle_id, int(device_epoch))
        seen_keys = set()
        if existing_count > 0:
            cur.execute("SELECT vehicle_id, CAST(device_epoch AS INT) FROM vehicle_unique_pings WHERE date_tag = ?", (date_tag,))
            for vid, ep in cur.fetchall():
                seen_keys.add((vid, ep))

        records = []
        for fp in files:
            with open(fp, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                        vid = int(row.get("vehicle_id", 0))
                        dev_time = row.get("device_update_time", "")
                        if not vid or not dev_time:
                            continue

                        # Parse epoch
                        try:
                            dev_epoch = datetime.fromisoformat(dev_time).timestamp()
                        except Exception:
                            continue

                        key = (vid, int(dev_epoch))
                        if key in seen_keys:
                            continue
                        seen_keys.add(key)

                        lat = float(row.get("lat", 0.0) or 0.0)
                        lon = float(row.get("lon", 0.0) or 0.0)
                        if lat < HANOI_BBOX["min_lat"] or lon < HANOI_BBOX["min_lon"]:  # Valid bounds check
                            continue

                        crawled_at = row.get("crawled_at", "")
                        try:
                            crawled_epoch = datetime.fromisoformat(crawled_at).timestamp() if crawled_at else dev_epoch
                        except Exception:
                            crawled_epoch = dev_epoch

                        speed = float(row.get("speed", 0.0) or 0.0)
                        plate = str(row.get("plate", "") or "")
                        route_id = int(row.get("route_id", 0) or 0)
                        direction = int(row.get("direction", 0) or 0)
                        heading_deg = float(row.get("heading_deg", 0.0) or 0.0)
                        curr_st = int(row.get("current_station_id", 0) or 0)
                        next_st = int(row.get("next_station_id", 0) or 0)
                        is_moving = 1 if speed > 1.0 else 0
                        latency = max(0.0, round(crawled_epoch - dev_epoch, 2))

                        records.append((
                            date_tag, vid, plate, route_id, dev_time, dev_epoch,
                            crawled_at, crawled_epoch, 1, lat, lon, speed,
                            direction, heading_deg, curr_st, next_st, is_moving, latency
                        ))
                    except Exception:
                        continue

        # Bulk insert
        if records:
            cur.executemany(insert_query, records)
            conn.commit()
            total_inserted += len(records)
            elapsed_date = time.time() - t0
            print(f"✅ Ingested {date_tag}: {len(records):,} new unique pings from {len(files)} files in {elapsed_date:.2f}s ({len(records)/elapsed_date:,.0f} pings/s)")
        else:
            print(f"⚠️ {date_tag}: 0 valid new records found.")

    total_time = time.time() - start_total_time
    cur.execute("SELECT COUNT(*) FROM vehicle_unique_pings")
    total_db = cur.fetchone()[0]

    # Re-enable normal synchronous mode
    cur.execute("PRAGMA synchronous = NORMAL;")
    conn.close()

    print("\n" + "=" * 70)
    print("🎉 INGESTION PIPELINE FINISHED SUCCESSFULLY")
    print(f"📥 Total Newly Ingested: {total_inserted:,} pings")
    print(f"📊 Grand Total Pings in Database: {total_db:,} pings")
    print(f"⏱️ Total Wall Time: {total_time:.2f}s ({total_time/60:.2f} mins)")
    print("=" * 70)

if __name__ == "__main__":
    main()

