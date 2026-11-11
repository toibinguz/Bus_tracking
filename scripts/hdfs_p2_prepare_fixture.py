"""Create one closed P2 replay fixture for the accepted P1 ingest path."""

from __future__ import annotations

import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from module_2_big_data_storage_and_lakehouse.step_2_4_hdfs_history.contract import TelemetryEnvelope
from module_2_big_data_storage_and_lakehouse.step_2_4_hdfs_history.spool import write_closed_window


def main(spool_root: str) -> None:
    fixture_path = REPO_ROOT / "tests" / "fixtures" / "hdfs_p2" / "p2_replayed_observed.json"
    values = json.loads(fixture_path.read_text(encoding="utf-8"))
    envelopes = [TelemetryEnvelope(**value) for value in values]
    spool_file = write_closed_window(envelopes, spool_root)
    print(spool_file)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: hdfs_p2_prepare_fixture.py SPOOL_ROOT")
    main(sys.argv[1])
