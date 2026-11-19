import math
from copy import deepcopy

import pytest

from config.system_config import METERS_PER_DEG_LON_EQUATOR
from module_3_bus_eta_prediction.step_3_2_feature_store_extractor.causal_eta import CausalFeatures, FEATURES, Observation
from module_3_bus_eta_prediction.step_3_3_machine_learning_models.causal_eta_training import (
    MONOTONE_SPEED_FEATURES,
    ResidualETA,
    TrainingReplay,
    build_xgb_regressor,
)


class StraightRoute:
    @staticmethod
    def get_shape_points(*args):
        return [(0, 21, longitude(0), 0), (1, 21, longitude(1600), 1600)]

    @staticmethod
    def get_corridor_stations(*args):
        return [(10, 1, 'A', 0), (20, 2, 'B', 500), (30, 3, 'C', 1600)]

    @staticmethod
    def get_route_idx(*args):
        return 0

    @staticmethod
    def get_route_profile(*args):
        return 18, 800, 1600

    @staticmethod
    def get_baseline_cell(*args):
        return 70, 100, 130, 105, 20, 0, 500


def longitude(s):
    return 105 + s / (METERS_PER_DEG_LON_EQUATOR * math.cos(math.radians(21)))


def ping(vehicle, stamp, s, source='busmap', signature='', received=None, context=''):
    return Observation(1, 0, vehicle, source, stamp, stamp if received is None else received,
                       21, longitude(s), signature, context)


def test_fleet_uses_unlabeled_pings_and_future_only_adds_label():
    replay = TrainingReplay(CausalFeatures(StraightRoute()))
    replay.snapshot(1, 0, 1000, [ping('ego', 1000, 100), ping('lead', 1000, 300)], ['ego', 'lead'])
    replay.snapshot(1, 0, 1040, [ping('ego', 1040, 200), ping('lead', 1040, 380)], ['ego', 'lead'])
    replay.forecast(1, 0, 'ego', 20, 1040)
    original = deepcopy(replay.examples[0])
    assert tuple(original['features']) == FEATURES
    assert len(FEATURES) == 36
    assert original['features']['lead_bus_dist_ahead_m'] == 180
    assert original['features']['lead_bus_speed_kmh'] == pytest.approx(7.2)
    assert original['features']['follow_bus_dist_behind_m'] is None
    assert original['features']['n_active_buses_on_route'] == 2
    assert original['speeds']['ego3']['seconds'] == 40
    assert original['speeds']['ego5']['seconds'] == 40
    assert list(replay.labeled(1100, 1200)) == []
    replay.snapshot(1, 0, 1080, [ping('ego', 1080, 600, received=1180)], ['ego'])
    row, = replay.labeled(1100, 1200)
    assert row['eta_seconds'] == pytest.approx(30)
    assert row['label']['before_epoch'] == 1040
    assert row['label']['after_epoch'] == 1080
    assert row['label']['known_at'] == 1080
    assert row['features'] == original['features']
    assert replay.examples[0] == original
    assert list(replay.labeled(1070, 1200)) == []


def test_timbus_compares_full_payload_and_late_busmap_cannot_move_state_back():
    engine = CausalFeatures(StraightRoute())
    assert engine.observe(ping('ego', 1000, 100, 'timbus', '{"speed":17}'))
    assert engine.observe(ping('ego', 1005, 100, 'timbus', '{"speed":17}')) is None
    assert engine.observe(ping('ego', 1010, 100, 'timbus', '{"speed":18}'))
    assert engine.observe(ping('ego', 1011, 100, 'timbus', '{"distance":500}', context='other')) is None
    assert engine.observe(ping('ego', 1004, 60, received=1012)) is None
    features, _, observation, _ = engine.features(1, 0, 'ego', 20, 1012)
    assert observation.epoch == 1010
    assert features['s_bus_m'] == 100
    assert features['n_active_buses_on_route'] is None


def test_training_rejects_timbus_before_changing_state():
    replay = TrainingReplay(CausalFeatures(StraightRoute()))
    with pytest.raises(ValueError, match='BusMap Silver'):
        replay.snapshot(1, 0, 1000, [ping('ego', 1000, 100, 'timbus')], ['ego'])
    assert replay.counts == {}


def test_complete_windows_and_tier_three_uncertainty():
    class MissingHistory(StraightRoute):
        @staticmethod
        def get_baseline_cell(*args):
            return 70, 100, 130, 100, 20, 3, 500

    engine = CausalFeatures(MissingHistory())
    for offset in range(0, 301, 30):
        assert engine.observe(ping('ego', 1000 + offset, 10 + offset))
    engine.observe_snapshot(1, 0, 1300, ['ego'])
    row, _, _, windows = engine.features(1, 0, 'ego', 20, 1300)
    assert windows['ego3'].seconds == 180
    assert windows['ego5'].seconds == 300
    assert row['ego_speed_avg_3min_kmh'] == pytest.approx(3.6)
    assert row['ego_speed_avg_5min_kmh'] == pytest.approx(3.6)
    assert row['n_buses_in_corridor_ahead'] == 0
    assert row['baseline_eta_p50_sec'] > 0
    assert row['baseline_tier0_frac'] == 0
    assert row['baseline_eta_p90_sec'] is None


def test_xgb_monotone_and_unknown_route_fallback():
    reg = build_xgb_regressor(rounds=50, early_stopping_rounds=10)
    assert reg.early_stopping_rounds == 10
    for idx, feat in enumerate(FEATURES):
        expected = -1 if feat in MONOTONE_SPEED_FEATURES else 0
        assert reg.monotone_constraints[idx] == expected

    class _DummyModel:
        def predict(self, frame, iteration_range=None):
            return frame['baseline_eta_p50_sec'].to_numpy() * 0.0 + 15.0

    runner = ResidualETA(
        _DummyModel(),
        {'route_id_idx': [0], 'direction_id': [0, 1], 'day_type': [0, 1, 2], 'hour_slot': list(range(5, 22))},
        best_iteration=5,
    )
    row_unknown = {f: 0.0 for f in FEATURES}
    row_unknown.update({'route_id_idx': 999, 'direction_id': 0, 'day_type': 0, 'hour_slot': 8, 'baseline_eta_p50_sec': 120.0})

    with pytest.raises(ValueError, match='no training examples'):
        runner.predict([row_unknown], allow_unknown_routes=False)

    assert runner.predict_one(row_unknown) == pytest.approx(120.0)
    row_known = dict(row_unknown, route_id_idx=0)
    assert runner.predict_one(row_known) == pytest.approx(135.0)
