"""Additive adapter from sanitized crawler batches to SPEC-25 Bronze envelopes."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterable, Mapping

from module_2_big_data_storage_and_lakehouse.step_2_4_hdfs_history.contract import (
    TelemetryEnvelope,
    envelope_from_sanitized_record,
)


def load_route_code_lookup(database_path: str | Path) -> dict[int, str]:
    """Read the existing canonical route master; no route code is guessed."""
    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(
            "SELECT route_id, route_code FROM canonical_route_master"
        ).fetchall()
    return {int(route_id): str(route_code) for route_id, route_code in rows}


def adapt_sanitized_batch(
    records: Iterable[Mapping[str, Any]],
    *,
    source_window_id: str,
    provenance: str,
    route_codes: Mapping[int, str],
    source_name: str = "busmap",
) -> list[TelemetryEnvelope]:
    """Return envelopes for one crawler window, failing closed on unknown routes."""
    envelopes: list[TelemetryEnvelope] = []
    for record in records:
        route_id = int(record["route_id"])
        if route_id not in route_codes:
            raise ValueError(f"route_id {route_id} is absent from canonical_route_master")
        envelopes.append(
            envelope_from_sanitized_record(
                record,
                source_name=source_name,
                source_window_id=source_window_id,
                provenance=provenance,
                route_code=route_codes[route_id],
                source_record_id=record.get("ping_id"),
            )
        )
    return envelopes
