"""
Module 1: Real-time Telemetry, Ground Truth & Kinematic Preprocessing Layer
Unified exports for the Canonical 3-Tier Architecture.
"""

from .step_1_1_busmap_crawler_and_relay.device_pool import (
    get_busmap_device_id,
    get_current_progressive_pool_size,
    MAX_POOL_SIZE
)

from .step_1_1_busmap_crawler_and_relay.socket_client import (
    fetch_single_bus_raw,
    get_busmap_ip
)

from .step_1_1_busmap_crawler_and_relay.catalog_manager import (
    load_cluster_config,
    save_cluster_config,
    search_vehicles_by_query
)

from .step_1_1_busmap_crawler_and_relay.incident_client import (
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

from .step_1_1_busmap_crawler_and_relay.hotspot_evaluator import (
    evaluate_hotspot_congestion
)

from .step_1_1_busmap_crawler_and_relay.hf_lake_sync import (
    get_hf_today_batch_count,
    get_hf_today_traffic_batch_count,
    fetch_hf_tomtom_quota_state,
    upload_batches_to_hf_native
)

from .step_1_1_busmap_crawler_and_relay.local_partition_writer import (
    append_jsonl_records,
    save_bus_telemetry_batch,
    save_traffic_flow_batch,
    save_incidents_batch
)

from .step_1_2_timbus_master_ground_truth.timbus_client import (
    TimBusClient
)

from .step_1_2_timbus_master_ground_truth.timbus_pipeline import (
    TimBusGroundTruthPipeline
)

from .step_1_3_telemetry_kinematic_sanitizer.kinematic_engine import (
    haversine_distance
)

from .step_1_3_telemetry_kinematic_sanitizer.telemetry_sanitizer import (
    sanitize_and_validate_telemetry
)

from .step_1_4_frenet_spatial_projection.multi_route_projector import (
    project_route,
    run_multi_route_projection
)

__all__ = [
    # Step 1.1: Telemetry & Ingestion
    "get_busmap_device_id", "get_current_progressive_pool_size", "MAX_POOL_SIZE",
    "fetch_single_bus_raw", "get_busmap_ip",
    "load_cluster_config", "save_cluster_config", "search_vehicles_by_query",
    "fetch_tomtom_flow", "fetch_tomtom_incidents",
    "execute_tomtom_flow_poll", "execute_tomtom_incident_poll", "execute_tomtom_poll",
    "load_tomtom_quota_state", "save_tomtom_quota_state", "render_tomtom_cli_bar",
    "TOMTOM_CIRCUIT_OPEN", "evaluate_hotspot_congestion",
    "get_hf_today_batch_count", "get_hf_today_traffic_batch_count", "fetch_hf_tomtom_quota_state",
    "upload_batches_to_hf_native", "append_jsonl_records",
    "save_bus_telemetry_batch", "save_traffic_flow_batch", "save_incidents_batch",

    # Step 1.2: Master Ground Truth
    "TimBusClient", "TimBusGroundTruthPipeline",

    # Step 1.3: Kinematic Sanitizer
    "haversine_distance", "sanitize_and_validate_telemetry",

    # Step 1.4: Frenet Spatial Projection
    "project_route", "run_multi_route_projection"
]
