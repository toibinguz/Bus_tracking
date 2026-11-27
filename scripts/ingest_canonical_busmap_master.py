"""Thin CLI wrapper for modules.ingestion.gtfs.ingest_busmap_canonical."""

from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from modules.ingestion.gtfs.ingest_busmap_canonical import main  # noqa: E402

if __name__ == '__main__':
    main()
