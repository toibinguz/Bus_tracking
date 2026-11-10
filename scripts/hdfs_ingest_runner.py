"""Upload only atomically closed host-spooled Bronze files from the private network."""

from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import Protocol


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WEBHDFS_URL = "http://namenode:9870"
DEFAULT_HDFS_USER = "root"


class BronzeUploader(Protocol):
    def upload(self, spool_file: str | Path) -> str: ...


def closed_spool_files(spool_root: str | Path) -> list[Path]:
    """Return final JSONL artifacts only; temporary writes are never eligible."""
    return sorted(Path(spool_root).glob("dt=*/hr=*/ingest-*.jsonl"))


def upload_closed_spool(spool_root: str | Path, uploader: BronzeUploader) -> list[str]:
    return [uploader.upload(spool_file) for spool_file in closed_spool_files(spool_root)]


def main(spool_root: str) -> None:
    sys.path.insert(0, str(REPO_ROOT))
    from module_2_big_data_storage_and_lakehouse.step_2_4_hdfs_history.webhdfs import WebHdfsUploader

    uploaded = upload_closed_spool(
        spool_root,
        WebHdfsUploader(
            base_url=os.environ.get("HDFS_WEBHDFS_URL", DEFAULT_WEBHDFS_URL),
            user_name=os.environ.get("HDFS_WEBHDFS_USER", DEFAULT_HDFS_USER),
        ),
    )
    print(f"uploaded={len(uploaded)}")
    for hdfs_path in uploaded:
        print(hdfs_path)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: hdfs_ingest_runner.py SPOOL_ROOT")
    main(sys.argv[1])
