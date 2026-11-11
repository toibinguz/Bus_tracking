"""Durable local spool for closed Bronze JSONL windows."""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from .contract import TelemetryEnvelope
from .receipt import RECEIPT_SUFFIX, file_sha256, load_receipt, receipt_path, write_receipt


SPOOL_SUFFIX = ".jsonl"
BUS_OPERATION_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")


def hour_partition(epoch_ms: int) -> tuple[str, str]:
    observed_at = datetime.fromtimestamp(epoch_ms / 1000, tz=BUS_OPERATION_TIMEZONE)
    return observed_at.date().isoformat(), observed_at.strftime("%H")


def write_closed_window(envelopes: list[TelemetryEnvelope], spool_root: str | Path) -> Path:
    """Atomically persist one same-hour source window before any network upload."""
    if not envelopes:
        raise ValueError("a spool window must contain at least one envelope")
    partitions = {hour_partition(item.observed_at_epoch_ms) for item in envelopes}
    if len(partitions) != 1:
        raise ValueError("a spool window must not span multiple UTC hours")
    dt, hour = partitions.pop()
    spool_directory = Path(spool_root) / f"dt={dt}" / f"hr={hour}"
    spool_directory.mkdir(parents=True, exist_ok=True)
    final_path = spool_directory / f"ingest-{uuid4()}{SPOOL_SUFFIX}"
    temporary_path = final_path.with_suffix(f"{SPOOL_SUFFIX}.tmp")
    with temporary_path.open("w", encoding="utf-8", newline="\n") as spool_file:
        for envelope in envelopes:
            spool_file.write(envelope.to_json_line())
            spool_file.write("\n")
        spool_file.flush()
        os.fsync(spool_file.fileno())
    os.replace(temporary_path, final_path)
    return final_path
