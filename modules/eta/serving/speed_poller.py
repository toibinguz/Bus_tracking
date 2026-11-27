"""
Step 3.4 — Speed Layer Background Poller (chu kỳ 45s).
Module: modules/eta/serving/speed_poller.py

Nhiệm vụ:
  1. Quét BusMap `route_query` 48 tuyến baseline mỗi 45s để làm ấm `MacroSpeedTracker` & `RouteProjectionTracker`
     (triệt tiêu cold-start 3-5 phút khi người dùng mở trang).
  2. Trám TimBus dàn trải (2 workers, `anchors[:1]`) cho xe trễ >= 60s hoặc biến mất giữa tuyến,
     tự động bỏ qua các xe mà Serving Layer vừa focus (< 45s) trong `_tb_last_valid`.
  3. Phân loại 4 trạng thái (RECOVERED_LIVE / TERMINAL_OR_DEPOT_PARKED / ON_CORRIDOR_GAP / UPSTREAM_ERROR)
     kèm Circuit Breaker (90s) và đóng hoàn toàn ngoài giờ hoạt động (22:30 - 04:45).
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from config.system_config import (
    MAX_CORRIDOR_CROSS_TRACK_M,
    SPEED_POLLER_END_HHMM,
    SPEED_POLLER_START_HHMM,
    TZ_HANOI,
)
from modules.eta.serving.timbus_client import TimBusClient
from modules.ingestion.crawler.hf_lake_sync import (
    fetch_latest_incidents_from_hf,
)
from modules.eta.serving.dto import BusVehicleDTO
from modules.eta.serving.live_feed import (
    fetch_live_vehicles_for_route,
    parse_ping_epoch,
)

logger = logging.getLogger(__name__)

SPEED_POLL_INTERVAL_SEC = 45.0
STALE_TRIGGER_AGE_SEC = 60.0
PARKED_COOLDOWN_SEC = 180.0
GAP_COOLDOWN_SEC = 45.0
CIRCUIT_BREAKER_SEC = 90.0
CIRCUIT_ERROR_THRESHOLD = 3
TIMBUS_GAP_WORKERS = 2
TIMBUS_STAGGER_DELAY_SEC = 0.15
TERMINAL_NEAR_M = 300.0
OFF_HOURS_SLEEP_SEC = 30.0


def is_operating_hours(epoch: Optional[float] = None) -> bool:
    """True trong khung giờ vận hành (SSOT SPEED_POLLER_START_HHMM..SPEED_POLLER_END_HHMM giờ Hà Nội)."""
    ts = time.time() if epoch is None else epoch
    dt = datetime.fromtimestamp(ts, tz=TZ_HANOI)
    hhmm = dt.hour * 60 + dt.minute
    start_m = SPEED_POLLER_START_HHMM[0] * 60 + SPEED_POLLER_START_HHMM[1]
    end_m = SPEED_POLLER_END_HHMM[0] * 60 + SPEED_POLLER_END_HHMM[1]
    return start_m <= hhmm < end_m


class SpeedLayerPoller:
    """Background runner cho Speed Layer (45s BusMap route-query + 2-worker TimBus gap-filler)."""

    def __init__(
        self,
        service: Any,
        poll_interval_sec: float = SPEED_POLL_INTERVAL_SEC,
        stale_trigger_sec: float = STALE_TRIGGER_AGE_SEC,
        timbus_workers: int = TIMBUS_GAP_WORKERS,
        stagger_delay_sec: float = TIMBUS_STAGGER_DELAY_SEC,
        circuit_breaker_sec: float = CIRCUIT_BREAKER_SEC,
        route_fetcher: Optional[Callable[[int, int], Any]] = None,
        timbus_fetcher: Optional[Callable[..., Tuple[Dict[str, Any], int, int, Optional[str]]]] = None,
        incident_fetcher: Optional[Callable[[], Tuple[Optional[dict], Optional[str]]]] = None,
        incident_sync_interval_sec: float = 120.0,
        now_fn: Optional[Callable[[], float]] = None,
    ):
        self._service = service
        self.poll_interval_sec = float(poll_interval_sec)
        self.stale_trigger_sec = float(stale_trigger_sec)
        self.timbus_workers = max(1, int(timbus_workers))
        self.stagger_delay_sec = max(0.0, float(stagger_delay_sec))
        self.circuit_breaker_sec = float(circuit_breaker_sec)
        self._route_fetcher = route_fetcher or (lambda r_id, d: fetch_live_vehicles_for_route(route_id=r_id, direction=d))
        self._timbus_fetcher = timbus_fetcher or TimBusClient.query_central_vehicles_with_status
        self._incident_fetcher = incident_fetcher or fetch_latest_incidents_from_hf
        self.incident_sync_interval_sec = float(incident_sync_interval_sec)
        self._now_fn = now_fn or time.time

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._state_lock = threading.Lock()

        # Trạng thái cooldown & tracking giữa các vòng
        self._cooldowns: Dict[Tuple[int, int, str], float] = {}
        self._prev_active: Dict[Tuple[int, int], Dict[str, BusVehicleDTO]] = {}
        self._error_streak = 0
        self._circuit_open_until = 0.0

        # Telemetry giám sát cho /api/health
        self._status = "stopped"
        self._cycle_count = 0
        self._last_cycle_epoch: Optional[float] = None
        self._last_cycle_duration_sec: Optional[float] = None
        self._last_error: Optional[str] = None
        self._counts = {
            "busmap_ok": 0,
            "busmap_error": 0,
            "recovered_live": 0,
            "parked_skip": 0,
            "on_corridor_gap": 0,
            "upstream_error": 0,
        }
        self._gap_routes: Dict[int, int] = {}
        self._last_incident_sync_epoch: float = 0.0
        self._incident_fetched_at: Optional[str] = None
        self._incident_count: int = 0
        self._incident_error: Optional[str] = None

    def start(self) -> None:
        """Khởi động thread nền Speed Layer (an toàn khi gọi nhiều lần)."""
        with self._state_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._status = "starting"
            self._thread = threading.Thread(target=self._run_loop, name="SpeedLayerPoller", daemon=True)
            self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Dừng thread nền sạch sẽ."""
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        with self._state_lock:
            self._status = "stopped"
            self._thread = None

    def get_health_snapshot(self) -> Dict[str, Any]:
        """Trả snapshot giám sát cho `/api/health`."""
        now_epoch = self._now_fn()
        with self._state_lock:
            circuit_open = self._circuit_open_until > now_epoch
            return {
                "status": self._status,
                "operating_hours": is_operating_hours(now_epoch),
                "cycle_count": self._cycle_count,
                "last_cycle_epoch": self._last_cycle_epoch,
                "last_cycle_age_sec": (
                    round(max(0.0, now_epoch - self._last_cycle_epoch), 1)
                    if self._last_cycle_epoch is not None
                    else None
                ),
                "last_cycle_duration_sec": self._last_cycle_duration_sec,
                "circuit_state": "OPEN" if circuit_open else "CLOSED",
                "circuit_remaining_sec": round(max(0.0, self._circuit_open_until - now_epoch), 1),
                "error_streak": self._error_streak,
                "last_error": self._last_error,
                "counts": dict(self._counts),
                "gap_routes_top": dict(sorted(self._gap_routes.items(), key=lambda kv: -kv[1])[:5]),
                "incidents": {
                    "fetched_at": self._incident_fetched_at,
                    "count": self._incident_count,
                    "last_sync_epoch": self._last_incident_sync_epoch or None,
                    "error": self._incident_error,
                },
            }

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            now_epoch = self._now_fn()
            if not is_operating_hours(now_epoch):
                with self._state_lock:
                    self._status = "off_hours"
                    self._prev_active.clear()
                    expired = [k for k, exp in self._cooldowns.items() if exp <= now_epoch]
                    for k in expired:
                        self._cooldowns.pop(k, None)
                self._stop_event.wait(OFF_HOURS_SLEEP_SEC)
                continue

            t0 = time.monotonic()
            try:
                self.run_once(now_epoch=now_epoch)
            except Exception as exc:
                logger.exception("SpeedLayerPoller cycle failed: %s", exc)
                with self._state_lock:
                    self._status = "degraded"
                    self._last_error = f"{type(exc).__name__}: {exc}"
            elapsed = time.monotonic() - t0
            wait_sec = max(1.0, self.poll_interval_sec - elapsed)
            self._stop_event.wait(wait_sec)

    def run_once(self, now_epoch: Optional[float] = None) -> Dict[str, Any]:
        """Chạy 1 chu kỳ đồng bộ Speed Layer (48 tuyến BusMap + TimBus gap-fill)."""
        now_ts = self._now_fn() if now_epoch is None else float(now_epoch)
        t_start = time.monotonic()
        self._maybe_sync_incidents(now_ts)
        route_ids = self._service.get_poller_route_ids()

        candidates: List[Tuple[int, int, int, BusVehicleDTO, float, float]] = []
        busmap_ok = 0
        busmap_err = 0

        for route_id in route_ids:
            if self._stop_event.is_set():
                break
            for dir_int in (0, 1):
                resp = self._route_fetcher(route_id, dir_int)
                if getattr(resp, "upstream_status", "ok") == "upstream_error":
                    busmap_err += 1
                    with self._state_lock:
                        self._last_error = getattr(resp, "upstream_error", None) or "busmap_upstream_error"
                    continue
                busmap_ok += 1
                prepared = self._service.ingest_speed_layer_vehicles(
                    route_id, dir_int, list(getattr(resp, "vehicles", []) or []), now_ts
                )
                curr_by_plate: Dict[str, BusVehicleDTO] = {}
                for v in prepared:
                    p_norm = TimBusClient.normalize_plate(v.plate)
                    if p_norm:
                        curr_by_plate[p_norm] = v

                timbus_ok, anchors = self._service.get_timbus_anchors(route_id, dir_int)
                if timbus_ok and anchors:
                    primary_anchor = anchors[0]
                    recent_tb: Set[str] = self._service.get_recent_timbus_plates(
                        route_id, dir_int, now_ts, max_age_sec=self.poll_interval_sec
                    )
                    prev_by_plate = self._prev_active.get((route_id, dir_int), {})
                    for p_norm, v in curr_by_plate.items():
                        if p_norm in recent_tb:
                            continue
                        if self._is_in_cooldown(route_id, dir_int, p_norm, now_ts):
                            continue
                        ping_ts, _ = parse_ping_epoch(v.updated_at, now_ts)
                        age = max(0.0, now_ts - ping_ts)
                        if age >= self.stale_trigger_sec:
                            candidates.append((route_id, dir_int, primary_anchor, v, age, v.matched_projection[1] if v.matched_projection else 999.0))
                    # Xe biến mất giữa tuyến từ vòng trước
                    for p_norm, prev_v in prev_by_plate.items():
                        if p_norm in curr_by_plate or p_norm in recent_tb:
                            continue
                        if self._is_in_cooldown(route_id, dir_int, p_norm, now_ts):
                            continue
                        if self._is_near_terminal(route_id, dir_int, prev_v):
                            continue
                        candidates.append((route_id, dir_int, primary_anchor, prev_v, self.stale_trigger_sec + 30.0, prev_v.matched_projection[1] if prev_v.matched_projection else 0.0))

                self._prev_active[(route_id, dir_int)] = curr_by_plate

        # Sắp xếp xe trễ lâu nhất trước và trám TimBus dàn trải
        candidates.sort(key=lambda item: -item[4])
        tb_stats = self._run_timbus_gap_fill(candidates, now_ts)

        duration = round(time.monotonic() - t_start, 2)
        end_ts = self._now_fn() if now_epoch is None else float(now_epoch)
        sweeper = getattr(self._service, "sweep_stale_state", None)
        if callable(sweeper):
            sweeper(end_ts)
        with self._state_lock:
            expired = [k for k, exp in self._cooldowns.items() if exp <= end_ts]
            for k in expired:
                self._cooldowns.pop(k, None)
            self._cycle_count += 1
            self._last_cycle_epoch = end_ts
            self._last_cycle_duration_sec = duration
            self._counts["busmap_ok"] += busmap_ok
            self._counts["busmap_error"] += busmap_err
            circuit_open = self._circuit_open_until > now_ts
            self._status = "degraded" if (circuit_open or (busmap_err > 0 and busmap_ok == 0)) else "running"

        return {
            "busmap_ok": busmap_ok,
            "busmap_error": busmap_err,
            "candidates": len(candidates),
            **tb_stats,
            "duration_sec": duration,
        }

    def _maybe_sync_incidents(self, now_ts: float) -> None:
        """Đồng bộ TomTom live incidents từ Hugging Face (0 TomTom API call); retry ở vòng sau nếu lỗi."""
        with self._state_lock:
            if (now_ts - self._last_incident_sync_epoch) < self.incident_sync_interval_sec:
                return
        try:
            payload, err = self._incident_fetcher()
        except Exception as exc:
            with self._state_lock:
                self._incident_error = f"{type(exc).__name__}: {exc}"
            return
        if err is not None or not isinstance(payload, dict) or not isinstance(payload.get("incidents"), list):
            with self._state_lock:
                self._incident_error = err or "invalid_incident_payload"
            return
        ingester = getattr(self._service, "ingest_live_incidents", None)
        cnt = ingester(payload, now_ts) if callable(ingester) else len(payload.get("incidents") or [])
        with self._state_lock:
            self._last_incident_sync_epoch = now_ts
            self._incident_fetched_at = payload.get("fetched_at")
            self._incident_count = cnt
            self._incident_error = None

    def _is_in_cooldown(self, route_id: int, dir_int: int, plate: str, now_ts: float) -> bool:
        with self._state_lock:
            until = self._cooldowns.get((route_id, dir_int, plate), 0.0)
            return until > now_ts

    def _is_near_terminal(self, route_id: int, dir_int: int, v: BusVehicleDTO) -> bool:
        if v.matched_projection is None:
            return False
        s_cur = v.matched_projection[0]
        dir_str = "go" if dir_int == 0 else "re"
        endpoints = self._service.get_route_endpoint_s(route_id, dir_str)
        if endpoints is None:
            return False
        s_start, s_end = endpoints
        return abs(s_cur - s_start) <= TERMINAL_NEAR_M or abs(s_end - s_cur) <= TERMINAL_NEAR_M

    def _classify_and_record(
        self,
        route_id: int,
        dir_int: int,
        bm_v: BusVehicleDTO,
        ct_m: float,
        tb_rec: Optional[Any],
        err_cnt: int,
        last_err: Optional[str],
        now_ts: float,
    ) -> str:
        p_norm = TimBusClient.normalize_plate(bm_v.plate)
        key = (route_id, dir_int, p_norm)

        if tb_rec is not None:
            self._service.ingest_speed_layer_timbus_hit(route_id, dir_int, bm_v, tb_rec, now_ts)
            with self._state_lock:
                self._cooldowns.pop(key, None)
                self._error_streak = 0
                self._counts["recovered_live"] += 1
            return "RECOVERED_LIVE"

        if err_cnt > 0:
            with self._state_lock:
                self._error_streak += 1
                self._counts["upstream_error"] += 1
                self._last_error = last_err or "timbus_upstream_error"
                if self._error_streak >= CIRCUIT_ERROR_THRESHOLD:
                    self._circuit_open_until = now_ts + self.circuit_breaker_sec
            return "UPSTREAM_ERROR"

        near_term = self._is_near_terminal(route_id, dir_int, bm_v)
        if bm_v.speed_kmh <= 0.1 and (ct_m > MAX_CORRIDOR_CROSS_TRACK_M or near_term):
            with self._state_lock:
                self._cooldowns[key] = now_ts + PARKED_COOLDOWN_SEC
                self._error_streak = 0
                self._counts["parked_skip"] += 1
            return "TERMINAL_OR_DEPOT_PARKED"

        with self._state_lock:
            self._cooldowns[key] = now_ts + GAP_COOLDOWN_SEC
            self._error_streak = 0
            self._counts["on_corridor_gap"] += 1
            self._gap_routes[route_id] = self._gap_routes.get(route_id, 0) + 1
        return "ON_CORRIDOR_GAP"

    def _run_timbus_gap_fill(
        self,
        candidates: List[Tuple[int, int, int, BusVehicleDTO, float, float]],
        now_ts: float,
    ) -> Dict[str, int]:
        stats = {
            "RECOVERED_LIVE": 0,
            "TERMINAL_OR_DEPOT_PARKED": 0,
            "ON_CORRIDOR_GAP": 0,
            "UPSTREAM_ERROR": 0,
            "skipped_circuit": 0,
        }
        if not candidates:
            return stats

        with self._state_lock:
            if self._circuit_open_until > now_ts:
                stats["skipped_circuit"] = len(candidates)
                return stats

        def _query_one(item: Tuple[int, int, int, BusVehicleDTO, float, float]) -> str:
            route_id, dir_int, anchor_sid, bm_v, _, ct_m = item
            if self.stagger_delay_sec > 0:
                time.sleep(self.stagger_delay_sec)
            with self._state_lock:
                if self._circuit_open_until > now_ts:
                    return "SKIPPED_CIRCUIT"
            p_norm = TimBusClient.normalize_plate(bm_v.plate)
            tb_map, _, err_cnt, last_err = self._timbus_fetcher(
                station_ids=[anchor_sid],
                plates=[p_norm],
                direction=dir_int,
                timeout=3,
            )
            tb_rec = tb_map.get(p_norm)
            return self._classify_and_record(route_id, dir_int, bm_v, ct_m, tb_rec, err_cnt, last_err, now_ts)

        with ThreadPoolExecutor(max_workers=self.timbus_workers) as pool:
            futs = [pool.submit(_query_one, item) for item in candidates]
            for fut in as_completed(futs):
                label = fut.result()
                if label == "SKIPPED_CIRCUIT":
                    stats["skipped_circuit"] += 1
                elif label in stats:
                    stats[label] += 1
        return stats
