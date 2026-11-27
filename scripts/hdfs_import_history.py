"""Thin CLI wrapper for modules.lakehouse.hdfs.import_history."""

from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from modules.lakehouse.hdfs.import_history import main, plan, run, upload  # noqa: E402

if __name__ == '__main__':
    main()
