"""
Facade Module: core.traffic_client (Backward Compatibility Layer)
Delegates directly to module_1_telemetry_and_traffic_ingestion.submodule_1_2_tomtom_incident_governor.
"""

from module_1_telemetry_and_traffic_ingestion.submodule_1_2_tomtom_incident_governor import (
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

__all__ = [
    "fetch_tomtom_flow",
    "fetch_tomtom_incidents",
    "execute_tomtom_flow_poll",
    "execute_tomtom_incident_poll",
    "execute_tomtom_poll",
    "load_tomtom_quota_state",
    "save_tomtom_quota_state",
    "render_tomtom_cli_bar",
    "TOMTOM_CIRCUIT_OPEN"
]
