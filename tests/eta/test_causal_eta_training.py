import math
from copy import deepcopy

import pytest

from config.system_config import METERS_PER_DEG_LON_EQUATOR
from modules.eta.features.causal_eta import (
    CausalFeatures,
    FEATURES,
    Observation,
    RouteIncidentInterval,
)
from modules.eta.training.causal_eta_training import (
    MONOTONE_INCIDENT_FEATURES,
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
    assert len(FEATURES) == 40
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
        expected = -1 if feat in MONOTONE_SPEED_FEATURES else (1 if feat in MONOTONE_INCIDENT_FEATURES else 0)
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


def test_tomtom_incident_features_causal_and_legacy_compat():
    engine = CausalFeatures(StraightRoute())
    engine.observe(ping('ego', 1000, 100))
    engine.observe(ping('ego', 1040, 200))

    empty_feats, *_ = engine.features(1, 0, 'ego', 30, 1040)
    assert empty_feats['inc_ahead_total_delay_sec'] == 0.0
    assert empty_feats['inc_dist_to_nearest_m'] == 25000.0
    assert empty_feats['inc_ahead_jam_length_m'] == 0.0
    assert empty_feats['inc_info_age_sec'] is None

    engine.observe_incidents(1, 0, [
        RouteIncidentInterval(0.0, 200.0, 90.0, 900.0, 1800.0),      # chạm biên s_cur=200 (ov_l=0) -> bỏ
        RouteIncidentInterval(250.0, 350.0, 0.0, 900.0, 1800.0),    # delay=0 (roadworks) -> bỏ
        RouteIncidentInterval(250.0, 350.0, 90.0, 1100.0, 1800.0),  # tương lai (crawled > now) -> bỏ
        RouteIncidentInterval(250.0, 350.0, 90.0, 500.0, 1000.0),   # hết hạn (expires < now) -> bỏ
        RouteIncidentInterval(300.0, 700.0, 120.0, 900.0, 1800.0),  # active toàn phần: 120s, jam=400m, age=140s
        RouteIncidentInterval(1400.0, 1800.0, 200.0, 1000.0, 1800.0),  # active 1 phần tới target=1600: frac=0.5 -> 100s, jam=200m, age=40s
    ])
    feats, *_ = engine.features(1, 0, 'ego', 30, 1040)
    assert feats['inc_ahead_total_delay_sec'] == pytest.approx(220.0)
    assert feats['inc_dist_to_nearest_m'] == pytest.approx(100.0)
    assert feats['inc_ahead_jam_length_m'] == pytest.approx(600.0)
    assert feats['inc_info_age_sec'] == pytest.approx((120.0 * 140.0 + 100.0 * 40.0) / 220.0)

    class _LegacyDummyModel:
        def predict(self, frame, iteration_range=None):
            assert tuple(frame.columns) == FEATURES[:36]
            return frame['baseline_eta_p50_sec'].to_numpy() * 0.0 + 10.0

    legacy_runner = ResidualETA(
        _LegacyDummyModel(),
        {'route_id_idx': [0], 'direction_id': [0, 1], 'day_type': [0, 1, 2], 'hour_slot': list(range(5, 22))},
        features=FEATURES[:36],
    )
    assert legacy_runner.predict_one(feats) == pytest.approx(feats['baseline_eta_p50_sec'] + 10.0)


def test_silver_replay_trainer_source_validation_and_single_db_default(tmp_path):
    from config.system_config import DEFAULT_DB_PATH
    from modules.eta.training import silver_replay_trainer as srt
    from modules.eta.serving.data_access import DataAccess

    parser = srt.build_parser()
    parsed = parser.parse_args([
        '--silver', str(tmp_path / 'silver'),
        '--from-day', '2026-11-01',
        '--to-day', '2026-11-10',
        '--test-start', '2026-11-08',
    ])
    assert parsed.db_path == (srt.ROOT / DEFAULT_DB_PATH)

    args_neither = parser.parse_args([
        '--from-day', '2026-11-01', '--to-day', '2026-11-10', '--test-start', '2026-11-08',
    ])
    with pytest.raises(ValueError, match='exactly one of --silver or --hdfs-snapshot'):
        srt.run(args_neither)

    args_both = parser.parse_args([
        '--silver', str(tmp_path / 'silver'),
        '--hdfs-snapshot', 'a' * 64,
        '--from-day', '2026-11-01', '--to-day', '2026-11-10', '--test-start', '2026-11-08',
    ])
    with pytest.raises(ValueError, match='exactly one of --silver or --hdfs-snapshot'):
        srt.run(args_both)

    import inspect
    params = list(inspect.signature(DataAccess.__init__).parameters)
    assert 'baseline_db_path' not in params
    assert 'db_path' in params
    assert srt._split_epoch('2026-11-13') == srt._split_epoch('2026-11-13T00:00:00+07:00')


def test_features_all_targets_matches_single_target_and_preprojected_s_bus():
    engine_seq = CausalFeatures(StraightRoute())
    engine_batch = CausalFeatures(StraightRoute())
    engine_fast = CausalFeatures(StraightRoute())

    obs_seq = [
        ping('ego', 1000, 100),
        ping('lead', 1000, 300),
        ping('ego', 1040, 200),
        ping('lead', 1040, 380),
    ]
    for o in obs_seq:
        engine_seq.observe(o)
        engine_batch.observe(o)
    engine_seq.observe_snapshot(1, 0, 1040, ['ego', 'lead'])
    engine_batch.observe_snapshot(1, 0, 1040, ['ego', 'lead'])

    batch_out = engine_batch.features_all_targets(1, 0, 'ego', 1040)
    assert len(batch_out) == 2
    for order, fields_b, j_b, obs_b, _ in batch_out:
        fields_s, j_s, obs_s, _ = engine_seq.features(1, 0, 'ego', order, 1040)
        assert j_b == j_s
        assert obs_b == obs_s
        assert fields_b == fields_s

    # Fast pre-projected s_bus_m path (Option B)
    fast_obs = [
        Observation(1, 0, 'ego', 'busmap', 1000, 1000, 21.0, longitude(100), '', s_bus_m=100.0),
        Observation(1, 0, 'lead', 'busmap', 1000, 1000, 21.0, longitude(300), '', s_bus_m=300.0),
        Observation(1, 0, 'ego', 'busmap', 1040, 1040, 21.0, longitude(200), '', s_bus_m=200.0),
        Observation(1, 0, 'lead', 'busmap', 1040, 1040, 21.0, longitude(380), '', s_bus_m=380.0),
    ]
    for o in fast_obs:
        engine_fast.observe(o)
    engine_fast.observe_snapshot(1, 0, 1040, ['ego', 'lead'])
    fast_out = engine_fast.features_all_targets(1, 0, 'ego', 1040)
    assert len(fast_out) == 2
    for (order_f, fields_f, *_), (_, fields_b, *_) in zip(fast_out, batch_out):
        assert fields_f == fields_b
