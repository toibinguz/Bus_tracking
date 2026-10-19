"""
Submodule 1.1: BusMap Telemetry Stream Ingestion
Combines transport, device pool, fleet catalog, and telemetry sanitization.
"""

from .component_1_1_1_transport_and_device_pool import (
    get_busmap_ip, fetch_single_bus_raw, get_busmap_device_id,
    get_current_progressive_pool_size, MAX_POOL_SIZE
)
from .component_1_1_2_fleet_catalog_manager import (
    load_cluster_config, save_cluster_config, search_vehicles_by_query
)
from .component_1_1_3_sanitizer_and_kinematics import (
    haversine_distance, sanitize_and_validate_telemetry
)

__all__ = [
    "get_busmap_ip", "fetch_single_bus_raw", "get_busmap_device_id",
    "get_current_progressive_pool_size", "MAX_POOL_SIZE",
    "load_cluster_config", "save_cluster_config", "search_vehicles_by_query",
    "haversine_distance", "sanitize_and_validate_telemetry"
]

