"""
Step 3.4 ETA Serving and Live Bus Telemetry

Facade package: re-export hợp đồng public từ các module mới (dto/serving_service).
`busmap_service.py` cũ (đang ImportError) sẽ được retire ở task 10.
"""

from .dto import (
    ApproachingBusDTO,
    BusVehicleDTO,
    RouteItemDTO,
    RouteLiveResponse,
    RouteShapeResponse,
    RouteStationsResponse,
    SafeWindowDTO,
    StationEtaResponse,
    StationItemDTO,
    normalize_direction,
)
from .live_feed import fetch_live_vehicles_for_route
from .serving_service import BusMapServingService

__all__ = [
    "BusMapServingService",
    "fetch_live_vehicles_for_route",
    "normalize_direction",
    "BusVehicleDTO",
    "RouteItemDTO",
    "RouteLiveResponse",
    "RouteShapeResponse",
    "RouteStationsResponse",
    "StationItemDTO",
    "StationEtaResponse",
    "SafeWindowDTO",
    "ApproachingBusDTO",
]
