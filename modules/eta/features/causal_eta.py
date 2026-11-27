"""ETA features from the observation prefix, shared by replay and inference."""

from __future__ import annotations

import bisect
import math
import threading
from dataclasses import dataclass, field
from datetime import datetime

from config.system_config import (
    BASELINE_MAX_HOUR_SLOT,
    BASELINE_MIN_HOUR_SLOT,
    MAX_GPS_BACKWARD_JITTER_M,
    STALE_DELTA_T_MAX_SEC,
    TERMINAL_RESET_ZONE_M,
    TOMTOM_DEFAULT_TTL_SEC,
    TZ_HANOI,
)
from modules.ingestion.projection.route_matcher import (
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
    s_bus_m: float | None = None


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


@dataclass(frozen=True)
class _PreprojectedPoint:
    epoch: float
    s: float


class _PreprojectedMatcher:
    """Fast O(1) trajectory state tracker when Silver already provides Frenet s_bus_m."""

    __slots__ = ('shape_len', 'window', 'horizon', 'best_path', 'resets', 'reason', '_last_epoch', '_last_s')

    def __init__(self, shape_len: float, window: int = 128, horizon: float = 360.0):
        self.shape_len = shape_len
        self.window = window
        self.horizon = horizon
        self.best_path: list[_PreprojectedPoint] = []
        self.resets = 0
        self.reason: str | None = None
        self._last_epoch: float | None = None
        self._last_s: float | None = None

    def update_preprojected(self, epoch: float, s: float) -> _PreprojectedPoint:
        if self._last_epoch is not None and epoch <= self._last_epoch:
            self.reason = 'late_or_duplicate'
            return self.best_path[-1]

        pt = _PreprojectedPoint(epoch, float(s))
        if self._last_epoch is None:
            self.best_path = [pt]
            self.reason = 'initialized'
        else:
            dt = epoch - self._last_epoch
            prev_s = self._last_s
            terminal_wrap = (
                self.shape_len > 1000.0
                and prev_s >= self.shape_len - TERMINAL_RESET_ZONE_M
                and s <= TERMINAL_RESET_ZONE_M
                and s < prev_s - MAX_GPS_BACKWARD_JITTER_M
            )
            if dt > STALE_DELTA_T_MAX_SEC:
                self.resets += 1
                self.best_path = [pt]
                self.reason = 'initialized'
            elif terminal_wrap:
                self.resets += 1
                self.best_path = [pt]
                self.reason = 'terminal_reset'
            elif s < prev_s - MAX_GPS_BACKWARD_JITTER_M:
                self.resets += 1
                self.best_path = [pt]
                self.reason = 'reset'
            else:
                self.best_path.append(pt)
                if len(self.best_path) > self.window:
                    del self.best_path[:-self.window]
                while len(self.best_path) > 2 and epoch - self.best_path[0].epoch > self.horizon:
                    self.best_path.pop(0)
                self.reason = 'matched'
        self._last_epoch = epoch
        self._last_s = pt.s
        return pt


@dataclass
class VehicleState:
    matcher: object
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
        self._shape_lengths = {}
        self._corridors = {}
        self._corridor_meta = {}
        self._profiles = {}
        self._baseline_cells = {}
        self._baseline_prefix = {}
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

    def _get_corridor_meta(self, route_id, direction):
        key = (route_id, direction)
        meta = self._corridor_meta.get(key)
        if meta is None:
            corridor = self.corridor(route_id, direction)
            positions = [station[3] for station in corridor]
            order_to_idx = {station[0]: i for i, station in enumerate(corridor)}
            strictly_inc = len(positions) >= 2 and not any(right <= left for left, right in zip(positions, positions[1:]))
            meta = (corridor, positions, order_to_idx, strictly_inc)
            self._corridor_meta[key] = meta
        return meta

    def _get_shape_len(self, route_id, direction):
        key = (route_id, direction)
        length = self._shape_lengths.get(key)
        if length is None:
            points = self.data.get_shape_points(route_id, ('go', 're')[direction])
            if len(points) < 2:
                length = None
            else:
                length = max(float(pt[3]) for pt in points)
            self._shape_lengths[key] = length
        return length

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
        preprojected = o.s_bus_m is not None
        if preprojected:
            if not math.isfinite(o.s_bus_m):
                return None
            shape_len = self._get_shape_len(o.route_id, o.direction)
            if shape_len is None:
                return None
            shape = None
        else:
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
            matcher = _PreprojectedMatcher(shape_len, window=128, horizon=360) if preprojected else RouteHMM(shape, window=128, horizon=360)
            state = VehicleState(matcher, self._journey)
            self._states[identity] = state
        self._directions[identity] = (o.direction, o.epoch)
        # A BusMap ping arriving very close to an identical TimBus position offers
        # insufficient new evidence to establish two distinct GPS measurements.
        if (state.last and (state.last.source, state.last.context) != (o.source, o.context)
                and o.epoch - state.last.epoch <= 8
                and (state.last.lat, state.last.lng) == (o.lat, o.lng)):
            return None
        old_resets = state.matcher.resets
        if preprojected:
            match = state.matcher.update_preprojected(o.epoch, o.s_bus_m)
        else:
            match = state.matcher.update(o.epoch, o.lat, o.lng, int(o.epoch * 1000))
        if state.matcher.resets != old_resets:
            self._journey += 1
            state.journey = self._journey
            if state.matcher.reason != 'terminal_reset':
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
        cutoff = o.epoch - 390
        if len(state.observations) > 32:
            state.observations = {t: obs for t, obs in state.observations.items() if t >= cutoff}
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
        start_obs = state.observations.get(start.epoch)
        end_obs = state.observations.get(end.epoch)
        if start_obs is None or end_obs is None:
            return None
        return Speed(kmh, duration, start.s, end.s, (start_obs.source, end_obs.source))

    def features(self, route_id, direction, vehicle, target_order, now):
        with self._lock:
            return self._features_locked(route_id, direction, vehicle, target_order, now)

    def features_all_targets(self, route_id, direction, vehicle, now):
        """Tính một lượt cho toàn bộ trạm đích phía trước của 1 xe tại thời điểm `now` (O(1) prefix-sum)."""
        with self._lock:
            return self._features_all_targets_locked(route_id, direction, vehicle, now)

    def _features_locked(self, route_id, direction, vehicle, target_order, now):
        state = self._states.get((route_id, vehicle))
        if (not state or not state.last or state.last.direction != direction
                or state.last.received > now or not 0 <= now - state.last_epoch <= MAX_POSITION_AGE):
            return None
        corridor, positions, order_to_idx, strictly_inc = self._get_corridor_meta(route_id, direction)
        if not strictly_inc:
            return None
        s = state.match.s
        current = bisect.bisect_right(positions, s) - 1
        target = order_to_idx.get(target_order, -1)
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

    def _features_all_targets_locked(self, route_id, direction, vehicle, now):
        state = self._states.get((route_id, vehicle))
        if (not state or not state.last or state.last.direction != direction
                or state.last.received > now or not 0 <= now - state.last_epoch <= MAX_POSITION_AGE):
            return []
        corridor, positions, _, strictly_inc = self._get_corridor_meta(route_id, direction)
        if not strictly_inc:
            return []
        s = state.match.s
        current = bisect.bisect_right(positions, s) - 1
        route_idx = self.data.get_route_idx(route_id)
        if current < 0 or current >= len(corridor) - 1 or route_idx is None:
            return []
        prof_key = (route_id, direction)
        if prof_key not in self._profiles:
            self._profiles[prof_key] = self.data.get_route_profile(route_id, ('go', 're')[direction])
        profile_speed, spacing, length = self._profiles[prof_key]
        if length <= 0:
            return []

        stamp = datetime.fromtimestamp(now, TZ_HANOI)
        day = min(2, max(0, stamp.weekday() - 4))
        hour = min(BASELINE_MAX_HOUR_SLOT, max(BASELINE_MIN_HOUR_SLOT, stamp.hour))
        angle = math.tau * (stamp.hour + stamp.minute / 60) / 24
        sin_a = math.sin(angle)
        cos_a = math.cos(angle)
        weekday = stamp.weekday()

        prefix = self._baseline_prefix_data(route_id, direction, corridor, day, hour)
        cells = prefix[0]
        if cells[current] is None:
            return []

        speed3, speed5 = self.speed(state, 180), self.speed(state, 300)
        speed3_kmh = speed3.kmh if speed3 else None
        speed5_kmh = speed5.kmh if speed5 else None
        lead_dist, follow_dist, count, ahead_s_sorted, lead_state, follow_state, fleet_complete = (
            self._fleet_summary(route_id, direction, vehicle, now, state)
        )
        lead = self.speed(lead_state, 180) if lead_state else None
        follow = self.speed(follow_state, 180) if follow_state else None
        lead_kmh = lead.kmh if lead else None
        follow_kmh = follow.kmh if follow else None
        lead_ratio = self._lead_ratio(route_id, direction, corridor, positions, day, hour, lead)
        speeds = {'ego3': speed3, 'ego5': speed5, 'lead3': lead, 'follow3': follow}

        raw_ivs = self._incidents.get((route_id, direction), ())
        active_ivs = tuple(
            iv for iv in raw_ivs
            if iv.delay_seconds > 0.0 and iv.crawled_epoch <= now <= iv.expires_epoch
        )

        cur_order = corridor[current][0]
        s_ratio = s / length
        dist_next = positions[current + 1] - s
        first_weight = dist_next / (positions[current + 1] - positions[current])
        c0 = cells[current]
        _, pref_none, pref_t0, pref_t3, pref_p50, pref_p10, pref_p90, pref_mean, pref_var, seg_p90 = prefix

        results = []
        running_max_p90 = 0.0
        has_t3 = False
        for target in range(current + 1, len(corridor)):
            if pref_none[target] - pref_none[current] > 0:
                break
            cell_prev = cells[target - 1]
            if cell_prev[2] > running_max_p90:
                running_max_p90 = cell_prev[2]
            if cell_prev[5] == 3:
                has_t3 = True

            p50 = first_weight * c0[1] + (pref_p50[target] - pref_p50[current + 1])
            fraction = (pref_t0[target] - pref_t0[current]) / (target - current)
            if has_t3:
                baseline = (p50, None, None, None, None, None, None, None, fraction)
            else:
                p10 = first_weight * c0[0] + (pref_p10[target] - pref_p10[current + 1])
                p90 = first_weight * c0[2] + (pref_p90[target] - pref_p90[current + 1])
                mean = first_weight * c0[3] + (pref_mean[target] - pref_mean[current + 1])
                var = (first_weight * c0[4]) ** 2 + (pref_var[target] - pref_var[current + 1])
                baseline = (p50, mean, p10, p90, p90 - p10, math.sqrt(var), mean - p50, running_max_p90, fraction)

            s_target = positions[target]
            target_order = corridor[target][0]
            ahead = bisect.bisect_right(ahead_s_sorted, s_target) if fleet_complete else None
            if not active_ivs:
                inc_features = (0.0, INCIDENT_SENTINEL_DIST_M, 0.0, None)
            else:
                inc_features = self._incident_features_active(active_ivs, s, s_target, now)

            items = (route_idx, direction, cur_order, target_order, day, weekday, hour,
                     sin_a, cos_a, s, s_target, s_target - s,
                     target - current, s_ratio, s_target / length, dist_next,
                     speed3_kmh, speed5_kmh, *baseline,
                     profile_speed, spacing, lead_dist, follow_dist, count, ahead,
                     lead_kmh, follow_kmh, lead_ratio, *inc_features)
            fields = dict(zip(FEATURES, items, strict=True))
            results.append((target_order, fields, state.journey, state.last, speeds))
        return results

    def _route_baseline_cells(self, route, direction, corridor, day, hour):
        key = (route, direction, day, hour)
        if key not in self._baseline_cells:
            self._baseline_cells[key] = [
                self.data.get_baseline_cell(route, direction, corridor[i][0], corridor[i + 1][0], day, hour)
                for i in range(len(corridor) - 1)
            ]
        return self._baseline_cells[key]

    def _baseline_prefix_data(self, route, direction, corridor, day, hour):
        key = (route, direction, day, hour)
        cached = self._baseline_prefix.get(key)
        if cached is not None:
            return cached
        cells = self._route_baseline_cells(route, direction, corridor, day, hour)
        pref_none = [0]
        pref_t0 = [0]
        pref_t3 = [0]
        pref_p50 = [0.0]
        pref_p10 = [0.0]
        pref_p90 = [0.0]
        pref_mean = [0.0]
        pref_var = [0.0]
        seg_p90 = []
        n_none = n_t0 = n_t3 = 0
        s_p50 = s_p10 = s_p90 = s_mean = s_var = 0.0
        for cell in cells:
            if cell is None:
                n_none += 1
                seg_p90.append(0.0)
            else:
                if cell[5] == 0:
                    n_t0 += 1
                elif cell[5] == 3:
                    n_t3 += 1
                s_p10 += cell[0]
                s_p50 += cell[1]
                s_p90 += cell[2]
                s_mean += cell[3]
                s_var += cell[4] ** 2
                seg_p90.append(cell[2])
            pref_none.append(n_none)
            pref_t0.append(n_t0)
            pref_t3.append(n_t3)
            pref_p50.append(s_p50)
            pref_p10.append(s_p10)
            pref_p90.append(s_p90)
            pref_mean.append(s_mean)
            pref_var.append(s_var)
        cached = (cells, pref_none, pref_t0, pref_t3, pref_p50, pref_p10, pref_p90, pref_mean, pref_var, seg_p90)
        self._baseline_prefix[key] = cached
        return cached

    def _baseline(self, route, direction, corridor, positions, start, stop, s, day, hour):
        cells, pref_none, pref_t0, pref_t3, pref_p50, pref_p10, pref_p90, pref_mean, pref_var, seg_p90 = (
            self._baseline_prefix_data(route, direction, corridor, day, hour)
        )
        if pref_none[stop] - pref_none[start] > 0:
            return None
        first = (positions[start + 1] - s) / (positions[start + 1] - positions[start])
        c0 = cells[start]
        p50 = first * c0[1] + (pref_p50[stop] - pref_p50[start + 1])
        fraction = (pref_t0[stop] - pref_t0[start]) / (stop - start)
        if pref_t3[stop] - pref_t3[start] > 0:
            return p50, None, None, None, None, None, None, None, fraction
        p10 = first * c0[0] + (pref_p10[stop] - pref_p10[start + 1])
        p90 = first * c0[2] + (pref_p90[stop] - pref_p90[start + 1])
        mean = first * c0[3] + (pref_mean[stop] - pref_mean[start + 1])
        std = math.sqrt((first * c0[4]) ** 2 + (pref_var[stop] - pref_var[start + 1]))
        return p50, mean, p10, p90, p90 - p10, std, mean - p50, max(seg_p90[start:stop]), fraction

    def _fleet_summary(self, route, direction, vehicle, now, state):
        snapshot = self._snapshots.get((route, direction))
        if snapshot is None or not snapshot[2] or not 0 <= now - snapshot[0] <= MAX_POSITION_AGE:
            return None, None, None, (), None, None, False
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
        fleet_complete = len(candidates) == count
        ahead_s_sorted = sorted(state.match.s + d for d, _, _ in ahead) if fleet_complete else ()
        return (ahead[0][0] if ahead else None, behind[0][0] if behind else None, count,
                ahead_s_sorted, ahead[0][2] if ahead else None, behind[0][2] if behind else None, fleet_complete)

    def _fleet(self, route, direction, vehicle, now, state, target_s):
        lead_dist, follow_dist, count, ahead_s_sorted, lead_state, follow_state, fleet_complete = (
            self._fleet_summary(route, direction, vehicle, now, state)
        )
        if count is None:
            return None, None, None, None, None, None
        n_ahead = bisect.bisect_right(ahead_s_sorted, target_s) if fleet_complete else None
        return lead_dist, follow_dist, count, n_ahead, lead_state, follow_state

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

    @staticmethod
    def _incident_features_active(active_ivs, s_cur, s_target, now):
        if not active_ivs or s_target <= s_cur:
            return 0.0, INCIDENT_SENTINEL_DIST_M, 0.0, None
        total_delay = 0.0
        jam_length = 0.0
        nearest_dist = INCIDENT_SENTINEL_DIST_M
        weighted_age_sum = 0.0
        ttl = float(TOMTOM_DEFAULT_TTL_SEC)
        for iv in active_ivs:
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

    def _incident_features(self, route_id, direction, s_cur, s_target, now):
        """Tính 4 feature TomTom trên [s_cur, s_target] theo Cách A (t_cur - crawled_epoch)."""
        intervals = self._incidents.get((route_id, direction), ())
        if not intervals or s_target <= s_cur:
            return 0.0, INCIDENT_SENTINEL_DIST_M, 0.0, None
        active_ivs = [
            iv for iv in intervals
            if iv.delay_seconds > 0.0 and iv.crawled_epoch <= now <= iv.expires_epoch
        ]
        return self._incident_features_active(active_ivs, s_cur, s_target, now)
