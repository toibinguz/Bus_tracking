"""
Daily Catalog Refresh Entrypoint
Thin facade delegating directly to module_5_system_orchestration_and_runners.runner_5_6_daily_catalog_refresher.
"""

import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from module_5_system_orchestration_and_runners.runner_5_6_daily_catalog_refresher import main

if __name__ == "__main__":
    main()
