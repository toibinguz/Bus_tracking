"""
OSM Bus Routes Extractor Entrypoint
Thin facade delegating directly to module_2_osm_ground_truth_and_road_network.step_2_1_overpass_route_and_station_extractor.extract_all_osm_routes_cli.
"""

import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from module_2_osm_ground_truth_and_road_network.step_2_1_overpass_route_and_station_extractor.extract_all_osm_routes_cli import main

if __name__ == "__main__":
    sys.exit(main())
