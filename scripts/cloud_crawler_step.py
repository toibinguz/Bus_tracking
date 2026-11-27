"""Thin CLI wrapper for modules.ingestion.crawler.cloud_crawler_runner."""

from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from modules.ingestion.crawler.cloud_crawler_runner import main  # noqa: E402

if __name__ == '__main__':
    main()
