"""
Facade Module: core.bus_client (Backward Compatibility Layer)
Delegates directly to module_1_telemetry_and_traffic_ingestion.submodule_1_1_busmap_telemetry_stream.
"""

from module_1_telemetry_and_traffic_ingestion.submodule_1_1_busmap_telemetry_stream import (
    get_busmap_ip,
    fetch_single_bus_raw,
    get_busmap_device_id,
    load_cluster_config,
    save_cluster_config,
    search_vehicles_by_query,
    haversine_distance,
    sanitize_and_validate_telemetry
)

__all__ = [
    "get_busmap_ip",
    "fetch_single_bus_raw",
    "get_busmap_device_id",
    "load_cluster_config",
    "save_cluster_config",
    "search_vehicles_by_query",
    "haversine_distance",
    "sanitize_and_validate_telemetry"
]
