"""Dispatch the same pipeline stages to Spark; pin upstream build IDs between jobs."""
from argparse import Namespace
import json
from pathlib import Path

from config.system_config import CONFIG_FILE
from modules.lakehouse.pipeline.spec import PipelineSpec, resolve_routes, FEATURE_START, FORECAST_SECONDS
from config.system_config import BASELINE_FIT_END_DATE, TEST_SPLIT_END_DATE, TEST_SPLIT_START_DATE


def cli_spec(args, stages):
    catalog = json.loads((Path(__file__).resolve().parents[3] / CONFIG_FILE).read_text(encoding="utf-8"))
    routes = resolve_routes(args.routes, args.all_routes, catalog)
    return PipelineSpec(stages, routes, getattr(args, "fit_end_date", BASELINE_FIT_END_DATE),
                        getattr(args, "from_day", FEATURE_START), getattr(args, "to_day", TEST_SPLIT_END_DATE),
                        getattr(args, "test_start", TEST_SPLIT_START_DATE),
                        None if getattr(args, "no_valid", False) else getattr(args, "validation_start", None),
                        getattr(args, "forecast_every", FORECAST_SECONDS),
                        feature_routes=tuple(sorted(set(args.feature_routes))) if getattr(args, "feature_routes", None) else None)


class SparkAdapter:
    def __init__(self, args):
        self.args = args

    def pin(self, product, inputs):
        from .artifact_transport import PrivateWebHdfs
        snapshot = self.args.snapshot
        if len(snapshot) != 64 or any(c not in "0123456789abcdef" for c in snapshot):
            raise ValueError("invalid snapshot ID")
        root = "/bus-eta/v1"
        if product == "silver":
            path = f"{root}/_published/history_snapshots/{snapshot}.json"
        else:
            path = f"{root}/gold/agg_segment_travel_times/snapshot={snapshot}"
            build = getattr(self.args, "baseline_build_id", None)
            if build:
                if len(build) != 32 or any(c not in "0123456789abcdef" for c in build):
                    raise ValueError("invalid baseline build ID")
                path += "/builds/" + build
            path += "/manifest.json"
        manifest = json.loads(PrivateWebHdfs().read(path))
        if manifest["snapshot_id"] != snapshot:
            raise ValueError("pinned snapshot mismatch")
        return manifest

    def silver(self, spec, inputs):
        from .silver_spark_job import execute
        return execute(spec, self.args)

    def gold_args(self, spec, inputs):
        values = vars(self.args).copy()
        if "silver" in inputs:
            values["snapshot"] = inputs["silver"]["snapshot_id"]
        return Namespace(**dict(values, fit_end_date=spec.fit_end_date, from_day=spec.from_day,
                                to_day=spec.to_day, test_start=spec.test_start, forecast_every=spec.forecast_every,
                                no_valid=not spec.validation_start))

    def baseline(self, spec, inputs):
        from .gold_baseline_spark import execute
        return execute(spec, self.gold_args(spec, inputs), inputs["silver"])

    def features(self, spec, inputs):
        from .gold_features_spark import execute
        args = self.gold_args(spec, inputs)
        return execute(spec, args, inputs["silver"], inputs["baseline"])
