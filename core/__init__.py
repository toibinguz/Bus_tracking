"""
Core package for HUST Bus & Traffic Crawler & ETA System
Exports clean modular API across Transport, Telemetry, Catalog, Traffic, Storage, and Analytics.
"""

from .config import (
    CONFIG_FILE,
    BUS_OUTPUT_DIR,
    TRAFFIC_OUTPUT_DIR,
    INCIDENT_OUTPUT_DIR,
    TOMTOM_QUOTA_FILE,
    DAILY_HEALTH_FILE,
    HANOI_BBOX,
    HUST_CORRIDOR_BBOX,
    HUST_BOTTLENECK_NODES,
    MAX_TOMTOM_FLOW_DAILY,
    MAX_TOMTOM_FLOW_MONTHLY,
    MAX_TOMTOM_INCIDENT_DAILY,
    MAX_TOMTOM_INCIDENT_MONTHLY,
    BUS_MICRO_BATCH_SIZE,
    BUS_MICRO_BATCH_DELAY_SEC,
    BUS_POLL_INTERVAL_SEC,
    SESSION_DURATION_SEC,
    get_hanoi_time,
    is_operating_hours,
    is_peak_hours,
    get_tomtom_api_key,
    get_hf_token
)

from .transport import (
    get_busmap_ip,
    fetch_single_bus_raw,
    get_busmap_device_id
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

from .traffic import (
    fetch_tomtom_flow,
    fetch_tomtom_incidents,
    execute_tomtom_flow_poll,
    execute_tomtom_incident_poll,
    execute_tomtom_poll,
    load_tomtom_quota_state,
    save_tomtom_quota_state
)

from .storage import (
    get_hf_today_batch_count,
    get_hf_today_traffic_batch_count,
    upload_batches_to_hf_native,
    save_bus_telemetry_batch
)

from .analytics import (
    evaluate_hotspot_congestion
)
