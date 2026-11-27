"""Thin CLI wrapper for modules.eta.evaluation.analyze_eta_live."""

from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from modules.eta.evaluation.analyze_eta_live import crossing_events, main, metrics  # noqa: E402

if __name__ == '__main__':
    main()
