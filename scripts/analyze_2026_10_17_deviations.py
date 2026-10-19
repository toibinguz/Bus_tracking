"""
Telemetry Deviation & Skew Auditor Entrypoint
Thin facade delegating directly to module_4_traffic_analytics_and_visualization.step_4_1_telemetry_data_auditor.telemetry_loss_and_skew_auditor.
"""

import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from module_4_traffic_analytics_and_visualization.step_4_1_telemetry_data_auditor.telemetry_loss_and_skew_auditor import main

if __name__ == "__main__":
    main()
