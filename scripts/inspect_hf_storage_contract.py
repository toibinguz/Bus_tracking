"""Thin CLI wrapper for modules.lakehouse.hdfs.inspect_contract."""

from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from modules.lakehouse.hdfs.inspect_contract import describe, main, reference_profile  # noqa: E402

if __name__ == '__main__':
    main()
