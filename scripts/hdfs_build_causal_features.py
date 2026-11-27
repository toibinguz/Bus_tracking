"""Thin CLI wrapper for modules.lakehouse.hdfs.gold_features_spark."""

from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from modules.lakehouse.hdfs.gold_features_spark import main  # noqa: E402

if __name__ == '__main__':
    main()
