"""
Component 1.1.2: Fleet Catalog Manager
"""

from .catalog_manager import (
    load_cluster_config,
    save_cluster_config,
    search_vehicles_by_query
)

__all__ = [
    "load_cluster_config",
    "save_cluster_config",
    "search_vehicles_by_query"
]

