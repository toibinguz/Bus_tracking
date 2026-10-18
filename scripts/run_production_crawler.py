"""
Production Crawler Entrypoint
Thin facade delegating directly to module_5_system_orchestration_and_runners.runner_5_2_local_production_daemon.
"""

import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from module_5_system_orchestration_and_runners.runner_5_2_local_production_daemon import main

if __name__ == "__main__":
    main()
