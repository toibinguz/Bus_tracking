"""
Facade Module: core.bus_client (Backward Compatibility Layer)
Exposes low-level transport, telemetry sanitization, kinematics and fleet catalog
by delegating to their respective domain subpackages:
- core.transport
- core.telemetry
- core.catalog
"""

from .transport import (
    get_busmap_ip,
    fetch_single_bus_raw,
    get_busmap_device_id,
    SOCKET_TIMEOUT_SEC,
    SOCKET_RETRY_TIMEOUT_SEC
)
from .telemetry import (
    haversine_distance,
    sanitize_and_validate_telemetry
)
from .catalog import (
    load_cluster_config,
    save_cluster_config,
    search_vehicles_by_query
)

__all__ = [
    "get_busmap_ip",
    "fetch_single_bus_raw",
    "get_busmap_device_id",
    "SOCKET_TIMEOUT_SEC",
    "SOCKET_RETRY_TIMEOUT_SEC",
    "haversine_distance",
    "sanitize_and_validate_telemetry",
    "load_cluster_config",
    "save_cluster_config",
    "search_vehicles_by_query"
]
