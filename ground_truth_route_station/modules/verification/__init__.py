"""
Verification Module
"""
from .projection import (
    RoutePolylineProjector,
    project_point_onto_segment,
    to_metric_xy,
    to_wgs84_latlon
)
from .evaluator import (
    evaluate_route_telemetry,
    ON_ROUTE_STRICT_METERS,
    ON_ROUTE_TOLERANT_METERS
)

__all__ = [
    "RoutePolylineProjector",
    "project_point_onto_segment",
    "to_metric_xy",
    "to_wgs84_latlon",
    "evaluate_route_telemetry",
    "ON_ROUTE_STRICT_METERS",
    "ON_ROUTE_TOLERANT_METERS"
]

