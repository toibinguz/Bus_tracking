"""
Facade Module: core.hf_client (Backward Compatibility Layer)
Delegates directly to module_1_telemetry_and_traffic_ingestion.submodule_1_3_cloud_lake_persistence.
"""

from module_1_telemetry_and_traffic_ingestion.submodule_1_3_cloud_lake_persistence import (
    get_hf_today_batch_count,
    get_hf_today_traffic_batch_count,
    fetch_hf_tomtom_quota_state,
    generate_hf_readme,
    sync_hf_metadata,
    upload_batches_to_hf_native
)

__all__ = [
    "get_hf_today_batch_count",
    "get_hf_today_traffic_batch_count",
    "fetch_hf_tomtom_quota_state",
    "generate_hf_readme",
    "sync_hf_metadata",
    "upload_batches_to_hf_native"
]
