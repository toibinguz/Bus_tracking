"""
Cloud Crawler Step Entrypoint for GitHub Actions
Thin facade delegating directly to module_5_system_orchestration_and_runners.runner_5_1_github_actions_cloud_relay.
Ensures 100% backward compatibility for GitHub Actions workflow (.github/workflows/crawl_bus.yml).
"""

import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from module_5_system_orchestration_and_runners.runner_5_1_github_actions_cloud_relay import main

if __name__ == "__main__":
    main()
