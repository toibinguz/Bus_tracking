"""
Module 1.3.2: Local Lake Writer
Ghi nối đuôi (append-only) an toàn các bản ghi jsonl phân vùng theo ngày.
"""

import os
import json
from core.config import BUS_OUTPUT_DIR, TRAFFIC_OUTPUT_DIR, INCIDENT_OUTPUT_DIR

def append_jsonl_records(records, out_file_path):
    """Ghi danh sách bản ghi nối đuôi vào file JSONL."""
    if not records:
        return 0
    os.makedirs(os.path.dirname(out_file_path), exist_ok=True)
    with open(out_file_path, "a", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return len(records)

def save_bus_telemetry_batch(records, date_tag, base_dir=BUS_OUTPUT_DIR):
    """Lưu các bản ghi xe buýt vào file phân vùng data/raw/bus/YYYY-MM-DD.jsonl."""
    target_path = os.path.join(base_dir, f"{date_tag}.jsonl")
    return append_jsonl_records(records, target_path)

def save_traffic_flow_batch(records, date_tag, base_dir=TRAFFIC_OUTPUT_DIR):
    """Lưu các bản ghi TomTom Flow vào file phân vùng data/raw/traffic/YYYY-MM-DD.jsonl."""
    target_path = os.path.join(base_dir, f"{date_tag}.jsonl")
    return append_jsonl_records(records, target_path)

def save_incidents_batch(records, date_tag, base_dir=INCIDENT_OUTPUT_DIR):
    """Lưu các bản ghi TomTom Incidents vào file phân vùng data/raw/incidents/YYYY-MM-DD.jsonl."""
    target_path = os.path.join(base_dir, f"{date_tag}.jsonl")
    return append_jsonl_records(records, target_path)

