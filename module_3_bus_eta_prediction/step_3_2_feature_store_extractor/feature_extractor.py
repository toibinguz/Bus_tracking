"""
Module 3: Bus ETA Prediction Engine
Subcomponent: step_3_2_feature_store_extractor
File: feature_extractor.py

Extracts machine learning training features (X) and ground truth target (Y).
Target Y = Actual seconds remaining until the bus reaches the target downstream station.
Features X = Spatial, temporal, kinematic, and topological transit properties.
"""

import os
import sys
import sqlite3
import pandas as pd
import numpy as np
from typing import Tuple

# Ensure project root in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))
sys.path.insert(0, os.path.abspath("."))


DEFAULT_DB_PATH = "data/telemetry_audit_2026_10_17_18.db"


def extract_route_training_dataset(route_code: str, db_path: str = DEFAULT_DB_PATH) -> pd.DataFrame:
    """
    Extract supervised training dataset for ETA prediction.
    Calculates the true remaining seconds to station arrival by matching each ping
    to the timestamp when the vehicle first reaches the station boundary.
    """
    conn = sqlite3.connect(db_path)
    query = """
    SELECT 
        ping_id, vehicle_id, direction, next_station_order,
        device_epoch, device_update_time, s_bus_m, cross_track_m,
        derived_speed_kmh, is_dwell, distance_remaining_m
    FROM v_bus_to_next_station
    WHERE route_code = ? AND distance_remaining_m >= 0 AND distance_remaining_m <= 2500
    ORDER BY vehicle_id, direction, device_epoch;
    """
    df = pd.read_sql_query(query, conn, params=[route_code])
    conn.close()

    if df.empty:
        return pd.DataFrame()

    df["derived_speed_kmh"] = df["derived_speed_kmh"].fillna(0.0)

    # Calculate actual arrival epoch at next station for each vehicle trip
    # Arrival epoch = minimum epoch where vehicle transitions to (next_station_order + 1)
    # or where distance_remaining_m <= 25m
    records = []
    for (vid, d), group in df.groupby(["vehicle_id", "direction"]):
        group = group.sort_values("device_epoch").reset_index(drop=True)

        # Map each next_station_order to its arrival epoch
        station_arrivals = {}
        for idx, row in group.iterrows():
            st_order = row["next_station_order"]
            # If vehicle is very close to station (<= 25m), record arrival
            if row["distance_remaining_m"] <= 25.0 and st_order not in station_arrivals:
                station_arrivals[st_order] = row["device_epoch"]

        # Assign actual remaining time (Y)
        for idx, row in group.iterrows():
            st_order = row["next_station_order"]
            if st_order in station_arrivals:
                actual_remaining_sec = station_arrivals[st_order] - row["device_epoch"]
                if 0 <= actual_remaining_sec <= 1800:  # Valid target window (up to 30 mins)
                    records.append({
                        "ping_id": row["ping_id"],
                        "vehicle_id": row["vehicle_id"],
                        "direction_encoded": 1 if d == "go" else 0,
                        "next_station_order": row["next_station_order"],
                        "s_bus_m": row["s_bus_m"],
                        "cross_track_m": row["cross_track_m"],
                        "derived_speed_kmh": row["derived_speed_kmh"],
                        "is_dwell": row["is_dwell"],
                        "distance_remaining_m": row["distance_remaining_m"],
                        "hour": pd.to_datetime(row["device_update_time"]).hour,
                        "minute": pd.to_datetime(row["device_update_time"]).minute,
                        "actual_remaining_sec": actual_remaining_sec
                    })

    result_df = pd.DataFrame(records)
    return result_df


if __name__ == "__main__":
    rc = sys.argv[1] if len(sys.argv) > 1 else "02"
    ds = extract_route_training_dataset(rc)
    print(f"Extracted {len(ds)} supervised training samples for Route {rc}.")
    if not ds.empty:
        print(ds[["distance_remaining_m", "derived_speed_kmh", "actual_remaining_sec"]].head())
