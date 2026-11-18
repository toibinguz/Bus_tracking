"""
Module 3 - Step 3.2: Unified Gold Feature Store Extractor
"""

from module_3_bus_eta_prediction.step_3_2_feature_store_extractor.causal_eta import (
    CATEGORICAL,
    FEATURES,
    CausalFeatures,
    Observation,
)
from module_3_bus_eta_prediction.step_3_2_feature_store_extractor.feature_store_builder import (
    build_gold_feature_store,
    select_representative_target_indices,
)

__all__ = [
    "CATEGORICAL",
    "FEATURES",
    "CausalFeatures",
    "Observation",
    "build_gold_feature_store",
    "select_representative_target_indices",
]
