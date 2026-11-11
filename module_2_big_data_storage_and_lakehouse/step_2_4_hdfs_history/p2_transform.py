"""Bounded Spark/HDFS P2 transform helpers (SPEC-35)."""

from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import json
from typing import Any, Iterable, Mapping

from module_1_data_ingestion_and_preprocessing.step_1_4_frenet_spatial_projection.projection_boundary import (
    ProjectableEvent,
    project_route_events,
)
from module_2_big_data_storage_and_lakehouse.step_2_4_hdfs_history.contract import (
    SCHEMA_VERSION,
    TelemetryEnvelope,
)


TRANSFORM_SCHEMA_VERSION = "hdfs-p2.v1"


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_hex(value: bytes) -> str:
    return sha256(value).hexdigest()


def source_direction(value: Any) -> str:
    if value == 0 or value == "0" or value == "go":
        return "go"
    if value == 1 or value == "1" or value == "re":
        return "re"
    return "unknown"


def validate_envelope(value: Mapping[str, Any]) -> TelemetryEnvelope:
    return TelemetryEnvelope(
        schema_version=value["schema_version"],
        provenance=value["provenance"],
        source_window_id=value["source_window_id"],
        event_id=value["event_id"],
        observed_at_epoch_ms=int(value["observed_at_epoch_ms"]),
        received_at_epoch_ms=int(value["received_at_epoch_ms"]),
        route_id=int(value["route_id"]),
        route_code=str(value["route_code"]),
        vehicle_id=int(value["vehicle_id"]),
        plate=str(value["plate"]),
        direction=value["direction"],
        lat=float(value["lat"]),
        lon=float(value["lon"]),
        payload=dict(value["payload"]),
    )


def p2_job_key(
    *,
    bronze_path: str,
    bronze_sha256: str,
    source_window_id: str,
    reference_sha256: str,
    source_revision_sha256: str,
) -> str:
    return sha256_hex(
        canonical_json_bytes(
            {
                "bronze_path": bronze_path,
                "bronze_sha256": bronze_sha256,
                "reference_sha256": reference_sha256,
                "source_revision_sha256": source_revision_sha256,
                "source_window_id": source_window_id,
                "transform_schema_version": TRANSFORM_SCHEMA_VERSION,
            }
        )
    )


def project_distinct_envelopes(
    envelopes: Iterable[TelemetryEnvelope], reference: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Deduplicate identity then invoke the single accepted projection boundary."""
    unique = {envelope.event_id: envelope for envelope in envelopes}
    ordered = [unique[event_id] for event_id in sorted(unique)]
    events = [
        ProjectableEvent(
            event_id=envelope.event_id,
            legacy_ping_id=(
                int(envelope.payload["legacy_ping_id"])
                if envelope.payload.get("legacy_ping_id") is not None
                else None
            ),
            route_id=envelope.route_id,
            route_code=envelope.route_code,
            vehicle_id=envelope.vehicle_id,
            plate=envelope.plate or None,
            device_update_time=str(envelope.payload["device_update_time"]),
            device_epoch_s=envelope.observed_at_epoch_ms / 1000,
            direction_hint=source_direction(envelope.direction),
            current_station_id=(
                int(envelope.payload["current_station_id"])
                if envelope.payload.get("current_station_id") is not None
                else None
            ),
            lat=envelope.lat,
            lon=envelope.lon,
        )
        for envelope in ordered
    ]
    station_lookup = {
        (int(item["route_id"]), int(item["station_id"])): str(item["direction"])
        for item in reference["station_direction_lookup"]
    }
    projected, diagnostics = project_route_events(events, reference["shape_by_direction"], station_lookup)
    lineage = {envelope.event_id: envelope for envelope in ordered}
    rows = []
    for projected_event in projected:
        envelope = lineage[projected_event.event_id]
        row = asdict(projected_event)
        row.update(
            {
                "source_window_id": envelope.source_window_id,
                "provenance": envelope.provenance,
                "device_epoch_ms": envelope.observed_at_epoch_ms,
                "ingested_at_epoch_ms": envelope.received_at_epoch_ms,
            }
        )
        rows.append(row)
    return rows, diagnostics
