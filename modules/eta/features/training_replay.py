"""Causal replay and crossing labels shared by training and batch execution."""
import bisect
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, replace

MAX_LABEL_BRACKET_SEC = 90.0
MAX_LABEL_BRACKET_M = 600.0


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

    def forecast_all(self, route, direction, vehicle, now):
        corridor = self.engine.corridor(route, direction)
        self.counts['forecast_attempts'] += len(corridor)
        results = self.engine.features_all_targets(route, direction, vehicle, now)
        self.counts['feature_rejected'] += len(corridor) - len(results)
        for order, features, journey, observation, speeds in results:
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
