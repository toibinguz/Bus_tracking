"""Canonical Module-1 to HDFS Bronze telemetry envelope."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, Mapping


SCHEMA_VERSION = "bus-telemetry.v1"
PROVENANCE_VALUES = frozenset({"observed", "replayed_observed", "synthetic_scale"})
COORDINATE_DECIMAL_PLACES = 6


def _canonical_coordinate(value: Any) -> str:
    return format(float(value), f".{COORDINATE_DECIMAL_PLACES}f")


def _epoch_milliseconds(value: Any) -> int:
    if isinstance(value, (int, float)):
        return int(float(value) * 1000) if abs(float(value)) < 10_000_000_000 else int(value)
    text = str(value).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("timestamps must include a UTC offset")
    return int(parsed.astimezone(timezone.utc).timestamp() * 1000)


def canonical_event_id(
    *,
    source_name: str,
    source_record_id: Any,
    route_id: Any,
    vehicle_id: Any,
    observed_at_epoch_ms: Any,
    lat: Any,
    lon: Any,
) -> str:
    """Return the stable SHA-256 identity specified by SPEC-25 section 4.1."""
    identity = {
        "lat": _canonical_coordinate(lat),
        "lon": _canonical_coordinate(lon),
        "observed_at_epoch_ms": int(observed_at_epoch_ms),
        "route_id": int(route_id),
        "source_name": str(source_name),
        "source_record_id": "" if source_record_id is None else str(source_record_id),
        "vehicle_id": int(vehicle_id),
    }
    encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TelemetryEnvelope:
    schema_version: str
    provenance: str
    source_window_id: str
    event_id: str
    observed_at_epoch_ms: int
    received_at_epoch_ms: int
    route_id: int
    route_code: str
    vehicle_id: int
    plate: str
    direction: int | str
    lat: float
    lon: float
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"unsupported schema version: {self.schema_version}")
        if self.provenance not in PROVENANCE_VALUES:
            raise ValueError(f"unsupported provenance: {self.provenance}")
        if not self.source_window_id:
            raise ValueError("source_window_id is required")
        if not self.route_code:
            raise ValueError("route_code is required")
        if len(self.event_id) != 64:
            raise ValueError("event_id must be a SHA-256 hex digest")

    def to_json_line(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def envelope_from_sanitized_record(
    record: Mapping[str, Any],
    *,
    source_name: str,
    source_window_id: str,
    provenance: str,
    route_code: str,
    source_record_id: Any = None,
) -> TelemetryEnvelope:
    """Adapt an existing sanitized crawler record without changing its local contract."""
    observed_at_epoch_ms = _epoch_milliseconds(record["device_update_time"])
    received_at_epoch_ms = _epoch_milliseconds(record["crawled_at"])
    event_id = canonical_event_id(
        source_name=source_name,
        source_record_id=source_record_id,
        route_id=record["route_id"],
        vehicle_id=record["vehicle_id"],
        observed_at_epoch_ms=observed_at_epoch_ms,
        lat=record["lat"],
        lon=record["lon"],
    )
    return TelemetryEnvelope(
        schema_version=SCHEMA_VERSION,
        provenance=provenance,
        source_window_id=source_window_id,
        event_id=event_id,
        observed_at_epoch_ms=observed_at_epoch_ms,
        received_at_epoch_ms=received_at_epoch_ms,
        route_id=int(record["route_id"]),
        route_code=str(route_code),
        vehicle_id=int(record["vehicle_id"]),
        plate=str(record.get("plate") or ""),
        direction=record.get("direction", 0),
        lat=float(record["lat"]),
        lon=float(record["lon"]),
        payload=dict(record),
    )
