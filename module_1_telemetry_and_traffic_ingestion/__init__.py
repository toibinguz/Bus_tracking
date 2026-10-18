"""
Module 1: Realtime Telemetry & External Traffic Ingestion Layer
Unified exports for Submodule 1.1 (BusMap), Submodule 1.2 (TomTom Incident), and Submodule 1.3 (Cloud & Local Lake).
"""

from .submodule_1_1_busmap_telemetry_stream import (
    get_busmap_ip,
    fetch_single_bus_raw,
    get_busmap_device_id,
    get_current_progressive_pool_size,
    MAX_POOL_SIZE,
    load_cluster_config,
    save_cluster_config,
    search_vehicles_by_query,
    haversine_distance,
    sanitize_and_validate_telemetry
)

from .submodule_1_2_tomtom_incident_governor import (
    fetch_tomtom_flow,
    fetch_tomtom_incidents,
    execute_tomtom_flow_poll,
    execute_tomtom_incident_poll,
    execute_tomtom_poll,
    load_tomtom_quota_state,
    save_tomtom_quota_state,
    render_tomtom_cli_bar,
    TOMTOM_CIRCUIT_OPEN
)

from .submodule_1_3_cloud_lake_persistence import (
    get_hf_today_batch_count,
    get_hf_today_traffic_batch_count,
    fetch_hf_tomtom_quota_state,
    generate_hf_readme,
    sync_hf_metadata,
    upload_batches_to_hf_native,
    sync_bus_telemetry_from_hf,
    append_jsonl_records,
    save_bus_telemetry_batch,
    save_traffic_flow_batch,
    save_incidents_batch,
    preprocess_telemetry_dataset,
    load_preprocessed_route_pings
)

__all__ = [
    # Submodule 1.1
    "get_busmap_ip", "fetch_single_bus_raw", "get_busmap_device_id",
    "get_current_progressive_pool_size", "MAX_POOL_SIZE",
    "load_cluster_config", "save_cluster_config", "search_vehicles_by_query",
    "haversine_distance", "sanitize_and_validate_telemetry",
    # Submodule 1.2
    "fetch_tomtom_flow", "fetch_tomtom_incidents",
    "execute_tomtom_flow_poll", "execute_tomtom_incident_poll",
    "execute_tomtom_poll", "load_tomtom_quota_state",
    "save_tomtom_quota_state", "render_tomtom_cli_bar",
    "TOMTOM_CIRCUIT_OPEN",
    # Submodule 1.3
    "get_hf_today_batch_count", "get_hf_today_traffic_batch_count",
    "fetch_hf_tomtom_quota_state", "generate_hf_readme",
    "sync_hf_metadata", "upload_batches_to_hf_native",
    "sync_bus_telemetry_from_hf",
    "append_jsonl_records", "save_bus_telemetry_batch",
    "save_traffic_flow_batch", "save_incidents_batch",
    "preprocess_telemetry_dataset", "load_preprocessed_route_pings"
]

