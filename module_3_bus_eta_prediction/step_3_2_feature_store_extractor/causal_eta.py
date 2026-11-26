"""ETA features from the observation prefix, shared by replay and inference."""

import bisect
import math
import threading
from dataclasses import dataclass, field
from datetime import datetime

from config.system_config import (
    BASELINE_MAX_HOUR_SLOT,
    BASELINE_MIN_HOUR_SLOT,
    TOMTOM_DEFAULT_TTL_SEC,
    TZ_HANOI,
)
from module_1_data_ingestion_and_preprocessing.step_1_4_frenet_spatial_projection.route_matcher import (
    RouteHMM,
    ShapeProjectionModel,
)


FEATURES = (
    'route_id_idx', 'direction_id', 'current_station_order', 'target_station_order',
    'day_type', 'day_of_week', 'hour_slot', 'sin_time', 'cos_time',
    's_bus_m', 's_target_m', 'remaining_distance_m', 'n_stations_ahead',
    'progress_ratio', 'target_progress_ratio', 'dist_to_next_station_m',
    'ego_speed_avg_3min_kmh', 'ego_speed_avg_5min_kmh',
    'baseline_eta_p50_sec', 'baseline_eta_mean_sec', 'baseline_eta_p10_sec',
    'baseline_eta_p90_sec', 'baseline_eta_p90_minus_p10_sec', 'baseline_eta_rss_std_sec',
    'baseline_eta_mean_minus_p50_sec', 'baseline_max_seg_p90_sec', 'baseline_tier0_frac',
    'route_base_speed_kmh', 'route_station_spacing_m',
    'lead_bus_dist_ahead_m', 'follow_bus_dist_behind_m', 'n_active_buses_on_route',
    'n_buses_in_corridor_ahead', 'lead_bus_speed_kmh', 'follow_bus_speed_kmh',
    'lead_bus_speed_ratio',
    'inc_ahead_total_delay_sec', 'inc_dist_to_nearest_m',
    'inc_ahead_jam_length_m', 'inc_info_age_sec',
)
CATEGORICAL = ('route_id_idx', 'direction_id', 'day_type', 'hour_slot')
INCIDENT_SENTINEL_DIST_M = 25000.0
MAX_POSITION_AGE = 90.0
MAX_FLEET_SKEW = 45.0
MAX_GAP = 120.0
MIN_SPEED_WINDOW = 30.0
WINDOW_TOLERANCE = 30.0
STATIONARY_TOLERANCE_M = 15.0


@dataclass(frozen=True)
class Observation:
    route_id: int
    direction: int
    vehicle: str
    source: str
    epoch: float
    received: float
    lat: float
    lng: float
    signature: str
    context: str = ''


@dataclass(frozen=True)
class Speed:
    kmh: float
    seconds: float
    start_s: float
    end_s: float
    sources: tuple[str, str]


@dataclass(frozen=True)
class RouteIncidentInterval:
    s_min_m: float
    s_max_m: float
    delay_seconds: float
    crawled_epoch: float
    expires_epoch: float


@dataclass
class VehicleState:
    matcher: RouteHMM
    journey: int
    last_epoch: float = -math.inf
    started: float | None = None
    observations: dict = field(default_factory=dict)
    last: Observation | None = None
    match: object = None


class CausalFeatures:
    def __init__(self, data):
        self.data = data
        self._lock = threading.RLock()
        self._shapes = {}
        self._corridors = {}
        self._profiles = {}
        self._baseline_cells = {}
        self._states = {}
        self._directions = {}
        self._fingerprints = {}
        self._snapshots = {}
        self._incidents = {}
        self._journey = 0

    def observe_incidents(self, route_id, direction, intervals):
        """Ghi nhận danh sách đoạn sự cố TomTom active cho (route_id, direction)."""
        with self._lock:
            self._incidents[(route_id, direction)] = tuple(intervals)

    def corridor(self, route_id, direction):
        with self._lock:
            key = (route_id, direction)
            if key not in self._corridors:
                self._corridors[key] = self.data.get_corridor_stations(route_id, ('go', 're')[direction])
            return self._corridors[key]

    def observe(self, observation):
        with self._lock:
            return self._observe_locked(observation)

    def _observe_locked(self, observation):
        o = observation
        if (
            o.source not in ('busmap', 'timbus') or o.direction not in (0, 1) or not o.vehicle
            or not all(map(math.isfinite, (o.epoch, o.received, o.lat, o.lng)))
            or not -90 <= o.lat <= 90 or not -180 <= o.lng <= 180
            or (o.lat == 0 and o.lng == 0) or o.epoch > o.received
        ):
            return None
        identity = (o.route_id, o.vehicle)
        fingerprint_key = (*identity, o.direction, o.source, o.context)
        previous = self._fingerprints.get(fingerprint_key)
        if previous is not None:
            if o.source == 'busmap' and o.epoch <= previous.epoch:
                return None
            if o.source == 'timbus' and (o.epoch <= previous.epoch or o.signature == previous.signature):
                return None
        self._fingerprints[fingerprint_key] = o
        if o.received - o.epoch > MAX_POSITION_AGE:
            return None
        old = self._directions.get(identity)
        if old and o.epoch <= old[1]:
            return None
        key = (o.route_id, o.direction)
        if key not in self._shapes:
            points = self.data.get_shape_points(o.route_id, ('go', 're')[o.direction])
            self._shapes[key] = ShapeProjectionModel.build(points) if len(points) >= 2 else None
        shape = self._shapes[key]
        if shape is None:
            return None
        state = self._states.get(identity)
        if state is not None and old[0] != o.direction:
            state = None
        if state is None:
            self._journey += 1
            state = VehicleState(RouteHMM(shape, window=128, horizon=360), self._journey)
            self._states[identity] = state
        self._directions[identity] = (o.direction, o.epoch)
        # A BusMap ping arriving very close to an identical TimBus position offers
        # insufficient new evidence to establish two distinct GPS measurements.
        if (state.last and (state.last.source, state.last.context) != (o.source, o.context)
                and o.epoch - state.last.epoch <= 8
                and (state.last.lat, state.last.lng) == (o.lat, o.lng)):
            return None
        old_resets = state.matcher.resets
        match = state.matcher.update(o.epoch, o.lat, o.lng, int(o.epoch * 1000))
        if state.matcher.resets != old_resets:
            self._journey += 1
            state.journey = self._journey
            state.observations.clear()
            state.last = state.match = None
            state.started = None
        if match is None:
            return None
        state.last = o
        state.match = match
        state.last_epoch = o.epoch
        if state.started is None:
            state.started = o.epoch
        state.observations[o.epoch] = o
        state.observations = {t: obs for t, obs in state.observations.items() if t >= o.epoch - 390}
        return state.journey, match.s

    def observe_snapshot(self, route_id, direction, received, vehicles, valid=True):
        with self._lock:
            self._snapshots[(route_id, direction)] = (received, frozenset(vehicles), valid)

    @staticmethod
    def speed(state, seconds):
        points = state.matcher.best_path
        if len(points) < 2:
            return None
        end = points[-1]
        start = min(points[:-1], key=lambda point: abs(end.epoch - point.epoch - seconds))
        if end.epoch - state.started < seconds:
            start = points[0]
        elif abs(end.epoch - start.epoch - seconds) > WINDOW_TOLERANCE:
            return None
        duration = end.epoch - start.epoch
        if duration < MIN_SPEED_WINDOW:
            return None
        window = [point for point in points if point.epoch >= start.epoch]
        if any(right.epoch - left.epoch > MAX_GAP for left, right in zip(window, window[1:])):
            return None
        distance = end.s - start.s
        if abs(distance) <= STATIONARY_TOLERANCE_M and max(p.s for p in window) - min(p.s for p in window) <= STATIONARY_TOLERANCE_M:
            distance = 0.0
        if distance < 0:
            return None
        kmh = 3.6 * distance / duration
        if kmh > 80:
            return None
        return Speed(kmh, duration, start.s, end.s,
                     (state.observations[start.epoch].source, state.observations[end.epoch].source))

    def features(self, route_id, direction, vehicle, target_order, now):
        with self._lock:
            return self._features_locked(route_id, direction, vehicle, target_order, now)

    def _features_locked(self, route_id, direction, vehicle, target_order, now):
        state = self._states.get((route_id, vehicle))
        if (not state or not state.last or state.last.direction != direction
                or state.last.received > now or not 0 <= now - state.last_epoch <= MAX_POSITION_AGE):
            return None
        corridor = self.corridor(route_id, direction)
        positions = [station[3] for station in corridor]
        if len(positions) < 2 or any(right <= left for left, right in zip(positions, positions[1:])):
            return None
        s = state.match.s
        current = bisect.bisect_right(positions, s) - 1
        target = next((i for i, station in enumerate(corridor) if station[0] == target_order), -1)
        route_idx = self.data.get_route_idx(route_id)
        if current < 0 or target <= current or route_idx is None:
            return None
        stamp = datetime.fromtimestamp(now, TZ_HANOI)
        day = min(2, max(0, stamp.weekday() - 4))
        hour = min(BASELINE_MAX_HOUR_SLOT, max(BASELINE_MIN_HOUR_SLOT, stamp.hour))
        angle = math.tau * (stamp.hour + stamp.minute / 60) / 24
        prof_key = (route_id, direction)
        if prof_key not in self._profiles:
            self._profiles[prof_key] = self.data.get_route_profile(route_id, ('go', 're')[direction])
        profile_speed, spacing, length = self._profiles[prof_key]
        if length <= 0:
            return None
        baseline = self._baseline(route_id, direction, corridor, positions, current, target, s, day, hour)
        if baseline is None:
            return None
        speed3, speed5 = self.speed(state, 180), self.speed(state, 300)
        fleet = self._fleet(route_id, direction, vehicle, now, state, positions[target])
        lead_dist, follow_dist, count, ahead, lead_state, follow_state = fleet
        lead = self.speed(lead_state, 180) if lead_state else None
        follow = self.speed(follow_state, 180) if follow_state else None
        lead_ratio = self._lead_ratio(route_id, direction, corridor, positions, day, hour, lead)
        inc_features = self._incident_features(route_id, direction, s, positions[target], now)
        items = (route_idx, direction, corridor[current][0], target_order, day, stamp.weekday(), hour,
                 math.sin(angle), math.cos(angle), s, positions[target], positions[target] - s,
                 target - current, s / length, positions[target] / length, positions[current + 1] - s,
                 speed3.kmh if speed3 else None, speed5.kmh if speed5 else None, *baseline,
                 profile_speed, spacing, lead_dist, follow_dist, count, ahead,
                 lead.kmh if lead else None, follow.kmh if follow else None, lead_ratio, *inc_features)
        fields = dict(zip(FEATURES, items, strict=True))
        speeds = {'ego3': speed3, 'ego5': speed5, 'lead3': lead, 'follow3': follow}
        return fields, state.journey, state.last, speeds

    def _route_baseline_cells(self, route, direction, corridor, day, hour):
        key = (route, direction, day, hour)
        if key not in self._baseline_cells:
            self._baseline_cells[key] = [
                self.data.get_baseline_cell(route, direction, corridor[i][0], corridor[i + 1][0], day, hour)
                for i in range(len(corridor) - 1)
            ]
        return self._baseline_cells[key]

    def _baseline(self, route, direction, corridor, positions, start, stop, s, day, hour):
        cells = self._route_baseline_cells(route, direction, corridor, day, hour)[start:stop]
        if any(cell is None for cell in cells):
            return None
        first = (positions[start + 1] - s) / (positions[start + 1] - positions[start])
        weights = [first] + [1.0] * (len(cells) - 1)
        p50 = sum(w * cell[1] for w, cell in zip(weights, cells))
        fraction = sum(cell[5] == 0 for cell in cells) / len(cells)
        if any(cell[5] == 3 for cell in cells):
            return p50, None, None, None, None, None, None, None, fraction
        p10 = sum(w * cell[0] for w, cell in zip(weights, cells))
        p90 = sum(w * cell[2] for w, cell in zip(weights, cells))
        mean = sum(w * cell[3] for w, cell in zip(weights, cells))
        std = math.sqrt(sum((w * cell[4]) ** 2 for w, cell in zip(weights, cells)))
        return p50, mean, p10, p90, p90 - p10, std, mean - p50, max(cell[2] for cell in cells), fraction

    def _fleet(self, route, direction, vehicle, now, state, target_s):
        snapshot = self._snapshots.get((route, direction))
        if snapshot is None or not snapshot[2] or not 0 <= now - snapshot[0] <= MAX_POSITION_AGE:
            return None, None, None, None, None, None
        candidates = []
        count = 0
        for other in sorted(snapshot[1]):
            other_state = self._states.get((route, other))
            if (other_state and other_state.last and other_state.last.direction == direction
                    and other_state.last.received <= now
                    and 0 <= now - other_state.last_epoch <= MAX_POSITION_AGE):
                count += 1
                if abs(state.last_epoch - other_state.last_epoch) <= MAX_FLEET_SKEW:
                    candidates.append((other, other_state.match.s - state.match.s, other_state))
        ahead = sorted((d, other, v) for other, d, v in candidates if other != vehicle and d > 20)
        behind = sorted((-d, other, v) for other, d, v in candidates if other != vehicle and d < -20)
        n_ahead = sum(state.match.s + d <= target_s for d, _, _ in ahead) if len(candidates) == count else None
        return (ahead[0][0] if ahead else None, behind[0][0] if behind else None, count,
                n_ahead, ahead[0][2] if ahead else None, behind[0][2] if behind else None)

    def _lead_ratio(self, route, direction, corridor, positions, day, hour, speed):
        if speed is None or speed.end_s <= speed.start_s:
            return None
        if speed.start_s < positions[0] or speed.end_s > positions[-1]:
            return None
        expected = 0.0
        route_cells = self._route_baseline_cells(route, direction, corridor, day, hour)
        for i, (left, right) in enumerate(zip(positions, positions[1:])):
            overlap = min(right, speed.end_s) - max(left, speed.start_s)
            if overlap <= 0:
                continue
            cell = route_cells[i]
            if cell is None or cell[5] == 3:
                return None
            expected += cell[1] * overlap / (right - left)
        return expected / speed.seconds

    def _incident_features(self, route_id, direction, s_cur, s_target, now):
        """Tính 4 feature TomTom trên [s_cur, s_target] theo Cách A (t_cur - crawled_epoch)."""
        intervals = self._incidents.get((route_id, direction), ())
        if not intervals or s_target <= s_cur:
            return 0.0, INCIDENT_SENTINEL_DIST_M, 0.0, None
        total_delay = 0.0
        jam_length = 0.0
        nearest_dist = INCIDENT_SENTINEL_DIST_M
        weighted_age_sum = 0.0
        ttl = float(TOMTOM_DEFAULT_TTL_SEC)
        for iv in intervals:
            if iv.delay_seconds <= 0.0:
                continue
            if not (iv.crawled_epoch <= now <= iv.expires_epoch):
                continue
            ov_l = min(s_target, iv.s_max_m) - max(s_cur, iv.s_min_m)
            if ov_l <= 0.0:
                continue
            span_l = max(1e-6, iv.s_max_m - iv.s_min_m)
            frac = min(1.0, ov_l / span_l)
            delay_part = iv.delay_seconds * frac
            total_delay += delay_part
            jam_length += ov_l
            d_near = max(0.0, iv.s_min_m - s_cur)
            if d_near < nearest_dist:
                nearest_dist = d_near
            age_sec = min(ttl, max(0.0, now - iv.crawled_epoch))
            weighted_age_sum += delay_part * age_sec
        if total_delay <= 0.0:
            return 0.0, INCIDENT_SENTINEL_DIST_M, 0.0, None
        return total_delay, nearest_dist, jam_length, weighted_age_sum / total_delay
