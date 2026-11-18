"""Build labeled ETA examples and fit a new residual model on temporal splits."""

import bisect
import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd
import xgboost as xgb

from config.system_config import BASELINE_MAX_HOUR_SLOT, BASELINE_MIN_HOUR_SLOT, TZ_HANOI
from module_3_bus_eta_prediction.step_3_2_feature_store_extractor.causal_eta import CATEGORICAL, FEATURES


BASE = 'baseline_eta_p50_sec'
MAX_LABEL_BRACKET_SEC = 90.0
MAX_LABEL_BRACKET_M = 600.0
MONOTONE_SPEED_FEATURES = frozenset({
    'ego_speed_avg_3min_kmh',
    'ego_speed_avg_5min_kmh',
    'lead_bus_speed_kmh',
})


def build_xgb_regressor(
    rounds: int,
    early_stopping_rounds: int = 30,
    max_depth: int = 4,
) -> xgb.XGBRegressor:
    """XGBRegressor với early stopping và ràng buộc đơn điệu âm cho nhóm tốc độ."""
    constraints = tuple(-1 if f in MONOTONE_SPEED_FEATURES else 0 for f in FEATURES)
    return xgb.XGBRegressor(
        objective='reg:absoluteerror',
        eval_metric='mae',
        n_estimators=rounds,
        early_stopping_rounds=early_stopping_rounds,
        max_depth=max_depth,
        learning_rate=0.05,
        tree_method='hist',
        enable_categorical=True,
        monotone_constraints=constraints,
        random_state=42,
        n_jobs=4,
    )


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


@dataclass(frozen=True)
class Crossing:
    epoch: float
    before_epoch: float
    after_epoch: float
    known_at: float
    before_s: float
    after_s: float
    before_source: str
    after_source: str


class TrainingReplay:
    def __init__(self, engine):
        self.engine = engine
        self._last = {}
        self._crossings = defaultdict(list)
        self._seen_crossings = set()
        self.examples = []
        self.counts = Counter()

    def snapshot(self, route, direction, available_at, observations, members, fleet_valid=True):
        if any(observation.source != 'busmap' for observation in observations):
            raise ValueError('ETA training replay accepts BusMap Silver observations only')
        for observation in sorted(observations, key=lambda event: event.epoch):
            if (observation.route_id, observation.direction) != (route, direction) or observation.epoch > available_at:
                raise ValueError('snapshot contains a future or unrelated observation')
            if observation.received != observation.epoch:
                observation = replace(observation, received=observation.epoch)
            sample = self.engine.observe(observation)
            self.counts['observations'] += 1
            if sample is None:
                continue
            self.counts['matched_observations'] += 1
            journey, s = sample
            identity = (route, observation.vehicle)
            previous = self._last.get(identity)
            self._last[identity] = (journey, observation, s)
            if previous is None or previous[0] != journey:
                continue
            _, old, old_s = previous
            dt, ds = observation.epoch - old.epoch, s - old_s
            if not (0 < dt <= MAX_LABEL_BRACKET_SEC and 0 < ds <= MAX_LABEL_BRACKET_M):
                continue
            for order, _, _, station_s in self.engine.corridor(route, direction):
                key = (journey, order)
                if key in self._seen_crossings or not old_s < station_s <= s:
                    continue
                self._seen_crossings.add(key)
                eta = old.epoch + dt * (station_s - old_s) / ds
                self._crossings[key].append(Crossing(eta, old.epoch, observation.epoch, observation.epoch,
                                                     old_s, s, old.source, observation.source))
        if members is not None:
            self.engine.observe_snapshot(route, direction, available_at, members, fleet_valid)

    def forecast(self, route, direction, vehicle, order, now):
        self.counts['forecast_attempts'] += 1
        result = self.engine.features(route, direction, vehicle, order, now)
        if result is None:
            self.counts['feature_rejected'] += 1
            return
        features, journey, observation, speeds = result
        self.examples.append(dict(route=route, vehicle=vehicle, journey=journey, target=order,
                                  as_of=now, position_epoch=observation.epoch, source=observation.source,
                                  features=features,
                                  speeds={key: asdict(value) if value else None for key, value in speeds.items()}))

    def labeled(self, validation_start, test_start):
        edges = (validation_start, test_start)
        splits = ('train', 'validation', 'test')
        for row in self.examples:
            crossing = next(iter(self._crossings.get((row['journey'], row['target']), ())), None)
            if crossing is None:
                self.counts['no_crossing'] += 1
                continue
            eta = crossing.epoch - row['as_of']
            if not 5 <= eta <= 7200:
                self.counts['invalid_eta'] += 1
                continue
            split = bisect.bisect_right(edges, row['as_of'])
            if bisect.bisect_right(edges, crossing.known_at) != split:
                self.counts['label_crosses_split'] += 1
                continue
            self.counts[f'labeled_{splits[split]}'] += 1
            yield {**row, 'split': splits[split], 'eta_seconds': eta, 'label': asdict(crossing)}


def feature_frame(rows, domains):
    frame = pd.DataFrame(rows, columns=FEATURES, dtype=float)
    for column in CATEGORICAL:
        frame[column] = pd.Categorical(frame[column], categories=domains[column])
    return frame


class ResidualETA:
    def __init__(self, model, domains, best_iteration=None):
        self.model = model
        self.domains = domains
        self.best_iteration = best_iteration

    def _predict_raw(self, frame):
        if self.best_iteration is not None:
            return self.model.predict(frame, iteration_range=(0, int(self.best_iteration) + 1))
        return self.model.predict(frame)

    def predict(self, rows, allow_unknown_routes=False):
        rows = list(rows)
        if not rows:
            return np.empty(0)
        if any(set(row) != set(FEATURES) or row[BASE] is None or not math.isfinite(row[BASE]) for row in rows):
            raise ValueError('features do not conform to ETA schema')
        frame = feature_frame(rows, self.domains)
        unknown_mask = frame['route_id_idx'].isna().to_numpy()
        if unknown_mask.any() and not allow_unknown_routes:
            raise ValueError('model has no training examples for at least one route')
        base_vals = frame[BASE].to_numpy()
        if unknown_mask.all():
            return np.maximum(5.0, base_vals)
        residual = self._predict_raw(frame)
        remaining = np.where(unknown_mask, base_vals, residual + base_vals)
        return np.maximum(5.0, remaining)

    def predict_one(self, row) -> float:
        return float(self.predict([row], allow_unknown_routes=True)[0])

    @classmethod
    def load(cls, root):
        root = Path(root)
        metadata = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
        if (metadata['schema'] != 'causal-eta.v1' or tuple(metadata['features']) != FEATURES
                or digest(root / 'model.json') != metadata['hashes']['model']):
            raise ValueError('ETA model contract or hash mismatch')
        model = xgb.XGBRegressor()
        model.load_model(root / 'model.json')
        if tuple(model.get_booster().feature_names) != FEATURES:
            raise ValueError('ETA model feature order is invalid')
        return cls(model, metadata['category_domains'], best_iteration=metadata.get('best_iteration'))


def metrics(actual, prediction, groups):
    error = np.asarray(prediction) - actual
    abs_error = np.abs(error)
    by_crossing = defaultdict(list)
    for group, value in zip(groups, abs_error, strict=True):
        by_crossing[group].append(value)
    return dict(rows=len(error), mae=float(abs_error.mean()), median_ae=float(np.median(abs_error)),
                p90_ae=float(np.quantile(abs_error, .9)), bias=float(error.mean()),
                crossings=len(by_crossing), crossing_balanced_mae=float(np.mean([np.mean(x) for x in by_crossing.values()])))


def fit_bundle(rows, output, provenance, rounds):
    if provenance.get('input_mode') != 'busmap_lakehouse_silver' or any(row['source'] != 'busmap' for row in rows):
        raise ValueError('ETA training requires a BusMap lakehouse Silver replay')
    splits = {name: [row for row in rows if row['split'] == name] for name in ('train', 'validation', 'test')}
    if any(not values for values in splits.values()):
        raise ValueError(f'each temporal split needs labels: { {key: len(value) for key, value in splits.items()} }')
    domains = {'route_id_idx': sorted({row['features']['route_id_idx'] for row in splits['train']}),
               'direction_id': [0, 1], 'day_type': [0, 1, 2],
               'hour_slot': list(range(BASELINE_MIN_HOUR_SLOT, BASELINE_MAX_HOUR_SLOT + 1))}
    train = splits['train']
    unsupported = {}
    for key, values in list(splits.items())[1:]:
        supported = [row for row in values if row['features']['route_id_idx'] in domains['route_id_idx']]
        unsupported[key] = len(values) - len(supported)
        splits[key] = supported
    validation, test = splits['validation'], splits['test']
    if not validation or not test:
        raise ValueError('no supported routes in validation or test')

    def input_data(examples):
        frame = feature_frame([row['features'] for row in examples], domains)
        residual = np.array([row['eta_seconds'] for row in examples]) - frame[BASE].to_numpy()
        counts = Counter((row['journey'], row['target']) for row in examples)
        weights = np.array([1 / counts[row['journey'], row['target']] for row in examples])
        return frame, residual, weights / np.mean(weights)

    x, y, weights = input_data(train)
    xv, yv, wv = input_data(validation)
    model = build_xgb_regressor(rounds)
    model.fit(x, y, sample_weight=weights, eval_set=[(x, y), (xv, yv)],
              sample_weight_eval_set=[weights, wv], verbose=50)
    history = model.evals_result()
    best_iteration = int(getattr(model, 'best_iteration', int(np.argmin(history['validation_1']['mae']))))
    model.get_booster().set_attr(best_iteration=str(best_iteration),
                                 best_score=str(history['validation_1']['mae'][best_iteration]))
    runner = ResidualETA(model, domains, best_iteration=best_iteration)
    test_predictions = runner.predict(row['features'] for row in test)
    actual = np.array([row['eta_seconds'] for row in test])
    baseline = np.array([row['features'][BASE] for row in test])
    groups = [(row['journey'], row['target']) for row in test]
    horizons = np.array([row['features']['n_stations_ahead'] for row in test])

    def compare(mask):
        keys = [group for group, include in zip(groups, mask, strict=True) if include]
        return {name: metrics(actual[mask], values[mask], keys)
                for name, values in [('baseline', baseline), ('model', test_predictions)]}

    report = dict(overall=compare(np.ones(len(test), dtype=bool)), unsupported_routes=unsupported,
                  by_horizon={}, by_source={}, by_speed_history={},
                  rows_by_split={name: len(data) for name, data in splits.items()})
    for name, start, end in [('1', 1, 1), ('2-5', 2, 5), ('6-15', 6, 15), ('16+', 16, math.inf)]:
        mask = (horizons >= start) & (horizons <= end)
        if mask.any():
            report['by_horizon'][name] = compare(mask)
    for source in sorted({row['source'] for row in test}):
        report['by_source'][source] = compare(np.array([row['source'] == source for row in test]))
    duration = np.array([row['speeds']['ego5']['seconds'] if row['speeds']['ego5'] else 0 for row in test])
    for name, mask in [('missing', duration == 0), ('short', (duration > 0) & (duration < 270)),
                       ('full', duration >= 270)]:
        if mask.any():
            report['by_speed_history'][name] = compare(mask)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(output)
    with TemporaryDirectory(dir=output.parent) as scratch:
        stage = Path(scratch) / 'bundle'
        stage.mkdir()
        model.save_model(stage / 'model.json')
        with (stage / 'examples.jsonl').open('w', encoding='utf-8') as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n')
        metadata = dict(schema='causal-eta.v1', features=FEATURES, category_domains=domains,
                        hashes={'model': digest(stage / 'model.json'), 'examples': digest(stage / 'examples.jsonl')},
                        best_iteration=model.best_iteration, trained_rounds=model.get_booster().num_boosted_rounds(),
                        training_history=history, provenance=provenance, evaluation=report)
        (stage / 'manifest.json').write_text(json.dumps(metadata, indent=2, allow_nan=False) + '\n', encoding='utf-8')
        np.testing.assert_allclose(ResidualETA.load(stage).predict(row['features'] for row in test), test_predictions)
        stage.rename(output)
    return metadata


def epoch(value):
    if isinstance(value, (int, float)):
        return float(value)
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        raise ValueError(f'timestamp lacks timezone: {value}')
    return stamp.timestamp()


def baseline_cutoff_epoch(day):
    return datetime.fromisoformat(day).replace(tzinfo=TZ_HANOI).timestamp() + 86400
