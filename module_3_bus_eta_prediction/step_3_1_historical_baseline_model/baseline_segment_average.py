"""
Module 3: Bus ETA Prediction Engine
Subcomponent: step_3_1_historical_baseline_model
File: baseline_segment_average.py

Historical Segment Average Travel Time Matrix (Baseline Model).
Calculates the statistical travel time (median, mean, P90) between consecutive station pairs (S_k -> S_{k+1})
segmented by operational time windows (Morning Peak, Off-Peak, Evening Peak, Night).
Acts as the empirical benchmark against which all ML models (XGBoost/LightGBM) are evaluated.
"""

import os
import sys
import sqlite3
import pandas as pd
import numpy as np
from typing import Dict, Any, Optional

# Ensure project root in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))
sys.path.insert(0, os.path.abspath("."))


DEFAULT_DB_PATH = "data/telemetry_audit_2026_10_17_18.db"


def get_time_window_bin(hour: int) -> str:
    """Classify hour of day into transit operational windows."""
    if 6 <= hour < 9:
        return "MORNING_PEAK"
    elif 9 <= hour < 16:
        return "OFF_PEAK_DAY"
    elif 16 <= hour < 19:
        return "EVENING_PEAK"
    else:
        return "NIGHT"


class HistoricalSegmentAverageModel:
    """Computes and serves baseline segment travel times."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        self.segment_matrix: Dict[Tuple[str, str, int, str], float] = {}

    def fit_route(self, route_code: str) -> pd.DataFrame:
        """
        Derive travel time between stations from sequential vehicle pings.
        Returns a summary DataFrame with segment transit metrics.
        """
        conn = sqlite3.connect(self.db_path)
        query = """
        SELECT 
            vehicle_id, direction, next_station_order, next_station_name,
            device_epoch, device_update_time, s_bus_m, distance_remaining_m
        FROM v_bus_to_next_station
        WHERE route_code = ?
        ORDER BY vehicle_id, direction, device_epoch;
        """
        df = pd.read_sql_query(query, conn, params=[route_code])
        conn.close()

        if df.empty:
            print(f"No projected data found for Route {route_code}.")
            return pd.DataFrame()

        # Parse hour and time window
        df["hour"] = pd.to_datetime(df["device_update_time"]).dt.hour
        df["time_window"] = df["hour"].apply(get_time_window_bin)

        # Detect station arrival transitions: vehicle transitions from station order K to K+1
        # Transit duration = time spent between station transitions
        transitions = []
        for (vid, d), group in df.groupby(["vehicle_id", "direction"]):
            group = group.sort_values("device_epoch")
            orders = group["next_station_order"].values
            epochs = group["device_epoch"].values
            windows = group["time_window"].values

            for i in range(1, len(orders)):
                # When vehicle reaches station K and moves to K+1
                if orders[i] == orders[i - 1] + 1:
                    transit_sec = epochs[i] - epochs[i - 1]
                    if 10.0 <= transit_sec <= 1200.0:  # Reasonable transit time between 2 stations
                        transitions.append({
                            "route_code": route_code,
                            "direction": d,
                            "from_station_order": orders[i - 1],
                            "to_station_order": orders[i],
                            "time_window": windows[i],
                            "transit_sec": transit_sec
                        })

        if not transitions:
            print(f"No direct station transitions identified for Route {route_code}.")
            return pd.DataFrame()

        trans_df = pd.DataFrame(transitions)
        summary = trans_df.groupby(["route_code", "direction", "from_station_order", "to_station_order", "time_window"]).agg(
            sample_count=("transit_sec", "count"),
            median_transit_sec=("transit_sec", "median"),
            mean_transit_sec=("transit_sec", "mean"),
            std_transit_sec=("transit_sec", "std"),
            p90_transit_sec=("transit_sec", lambda x: np.percentile(x, 90))
        ).reset_index()

        summary["mean_transit_sec"] = summary["mean_transit_sec"].round(1)
        summary["median_transit_sec"] = summary["median_transit_sec"].round(1)

        return summary


def run_baseline_evaluation(route_code: str = "02", db_path: str = DEFAULT_DB_PATH):
    print("=" * 80)
    print(f"HISTORICAL SEGMENT AVERAGE MODEL (BASELINE) FOR ROUTE {route_code}")
    print("=" * 80)

    model = HistoricalSegmentAverageModel(db_path=db_path)
    summary_df = model.fit_route(route_code)

    if not summary_df.empty:
        print(f"Successfully generated baseline matrix with {len(summary_df)} segment-window combinations.")
        print("\nSample Segment Travel Times (First 10 rows):")
        print(summary_df[["direction", "from_station_order", "to_station_order", "time_window", "sample_count", "median_transit_sec", "mean_transit_sec"]].head(10).to_string(index=False))

        # Overall route statistics
        overall_median = summary_df["median_transit_sec"].median()
        print(f"\nOverall Median Segment Travel Time across Route {route_code}: {overall_median:.1f} seconds (~{overall_median/60:.2f} mins/segment)")
    print("=" * 80)


if __name__ == "__main__":
    rc = sys.argv[1] if len(sys.argv) > 1 else "02"
    run_baseline_evaluation(rc)
