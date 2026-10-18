"""
Facade Module: core.congestion (Backward Compatibility Layer)
Exposes traffic congestion evaluation by delegating to core.analytics subpackage.
"""

from .analytics import evaluate_hotspot_congestion

__all__ = [
    "evaluate_hotspot_congestion"
]
