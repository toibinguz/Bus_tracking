"""Resolved business configuration, stage order and publication metadata."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Optional, Tuple

from config.system_config import (
    BASELINE_FIT_END_DATE, CANONICAL_START_DATE, TEST_SPLIT_START_DATE,
    TEST_SPLIT_END_DATE, TRAIN_SPLIT_END_DATE, TZ_HANOI,
)

FEATURE_START = (date.fromisoformat(BASELINE_FIT_END_DATE) + timedelta(days=1)).isoformat()
FORECAST_SECONDS = 120.0
MAX_SESSION_EVENTS = 20000
MAX_BATCH_BYTES = 16 * 1024 * 1024
STAGES = ("silver", "baseline", "features", "serving")


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(content):
    return sha256(content).hexdigest()


def batch_identity(dataset, path, content_sha256):
    return digest(encoded(dict(dataset=dataset, path=path, content_sha256=content_sha256)))


def resolve_routes(routes, all_routes, catalog):
    if routes:
        if all_routes:
            raise ValueError("choose explicit routes or all routes")
        return tuple(sorted(set(routes)))
    if all_routes:
        return None
    return tuple(sorted({str(item["route_no"]) for item in catalog["routes"] if item.get("route_no") is not None}))


def split_epoch(value):
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=TZ_HANOI)
    return stamp.timestamp()


@dataclass(frozen=True)
class PipelineSpec:
    stages: Tuple[str, ...]
    routes: Optional[Tuple[str, ...]]
    fit_end_date: str = BASELINE_FIT_END_DATE
    from_day: str = FEATURE_START
    to_day: str = TEST_SPLIT_END_DATE
    test_start: str = TEST_SPLIT_START_DATE
    validation_start: Optional[str] = None
    forecast_every: float = FORECAST_SECONDS
    silver_start: str = CANONICAL_START_DATE
    feature_routes: Optional[Tuple[str, ...]] = None

    def __post_init__(self):
        if not self.stages or set(self.stages).difference(STAGES):
            raise ValueError("unknown or empty pipeline stages")
        if date.fromisoformat(self.fit_end_date) > date.fromisoformat(TRAIN_SPLIT_END_DATE):
            raise ValueError("baseline fit cutoff exceeds training boundary")
        if self.feature_routes is not None and self.routes is not None and set(self.feature_routes).difference(self.routes):
            raise ValueError("feature routes must belong to Silver scope")
        if "features" in self.stages:
            if date.fromisoformat(self.from_day) > date.fromisoformat(self.to_day):
                raise ValueError("feature window overlaps fitting or is reversed")
            if not math.isfinite(self.forecast_every) or self.forecast_every <= 0:
                raise ValueError("forecast cadence must be positive")
            if self.validation_epoch > self.test_epoch:
                raise ValueError("validation split starts after test")

    @property
    def validation_epoch(self):
        return split_epoch(self.validation_start or self.test_start)

    @property
    def test_epoch(self):
        return split_epoch(self.test_start)

    def includes_silver(self, route, day):
        return day >= self.silver_start and (self.routes is None or route in self.routes)

    @property
    def selected_features(self):
        return self.feature_routes if self.feature_routes is not None else self.routes

    def includes_fit(self, day):
        return day <= self.fit_end_date

    def includes_features(self, day):
        return (day >= self.from_day) & (day <= self.to_day)

    def manifest(self):
        return dict(asdict(self), timezone="Asia/Ho_Chi_Minh")


def run_pipeline(spec, adapter):
    """Adapters receive the completed builds from this run, in dependency order."""
    dependencies = {"silver": (), "baseline": ("silver",), "features": ("baseline", "silver"), "serving": ("baseline",)}
    results = {}
    for stage in STAGES:
        if stage in spec.stages:
            for product in dependencies[stage]:
                if product not in results:
                    results[product] = adapter.pin(product, results)
            if stage == "features":
                if results["silver"]["snapshot_id"] != results["baseline"]["snapshot_id"]:
                    raise ValueError("baseline and Silver snapshot mismatch")
                if date.fromisoformat(results["baseline"]["fit_end_date"]) >= date.fromisoformat(spec.from_day):
                    raise ValueError("feature window overlaps baseline fitting")
                from dataclasses import replace
                spec = replace(spec, fit_end_date=results["baseline"]["fit_end_date"])
            results[stage] = getattr(adapter, stage)(spec, results)
    return results


def logic_version():
    root = Path(__file__).resolve().parents[3]
    sources = list(Path(__file__).parent.glob("*.py"))
    for pattern in ("core_cpp/*.cpp", "core_cpp/*.hpp", "core_cpp/native_bridge.py",
                    "modules/eta/baseline/baseline_core.py", "modules/eta/features/*.py",
                    "modules/eta/temporal_contract.py", "modules/ingestion/projection/*.py",
                    "modules/ingestion/sanitizer/trip_segmenter.py", "config/system_config.py",
                    "modules/lakehouse/hdfs/contract.py"):
        sources.extend(root.glob(pattern))
    return digest(encoded({p.relative_to(root).as_posix(): digest(p.read_bytes().replace(b"\r\n", b"\n"))
                           for p in sources}))


def stage_manifest(stage, spec, engines, **fields):
    fields.setdefault("schema_version", {"silver": "history-snapshot.v1", "baseline": "gold-baseline.v1",
                                         "features": "gold-causal-features.v1"}[stage])
    return dict(fields, stage=stage, spec=spec.manifest(), engines=sorted(set(engines)),
                logic_version=logic_version())


def validate_counts(counts, total, allowed):
    if sum(counts.values()) != total or set(counts).difference(allowed):
        raise ValueError("invalid published output counts")
