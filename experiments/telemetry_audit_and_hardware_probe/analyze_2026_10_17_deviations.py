"""
Telemetry Deviation & Skew Auditor Entrypoint
Delegates directly to local telemetry_loss_and_skew_auditor.
"""

import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .telemetry_loss_and_skew_auditor import main

if __name__ == "__main__":
    main()
