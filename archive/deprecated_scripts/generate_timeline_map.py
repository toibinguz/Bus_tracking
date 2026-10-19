"""
High-Resolution 60FPS Telemetry Timeline Map Generator Entrypoint
Thin facade delegating directly to module_4_traffic_analytics_and_visualization.step_4_2_high_resolution_timeline_map_visualizer.timeline_map_60fps_generator.
"""

import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from module_4_traffic_analytics_and_visualization.step_4_2_high_resolution_timeline_map_visualizer.timeline_map_60fps_generator import main

if __name__ == "__main__":
    main()

