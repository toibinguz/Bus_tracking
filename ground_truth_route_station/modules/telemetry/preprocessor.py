"""
Step 0: Telemetry Preprocessing & Indexing Module
Parses, sanitizes, partitions, and indexes bus telemetry pings by route and vehicle.
Distinguishes moving pings (v > 5 km/h) for route trace verification
from dwell pings (v <= 5 km/h) for station ground-truth verification.
"""

import os
import glob
import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

HANOI_BBOX = {
    "min_lat": 20.80,
    "max_lat": 21.35,
    "min_lon": 105.50,
    "max_lon": 106.20
}

def is_valid_gps_ping(lat: float, lon: float) -> bool:
    """Validates GPS coordinates within Hanoi Greater Metropolitan Region."""
    if lat is None or lon is None:
        return False
    return (
        HANOI_BBOX["min_lat"] <= lat <= HANOI_BBOX["max_lat"] and
        HANOI_BBOX["min_lon"] <= lon <= HANOI_BBOX["max_lon"]
    )

def preprocess_telemetry_dataset(
    raw_batches_dir: str = "data/telemetry_sync/raw_batches",
    processed_dir: str = "data/telemetry_sync/processed"
) -> Dict[str, Any]:
    """
    Parses all raw batch jsonl files, groups records by route_id,
    and partitions into moving vs dwell pings.
    
    Args:
        raw_batches_dir: Directory containing synced raw jsonl files.
        processed_dir: Destination directory for indexed route files.
        
    Returns:
        Summary metrics of processed telemetry.
    """
    os.makedirs(processed_dir, exist_ok=True)
    all_files = glob.glob(os.path.join(raw_batches_dir, "**", "*.jsonl"), recursive=True)
    
    if not all_files:
        # Fallback to data/raw/bus if raw_batches is not populated yet
        fallback_files = glob.glob(os.path.join("data", "raw", "bus", "*.jsonl"))
        if fallback_files:
            all_files = fallback_files

    print(f"[*] Preprocessing telemetry across {len(all_files)} batch files...")

    # Route map: route_id -> list of records
    routes_data: Dict[int, List[Dict[str, Any]]] = {}
    total_raw_records = 0
    valid_records = 0
    invalid_records = 0

    for file_path in all_files:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                total_raw_records += 1
                try:
                    rec = json.loads(line)
                except Exception:
                    invalid_records += 1
                    continue

                lat = rec.get("lat")
                lon = rec.get("lon")
                if not is_valid_gps_ping(lat, lon):
                    invalid_records += 1
                    continue

                # Normalization
                route_id = rec.get("route_id")
                if route_id is None:
                    continue
                try:
                    route_id = int(route_id)
                except (ValueError, TypeError):
                    continue

                cleaned_rec = {
                    "vehicle_id": rec.get("vehicle_id"),
                    "plate": rec.get("plate", ""),
                    "route_id": route_id,
                    "lat": round(float(lat), 6),
                    "lon": round(float(lon), 6),
                    "speed": float(rec.get("speed", 0.0) or 0.0),
                    "direction": int(rec.get("direction", 0) if rec.get("direction") is not None else 0),
                    "heading_deg": float(rec.get("heading_deg", 0.0) or 0.0),
                    "current_station_id": rec.get("current_station_id"),
                    "next_station_id": rec.get("next_station_id"),
                    "device_update_time": rec.get("device_update_time", "")
                }

                if route_id not in routes_data:
                    routes_data[route_id] = []
                routes_data[route_id].append(cleaned_rec)
                valid_records += 1

    # Save per-route summaries & data
    route_summaries = {}
    for r_id, pings in routes_data.items():
        # Sort by device_update_time if available
        pings.sort(key=lambda x: x.get("device_update_time") or "")
        
        # Partition moving (v > 5 km/h) vs dwell (v <= 5 km/h)
        moving = [p for p in pings if p["speed"] > 5.0]
        dwell = [p for p in pings if p["speed"] <= 5.0]
        
        # Unique vehicles
        vehicles = sorted(list(set(p["vehicle_id"] for p in pings if p["vehicle_id"] is not None)))

        route_payload = {
            "route_id": r_id,
            "total_pings": len(pings),
            "moving_pings_count": len(moving),
            "dwell_pings_count": len(dwell),
            "vehicles": vehicles,
            "vehicles_count": len(vehicles),
            "pings": pings
        }

        out_path = os.path.join(processed_dir, f"route_{r_id}.json")
        with open(out_path, "w", encoding="utf-8") as out_f:
            json.dump(route_payload, out_f, ensure_ascii=False)

        route_summaries[r_id] = {
            "total_pings": len(pings),
            "moving_pings": len(moving),
            "dwell_pings": len(dwell),
            "vehicles_count": len(vehicles)
        }

    summary_file = os.path.join(processed_dir, "telemetry_summary.json")
    summary = {
        "processed_at": datetime.now().isoformat(),
        "total_files": len(all_files),
        "total_raw_records": total_raw_records,
        "valid_records": valid_records,
        "invalid_records": invalid_records,
        "routes_detected_count": len(routes_data),
        "route_summaries": route_summaries
    }
    with open(summary_file, "w", encoding="utf-8") as sf:
        json.dump(summary, sf, indent=2, ensure_ascii=False)

    print(f"[OK] Preprocessed {valid_records:,} valid pings across {len(routes_data)} routes.")
    return summary

def load_preprocessed_route_pings(route_id: int, processed_dir: str = "data/telemetry_sync/processed") -> Optional[Dict[str, Any]]:
    """Loads indexed pings for a specific route."""
    file_path = os.path.join(processed_dir, f"route_{route_id}.json")
    if not os.path.exists(file_path):
        return None
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)

if __name__ == "__main__":
    preprocess_telemetry_dataset()

