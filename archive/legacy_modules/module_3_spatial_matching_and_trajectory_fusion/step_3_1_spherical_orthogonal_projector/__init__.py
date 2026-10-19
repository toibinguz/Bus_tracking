"""
Step 3.1: Spherical Cross-Track Projector & Verification Evaluator
"""

from .spherical_cross_track_projector import (
    haversine_distance_m,
    spherical_bearing_rad,
    project_point_onto_spherical_segment,
    RoutePolylineProjector,
    EARTH_RADIUS_M
)
from .route_telemetry_evaluator import (
    evaluate_route_telemetry,
    ON_ROUTE_STRICT_METERS,
    ON_ROUTE_TOLERANT_METERS,
    STOP_DWELL_RADIUS_METERS
)

__all__ = [
    "haversine_distance_m",
    "spherical_bearing_rad",
    "project_point_onto_spherical_segment",
    "RoutePolylineProjector",
    "EARTH_RADIUS_M",
    "evaluate_route_telemetry",
    "ON_ROUTE_STRICT_METERS",
    "ON_ROUTE_TOLERANT_METERS",
    "STOP_DWELL_RADIUS_METERS"
]

