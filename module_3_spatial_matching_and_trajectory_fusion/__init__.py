"""
Module 3: Spatial Map Matching, Trajectory Fusion & Kinematic Interpolation Layer
Exports:
- step_3_1_spherical_orthogonal_projector
- step_3_2_virtual_ghost_point_and_detour
- step_3_3_route_curve_kinematic_interpolator
"""

from .step_3_1_spherical_orthogonal_projector import (
    haversine_distance_m,
    spherical_bearing_rad,
    project_point_onto_spherical_segment,
    RoutePolylineProjector,
    EARTH_RADIUS_M,
    evaluate_route_telemetry,
    ON_ROUTE_STRICT_METERS,
    ON_ROUTE_TOLERANT_METERS,
    STOP_DWELL_RADIUS_METERS
)
from .step_3_2_virtual_ghost_point_and_detour import (
    compute_virtual_ghost_point
)
from .step_3_3_route_curve_kinematic_interpolator import (
    point_at_chainage
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
    "STOP_DWELL_RADIUS_METERS",
    "compute_virtual_ghost_point",
    "point_at_chainage"
]

