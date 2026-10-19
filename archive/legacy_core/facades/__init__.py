"""
Legacy Core Package (Deprecated Backward-Compatibility Shim)
All active functionality has been modularized into domain packages (module_1 to module_5) and config.
"""

from config import *
from module_1_telemetry_and_traffic_ingestion import (
    get_busmap_ip,
    fetch_single_bus_raw,
    get_busmap_device_id,
    load_cluster_config,
    save_cluster_config,
    search_vehicles_by_query,
    haversine_distance,
    sanitize_and_validate_telemetry,
    fetch_tomtom_flow,
    fetch_tomtom_incidents,
    execute_tomtom_flow_poll,
    execute_tomtom_incident_poll,
    execute_tomtom_poll,
    load_tomtom_quota_state,
    save_tomtom_quota_state,
    render_tomtom_cli_bar,
    TOMTOM_CIRCUIT_OPEN,
    get_hf_today_batch_count,
    get_hf_today_traffic_batch_count,
    fetch_hf_tomtom_quota_state,
    generate_hf_readme,
    sync_hf_metadata,
    upload_batches_to_hf_native,
    append_jsonl_records,
    save_bus_telemetry_batch,
    save_traffic_flow_batch,
    save_incidents_batch
)
from module_4_traffic_analytics_and_visualization import evaluate_hotspot_congestion
