"""
Empirical Audit Script for WP 2.1: TomTom Multi-Source Fusion Feasibility
"""
import os
import glob
import json
import sqlite3
import math
from datetime import datetime
from collections import Counter

DB_PATH = "data/hanoi_bus_system.db"
INCIDENTS_GLOB = "data/temp_hf_sync/raw_data/*/incidents/*.jsonl"

def run_audit():
    print("=== 1. AUDITING TOMTOM INCIDENT FILES ===")
    files = sorted(glob.glob(INCIDENTS_GLOB))
    print(f"Total incident JSONL files found: {len(files)}")
    
    total_raw_records = 0
    date_counter = Counter()
    category_counter = Counter()
    magnitude_counter = Counter()
    geom_type_counter = Counter()
    unique_incident_ids = set()
    sample_records = []
    
    min_time = None
    max_time = None
    
    for fpath in files:
        # extract date from path
        parts = fpath.replace("\\", "/").split("/")
        # e.g., data/temp_hf_sync/raw_data/2026-10-08/incidents/batch_140018.jsonl
        dt_str = "unknown"
        for p in parts:
            if p.startswith("2026-"):
                dt_str = p
                break
        
        with open(fpath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                total_raw_records += 1
                date_counter[dt_str] += 1
                try:
                    rec = json.loads(line)
                    inc_id = rec.get("incident_id")
                    if inc_id:
                        unique_incident_ids.add(inc_id)
                    category_counter[rec.get("icon_category", "unknown")] += 1
                    magnitude_counter[rec.get("magnitude_of_delay", "unknown")] += 1
                    geom_type_counter[rec.get("geometry_type", "unknown")] += 1
                    
                    ts = rec.get("timestamp")
                    if ts:
                        if min_time is None or ts < min_time:
                            min_time = ts
                        if max_time is None or ts > max_time:
                            max_time = ts
                    
                    if len(sample_records) < 3:
                        sample_records.append(rec)
                except Exception as e:
                    pass

    print(f"Total raw incident records across all files: {total_raw_records:,}")
    print(f"Unique incident_ids: {len(unique_incident_ids):,}")
    print(f"Time span: {min_time} to {max_time}")
    print(f"Active dates count: {len(date_counter)}")
    for dt, cnt in sorted(date_counter.items()):
        print(f"  - {dt}: {cnt:,} records")
        
    print("\nIcon Category distribution:")
    for cat, cnt in category_counter.most_common():
        print(f"  Category {cat}: {cnt:,} ({cnt/total_raw_records*100:.1f}%)")
        
    print("\nMagnitude of Delay distribution:")
    for mag, cnt in magnitude_counter.most_common():
        print(f"  Magnitude {mag}: {cnt:,} ({cnt/total_raw_records*100:.1f}%)")
        
    print("\nGeometry types:")
    for gt, cnt in geom_type_counter.most_common():
        print(f"  {gt}: {cnt:,}")

    print("\n=== 2. AUDITING DATABASE TELEMETRY & SHAPES ===")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    # Check bus telemetry dates
    cur.execute("SELECT MIN(ping_time), MAX(ping_time), COUNT(*) FROM route_projected_telemetry")
    row = cur.fetchone()
    print(f"route_projected_telemetry: min={row[0]}, max={row[1]}, total={row[2]:,}")
    
    # Check canonical_route_master
    cur.execute("SELECT COUNT(DISTINCT route_code) FROM canonical_route_master")
    print(f"Canonical routes count: {cur.fetchone()[0]}")
    
    # Check canonical_shape_master
    cur.execute("SELECT COUNT(*), COUNT(DISTINCT route_code), MIN(shape_dist_traveled_m), MAX(shape_dist_traveled_m) FROM canonical_shape_master")
    s_row = cur.fetchone()
    print(f"canonical_shape_master: count={s_row[0]:,}, routes={s_row[1]}, min_dist={s_row[2]}, max_dist={s_row[3]}")
    
    # Check route bounds
    cur.execute("SELECT MIN(shape_pt_lat), MAX(shape_pt_lat), MIN(shape_pt_lon), MAX(shape_pt_lon) FROM canonical_shape_master")
    b_row = cur.fetchone()
    print(f"Shape coordinates bounding box: lat=[{b_row[0]}, {b_row[1]}], lon=[{b_row[2]}, {b_row[3]}]")
    
    conn.close()

if __name__ == "__main__":
    run_audit()

