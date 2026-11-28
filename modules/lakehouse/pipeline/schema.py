"""Ordered logical fields for Spark and Arrow writers (name, type, nullable)."""
from modules.eta.features.causal_eta import FEATURES

SILVER = tuple((name, kind, True) for kind, names in (
    ("string", ("event_id", "route_code", "plate", "device_update_time", "direction", "provenance")),
    ("int64", ("legacy_ping_id", "route_id", "vehicle_id")),
    ("float64", ("device_epoch_s", "device_epoch", "lat", "lon", "s_bus_m", "cross_track_m", "derived_speed_kmh")),
) for name in names)

BASELINE = (
    ("route_code", "string", False),
    ("direction", "string", False),
    ("from_station_order", "int32", False),
    ("to_station_order", "int32", False),
    ("from_station_id", "int32", False),
    ("to_station_id", "int32", False),
    ("from_station_name", "string", True),
    ("to_station_name", "string", True),
    ("segment_length_m", "float64", False),
    ("day_type", "int32", False),
    ("hour_slot", "int32", False),
    ("sample_count", "int32", False),
    ("quality_tier", "int32", False),
    ("tt_p10_sec", "float64", False),
    ("tt_p50_sec", "float64", False),
    ("tt_p90_sec", "float64", False),
    ("tt_mean_sec", "float64", False),
    ("tt_std_sec", "float64", False),
)

CAUSAL = tuple((f, "float32", True) for f in FEATURES) + (
    ("route", "string", False), ("vehicle", "string", False), ("journey", "int64", False),
    ("target", "int64", False), ("split", "string", False), ("as_of", "float64", False),
    ("eta_seconds", "float64", False), ("bracket_before", "float64", False),
    ("bracket_after", "float64", False), ("crossing_epoch", "float64", False),
    ("history_seconds", "float64", False),
)
