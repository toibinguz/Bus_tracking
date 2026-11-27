"""Cross-platform C++17 native projection, baseline, and causal feature kernels."""

from .native_bridge import (
    build_route_baseline_native,
    extract_route_causal_features_native,
    is_native_available,
    project_route_pings_native,
)

__all__ = [
    "build_route_baseline_native",
    "extract_route_causal_features_native",
    "is_native_available",
    "project_route_pings_native",
]
