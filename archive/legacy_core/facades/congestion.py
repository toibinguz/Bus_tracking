"""
Facade Module: core.congestion (Backward Compatibility Layer)
Exposes traffic congestion evaluation by delegating to module_4.
"""

from module_4_traffic_analytics_and_visualization import evaluate_hotspot_congestion

__all__ = [
    "evaluate_hotspot_congestion"
]
