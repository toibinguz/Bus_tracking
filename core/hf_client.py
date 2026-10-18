"""
Facade Module: core.hf_client (Backward Compatibility Layer)
Exposes Hugging Face native commit sync, batch counting, and quota sync
by delegating to core.storage subpackage.
"""

from .storage import (
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
