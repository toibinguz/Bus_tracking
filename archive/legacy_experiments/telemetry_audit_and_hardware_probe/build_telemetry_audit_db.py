"""
Build Telemetry Audit SQLite Database for 2026-10-17 and 2026-10-18
Ingests raw JSONL batches, deduplicates unique pings per vehicle, calculates
ping periodicity (delta T), latency distributions, and packet loss / gap statistics.
"""

import os
import sys
import glob
import json
import sqlite3
import math
from datetime import datetime
from collections import defaultdict
import numpy as np

DB_PATH = "data/telemetry_audit_2026_10_17_18.db"
RAW_BASE_DIR = "data/telemetry_sync/raw_batches"
DATES = ["2026-10-17", "2026-10-18"]

def haversine_distance(lat1, lon1, lat2, lon2):
    R = 6371000.0  # meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2.0)**2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c

def init_db(conn):
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode = WAL;")
    cur.execute("PRAGMA synchronous = NORMAL;")

    # 1. Raw Telemetry Records (All polls)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS raw_telemetry (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date_tag TEXT NOT NULL,
        batch_file TEXT NOT NULL,
        vehicle_id INTEGER NOT NULL,
        plate TEXT,
        route_id INTEGER,
        lat REAL,
        lon REAL,
        speed REAL,
        raw_speed REAL,
        direction INTEGER,
        heading_deg REAL,
        current_station_id INTEGER,
        next_station_id INTEGER,
        device_update_time TEXT,
        device_epoch REAL,
        crawled_at TEXT,
        crawled_epoch REAL,
        raw_latency_sec REAL,
        corr_latency_sec REAL,
        is_moving INTEGER,
        quality_status TEXT
    );
    """)

    # 2. Unique GPS Pings Per Vehicle
    cur.execute("""
    CREATE TABLE IF NOT EXISTS vehicle_unique_pings (
        ping_id INTEGER PRIMARY KEY AUTOINCREMENT,
        date_tag TEXT NOT NULL,
        vehicle_id INTEGER NOT NULL,
        plate TEXT,
        route_id INTEGER,
        device_update_time TEXT NOT NULL,
        device_epoch REAL NOT NULL,
        first_crawled_at TEXT,
        first_crawled_epoch REAL,
        poll_count INTEGER DEFAULT 1,
        lat REAL,
        lon REAL,
        speed REAL,
        direction INTEGER,
        heading_deg REAL,
        current_station_id INTEGER,
        next_station_id INTEGER,
        is_moving INTEGER,
        latency_sec REAL
    );
    """)

    # 3. Inter-Ping Intervals (Periodicity & Gaps)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS vehicle_intervals (
        interval_id INTEGER PRIMARY KEY AUTOINCREMENT,
        date_tag TEXT NOT NULL,
        vehicle_id INTEGER NOT NULL,
        plate TEXT,
        route_id INTEGER,
        prev_time TEXT NOT NULL,
        curr_time TEXT NOT NULL,
        prev_epoch REAL NOT NULL,
        curr_epoch REAL NOT NULL,
        delta_t_sec REAL NOT NULL,
        distance_m REAL,
        speed_kmh REAL,
        is_moving INTEGER,
        category TEXT
    );
    """)

    # 4. Vehicle Daily Summary KPIs
    cur.execute("""
    CREATE TABLE IF NOT EXISTS vehicle_daily_kpis (
        date_tag TEXT NOT NULL,
        vehicle_id INTEGER NOT NULL,
        plate TEXT,
        route_id INTEGER,
        operating_start TEXT,
        operating_end TEXT,
        span_hours REAL,
        total_polls INTEGER,
        unique_pings INTEGER,
        stale_polls INTEGER,
        stale_ratio_pct REAL,
        delta_t_mean REAL,
        delta_t_median REAL,
        delta_t_std REAL,
        delta_t_min REAL,
        delta_t_max REAL,
        delta_t_p10 REAL,
        delta_t_p25 REAL,
        delta_t_p75 REAL,
        delta_t_p90 REAL,
        delta_t_p95 REAL,
        delta_t_p99 REAL,
        moving_delta_t_median REAL,
        dwell_delta_t_median REAL,
        gaps_gt_60s INTEGER,
        gaps_gt_120s INTEGER,
        gaps_gt_300s INTEGER,
        gaps_gt_600s INTEGER,
        avg_latency_corr REAL,
        median_latency_corr REAL,
        std_latency_corr REAL,
        negative_latency_count INTEGER,
        PRIMARY KEY (date_tag, vehicle_id)
    );
    """)

    # 5. System Daily Aggregate Comparison
    cur.execute("""
    CREATE TABLE IF NOT EXISTS daily_system_kpis (
        date_tag TEXT PRIMARY KEY,
        total_batches INTEGER,
        total_raw_records INTEGER,
        total_vehicles_seen INTEGER,
        total_unique_pings INTEGER,
        overall_stale_pct REAL,
        mean_latency_sec REAL,
        median_latency_sec REAL,
        std_latency_sec REAL,
        negative_latency_count INTEGER,
        negative_latency_pct REAL,
        mean_interval_sec REAL,
        median_interval_sec REAL,
        std_interval_sec REAL,
        gaps_gt_60s_count INTEGER,
        gaps_gt_120s_count INTEGER,
        gaps_gt_300s_count INTEGER,
        gaps_gt_600s_count INTEGER
    );
    """)

    conn.commit()

def create_indexes(conn):
    print("[*] Creating database indexes for high-speed queries...")
    cur = conn.cursor()
    cur.execute("CREATE INDEX IF NOT EXISTS idx_raw_veh_time ON raw_telemetry (vehicle_id, device_epoch);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_raw_date_veh ON raw_telemetry (date_tag, vehicle_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_raw_route ON raw_telemetry (route_id, device_epoch);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_unique_veh_time ON vehicle_unique_pings (vehicle_id, device_epoch);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_unique_date_veh ON vehicle_unique_pings (date_tag, vehicle_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_interval_veh ON vehicle_intervals (vehicle_id, curr_epoch);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_interval_date_dt ON vehicle_intervals (date_tag, delta_t_sec);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_kpis_route ON vehicle_daily_kpis (route_id, date_tag);")
    conn.commit()
    print("[OK] Indexes created successfully.")

def categorize_interval(dt):
    if dt <= 35:
        return "STANDARD_30S (<=35s)"
    elif dt <= 65:
        return "EXPECTED_60S (36-65s)"
    elif dt <= 125:
        return "MINOR_GAP (66-125s)"
    elif dt <= 305:
        return "SIGNIFICANT_GAP (126-305s)"
    elif dt <= 605:
        return "MAJOR_DROPOUT (306-605s)"
    else:
        return "BLACKOUT (>605s)"

def parse_timestamps(d, date_tag):
    """
    Parses device_update_time and crawled_at.
    Handles the 17/10 dev time issue where crawled_at had +00:00 mistakenly appended to local time.
    """
    dev_str = d.get('device_update_time', '')
    crawl_str = d.get('crawled_at', '')
    
    dt_dev = datetime.fromisoformat(dev_str)
    dev_epoch = dt_dev.timestamp()

    # Raw crawled epoch
    dt_crawl = datetime.fromisoformat(crawl_str)
    raw_crawl_epoch = dt_crawl.timestamp()
    raw_latency = raw_crawl_epoch - dev_epoch

    # Corrected crawled epoch
    if date_tag == "2026-10-17":
        # 17/10 fix: crawled_at was local Vietnam time stamped with +00:00
        dt_crawl_corr = dt_crawl.replace(tzinfo=dt_dev.tzinfo)
        corr_crawl_epoch = dt_crawl_corr.timestamp()
    else:
        corr_crawl_epoch = raw_crawl_epoch

    corr_latency = corr_crawl_epoch - dev_epoch

    return dev_epoch, raw_crawl_epoch, corr_crawl_epoch, raw_latency, corr_latency

def process_all_data():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print(f"[*] Removed existing database: {DB_PATH}")

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    system_metrics = {}

    for date_tag in DATES:
        dir_path = os.path.join(RAW_BASE_DIR, date_tag, "bus")
        batch_files = sorted(glob.glob(os.path.join(dir_path, "*.jsonl")))
        print(f"\n{'='*70}\n[DATA INGESTION] Processing {date_tag}: {len(batch_files)} batch files\n{'='*70}")

        raw_rows = []
        # vehicle_pings_map: vehicle_id -> dict of (device_update_time -> dict of aggregated ping info)
        vehicle_pings_map = defaultdict(dict)
        vehicle_meta = {}

        total_records = 0
        neg_latency_count = 0
        all_corr_latencies = []

        for b_idx, b_file in enumerate(batch_files):
            b_name = os.path.basename(b_file)
            with open(b_file, "r", encoding="utf-8", errors="ignore") as fp:
                for line in fp:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue

                    vid = d.get("vehicle_id")
                    if vid is None:
                        continue

                    dev_epoch, raw_crawl_epoch, corr_crawl_epoch, raw_latency, corr_latency = parse_timestamps(d, date_tag)
                    spd = float(d.get("speed", 0.0) or 0.0)
                    is_moving = 1 if spd > 5.0 else 0
                    if corr_latency < 0:
                        neg_latency_count += 1
                    all_corr_latencies.append(corr_latency)

                    plate = d.get("plate", "")
                    route_id = d.get("route_id", 0)
                    if vid not in vehicle_meta:
                        vehicle_meta[vid] = (plate, route_id)

                    raw_rows.append((
                        date_tag,
                        b_name,
                        vid,
                        plate,
                        route_id,
                        float(d.get("lat", 0.0) or 0.0),
                        float(d.get("lon", 0.0) or 0.0),
                        spd,
                        float(d.get("raw_speed", 0.0) or 0.0),
                        int(d.get("direction", -1) or -1),
                        float(d.get("heading_deg", 0.0) or 0.0),
                        int(d.get("current_station_id", 0) or 0),
                        int(d.get("next_station_id", 0) or 0),
                        d.get("device_update_time", ""),
                        dev_epoch,
                        d.get("crawled_at", ""),
                        raw_crawl_epoch,
                        raw_latency,
                        corr_latency,
                        is_moving,
                        d.get("quality_status", "")
                    ))

                    # Deduplicate into unique pings per vehicle
                    dev_time = d.get("device_update_time", "")
                    if dev_time not in vehicle_pings_map[vid]:
                        vehicle_pings_map[vid][dev_time] = {
                            "plate": plate,
                            "route_id": route_id,
                            "device_epoch": dev_epoch,
                            "first_crawled_at": d.get("crawled_at", ""),
                            "first_crawled_epoch": corr_crawl_epoch,
                            "poll_count": 1,
                            "lat": float(d.get("lat", 0.0) or 0.0),
                            "lon": float(d.get("lon", 0.0) or 0.0),
                            "speed": spd,
                            "direction": int(d.get("direction", -1) or -1),
                            "heading_deg": float(d.get("heading_deg", 0.0) or 0.0),
                            "current_station_id": int(d.get("current_station_id", 0) or 0),
                            "next_station_id": int(d.get("next_station_id", 0) or 0),
                            "is_moving": is_moving,
                            "latency_sec": corr_latency
                        }
                    else:
                        vehicle_pings_map[vid][dev_time]["poll_count"] += 1

                    total_records += 1

            if len(raw_rows) >= 50000:
                conn.executemany("""
                INSERT INTO raw_telemetry (
                    date_tag, batch_file, vehicle_id, plate, route_id,
                    lat, lon, speed, raw_speed, direction, heading_deg,
                    current_station_id, next_station_id, device_update_time,
                    device_epoch, crawled_at, crawled_epoch, raw_latency_sec,
                    corr_latency_sec, is_moving, quality_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, raw_rows)
                conn.commit()
                print(f"  -> Ingested {len(raw_rows):,} raw rows (Batch {b_idx+1}/{len(batch_files)})...")
                raw_rows = []

        if raw_rows:
            conn.executemany("""
            INSERT INTO raw_telemetry (
                date_tag, batch_file, vehicle_id, plate, route_id,
                lat, lon, speed, raw_speed, direction, heading_deg,
                current_station_id, next_station_id, device_update_time,
                device_epoch, crawled_at, crawled_epoch, raw_latency_sec,
                corr_latency_sec, is_moving, quality_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, raw_rows)
            conn.commit()

        print(f"[OK] Completed raw telemetry ingestion for {date_tag}: {total_records:,} records.")

        # Ingest Unique Pings and Calculate Intervals per Vehicle
        print(f"[*] Ingesting unique pings & calculating intervals for {len(vehicle_pings_map)} vehicles...")
        unique_ping_rows = []
        interval_rows = []
        daily_kpi_rows = []

        all_day_intervals = []
        total_unique_pings_day = 0
        gaps_60_day = 0
        gaps_120_day = 0
        gaps_300_day = 0
        gaps_600_day = 0

        for vid, pings_dict in vehicle_pings_map.items():
            plate, route_id = vehicle_meta[vid]
            # Sort unique pings by device_epoch
            sorted_times = sorted(pings_dict.keys(), key=lambda t: pings_dict[t]["device_epoch"])
            n_pings = len(sorted_times)
            total_unique_pings_day += n_pings

            total_polls_vid = sum(p["poll_count"] for p in pings_dict.values())
            stale_polls = total_polls_vid - n_pings
            stale_pct = (stale_polls / total_polls_vid * 100.0) if total_polls_vid > 0 else 0.0

            first_t = sorted_times[0]
            last_t = sorted_times[-1]
            first_epoch = pings_dict[first_t]["device_epoch"]
            last_epoch = pings_dict[last_t]["device_epoch"]
            span_hrs = max((last_epoch - first_epoch) / 3600.0, 0.0)

            # Ingest unique pings
            for t in sorted_times:
                p = pings_dict[t]
                unique_ping_rows.append((
                    date_tag, vid, plate, route_id,
                    t, p["device_epoch"],
                    p["first_crawled_at"], p["first_crawled_epoch"],
                    p["poll_count"], p["lat"], p["lon"], p["speed"],
                    p["direction"], p["heading_deg"],
                    p["current_station_id"], p["next_station_id"],
                    p["is_moving"], p["latency_sec"]
                ))

            # Intervals calculation
            v_intervals = []
            v_moving_intervals = []
            v_dwell_intervals = []
            v_gaps_60 = 0
            v_gaps_120 = 0
            v_gaps_300 = 0
            v_gaps_600 = 0

            for i in range(1, n_pings):
                prev_p = pings_dict[sorted_times[i - 1]]
                curr_p = pings_dict[sorted_times[i]]
                dt = curr_p["device_epoch"] - prev_p["device_epoch"]
                if dt <= 0:
                    continue

                dist = haversine_distance(prev_p["lat"], prev_p["lon"], curr_p["lat"], curr_p["lon"])
                cat = categorize_interval(dt)
                is_mov = 1 if (prev_p["speed"] > 5.0 or curr_p["speed"] > 5.0) else 0

                interval_rows.append((
                    date_tag, vid, plate, route_id,
                    sorted_times[i - 1], sorted_times[i],
                    prev_p["device_epoch"], curr_p["device_epoch"],
                    dt, dist, curr_p["speed"], is_mov, cat
                ))

                v_intervals.append(dt)
                all_day_intervals.append(dt)
                if is_mov:
                    v_moving_intervals.append(dt)
                else:
                    v_dwell_intervals.append(dt)

                if dt > 60:
                    v_gaps_60 += 1
                    gaps_60_day += 1
                if dt > 120:
                    v_gaps_120 += 1
                    gaps_120_day += 1
                if dt > 300:
                    v_gaps_300 += 1
                    gaps_300_day += 1
                if dt > 600:
                    v_gaps_600 += 1
                    gaps_600_day += 1

            # Vehicle KPIs
            if v_intervals:
                arr = np.array(v_intervals)
                dt_mean = float(np.mean(arr))
                dt_median = float(np.median(arr))
                dt_std = float(np.std(arr))
                dt_min = float(np.min(arr))
                dt_max = float(np.max(arr))
                dt_p10 = float(np.percentile(arr, 10))
                dt_p25 = float(np.percentile(arr, 25))
                dt_p75 = float(np.percentile(arr, 75))
                dt_p90 = float(np.percentile(arr, 90))
                dt_p95 = float(np.percentile(arr, 95))
                dt_p99 = float(np.percentile(arr, 99))
            else:
                dt_mean = dt_median = dt_std = dt_min = dt_max = 0.0
                dt_p10 = dt_p25 = dt_p75 = dt_p90 = dt_p95 = dt_p99 = 0.0

            mov_median = float(np.median(v_moving_intervals)) if v_moving_intervals else 0.0
            dwell_median = float(np.median(v_dwell_intervals)) if v_dwell_intervals else 0.0

            # Latency stats for this vehicle
            v_latencies = [p["latency_sec"] for p in pings_dict.values()]
            v_neg_lat = sum(1 for lat in v_latencies if lat < 0)
            avg_lat = float(np.mean(v_latencies)) if v_latencies else 0.0
            med_lat = float(np.median(v_latencies)) if v_latencies else 0.0
            std_lat = float(np.std(v_latencies)) if v_latencies else 0.0

            daily_kpi_rows.append((
                date_tag, vid, plate, route_id,
                first_t, last_t, span_hrs,
                total_polls_vid, n_pings, stale_polls, stale_pct,
                dt_mean, dt_median, dt_std, dt_min, dt_max,
                dt_p10, dt_p25, dt_p75, dt_p90, dt_p95, dt_p99,
                mov_median, dwell_median,
                v_gaps_60, v_gaps_120, v_gaps_300, v_gaps_600,
                avg_lat, med_lat, std_lat, v_neg_lat
            ))

        # Commit unique pings
        conn.executemany("""
        INSERT INTO vehicle_unique_pings (
            date_tag, vehicle_id, plate, route_id,
            device_update_time, device_epoch,
            first_crawled_at, first_crawled_epoch,
            poll_count, lat, lon, speed, direction,
            heading_deg, current_station_id, next_station_id,
            is_moving, latency_sec
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, unique_ping_rows)
        conn.commit()
        print(f"[OK] Ingested {len(unique_ping_rows):,} unique pings for {date_tag}.")

        # Commit intervals
        conn.executemany("""
        INSERT INTO vehicle_intervals (
            date_tag, vehicle_id, plate, route_id,
            prev_time, curr_time, prev_epoch, curr_epoch,
            delta_t_sec, distance_m, speed_kmh, is_moving, category
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, interval_rows)
        conn.commit()
        print(f"[OK] Ingested {len(interval_rows):,} ping intervals for {date_tag}.")

        # Commit daily KPIs
        conn.executemany("""
        INSERT INTO vehicle_daily_kpis (
            date_tag, vehicle_id, plate, route_id,
            operating_start, operating_end, span_hours,
            total_polls, unique_pings, stale_polls, stale_ratio_pct,
            delta_t_mean, delta_t_median, delta_t_std, delta_t_min, delta_t_max,
            delta_t_p10, delta_t_p25, delta_t_p75, delta_t_p90, delta_t_p95, delta_t_p99,
            moving_delta_t_median, dwell_delta_t_median,
            gaps_gt_60s, gaps_gt_120s, gaps_gt_300s, gaps_gt_600s,
            avg_latency_corr, median_latency_corr, std_latency_corr,
            negative_latency_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, daily_kpi_rows)
        conn.commit()
        print(f"[OK] Ingested {len(daily_kpi_rows):,} vehicle KPI records for {date_tag}.")

        # Store system level stats
        arr_intervals = np.array(all_day_intervals) if all_day_intervals else np.array([0])
        arr_lat = np.array(all_corr_latencies) if all_corr_latencies else np.array([0])
        system_metrics[date_tag] = (
            date_tag,
            len(batch_files),
            total_records,
            len(vehicle_pings_map),
            total_unique_pings_day,
            float((total_records - total_unique_pings_day) / total_records * 100.0) if total_records > 0 else 0.0,
            float(np.mean(arr_lat)),
            float(np.median(arr_lat)),
            float(np.std(arr_lat)),
            neg_latency_count,
            float(neg_latency_count / total_records * 100.0) if total_records > 0 else 0.0,
            float(np.mean(arr_intervals)),
            float(np.median(arr_intervals)),
            float(np.std(arr_intervals)),
            gaps_60_day,
            gaps_120_day,
            gaps_300_day,
            gaps_600_day
        )

    # Insert daily system KPIs
    conn.executemany("""
    INSERT INTO daily_system_kpis (
        date_tag, total_batches, total_raw_records, total_vehicles_seen,
        total_unique_pings, overall_stale_pct,
        mean_latency_sec, median_latency_sec, std_latency_sec,
        negative_latency_count, negative_latency_pct,
        mean_interval_sec, median_interval_sec, std_interval_sec,
        gaps_gt_60s_count, gaps_gt_120s_count, gaps_gt_300s_count, gaps_gt_600s_count
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """, list(system_metrics.values()))
    conn.commit()

    create_indexes(conn)
    conn.close()
    print(f"\n[SUCCESS] DATABASE FULLY CREATED AT: {os.path.abspath(DB_PATH)}")

if __name__ == "__main__":
    process_all_data()
