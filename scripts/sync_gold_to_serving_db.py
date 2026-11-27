"""Thin CLI wrapper for modules.lakehouse.serving_sync."""

from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from modules.lakehouse.serving_sync import SERVING_TABLES, main, sync_gold_to_serving_db  # noqa: E402

if __name__ == '__main__':
    main()
