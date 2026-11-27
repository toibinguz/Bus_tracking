"""Unit & integration tests for the locked-anchor TimBus hybrid serving flow."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pytest

from config.system_config import TZ_HANOI
from modules.eta.serving.timbus_client import BusRecord, TimBusClient
from modules.eta.serving import serving_service as svc_mod
from modules.eta.serving.dto import (
    BusVehicleDTO,
    RouteLiveResponse,
)
from modules.ingestion.projection.route_matcher import ShapeProjectionModel
from modules.eta.serving.serving_service import (
    BusMapServingService,
)


def _point_at_s(
    points: List[Tuple[int, float, float, float]], s_want: float
) -> Tuple[float, float, float]:
    """Nội suy tuyến tính tọa độ trên tim tuyến tại đúng lý trình s_want."""
    if not points:
        raise ValueError("Empty shape points")
    if s_want <= float(points[0][3]):
        return float(points[0][1]), float(points[0][2]), float(points[0][3])
    for p0, p1 in zip(points, points[1:]):
        s0, s1 = float(p0[3]), float(p1[3])
        if s0 <= s_want <= s1:
            if s1 <= s0:
                return float(p0[1]), float(p0[2]), s0
            ratio = (s_want - s0) / (s1 - s0)
            lat = float(p0[1]) + ratio * (float(p1[1]) - float(p0[1]))
            lon = float(p0[2]) + ratio * (float(p1[2]) - float(p0[2]))
            return lat, lon, float(s_want)
    last = points[-1]
    return float(last[1]), float(last[2]), float(last[3])


def _offset_point(lat: float, lon: float, east_m: float, north_m: float) -> Tuple[float, float]:
    """Dịch điểm theo mét (độ chính xác vùng Hà Nội) để tạo điểm lệch hành lang ct mong muốn."""
    d_lat = north_m / 111320.0
    d_lon = east_m / (111320.0 * math.cos(math.radians(lat)))
    return lat + d_lat, lon + d_lon


def _make_bus_record(plate: str, route: str, lat: float, lon: float, speed_kmh: int = 24) -> BusRecord:
    return BusRecord(
        plate=plate,
        route=route,
        next_station_id=100,
        distance_m=30,
        next_station_name="Giáp Bát",
        speed_kmh=speed_kmh,
        latitude=lat,
        longitude=lon,
        status=0,
        direction="Đi",
    )


def _make_bm_vehicle(
    vid: int, plate: str, route_id: int, lat: float, lon: float, now_iso: str, speed_kmh: float = 20.0
) -> BusVehicleDTO:
    return BusVehicleDTO(
        id=vid,
        plate=plate,
        route_id=route_id,
        direction=0,
        lat=lat,
        lng=lon,
        deg=90.0,
        speed_kmh=speed_kmh,
        updated_at=now_iso,
    )


@pytest.fixture()
def service() -> BusMapServingService:
    return BusMapServingService()


def test_locked_routes_96_enabled_vs_80_ignored(service: BusMapServingService, monkeypatch: pytest.MonkeyPatch) -> None:
    """96 tuyến sạch (192 cặp) bật TimBus 5s; 80 tuyến bỏ qua giữ BusMap 15s và không gọi TimBus."""
    assert len(service._da._timbus_anchors) == 352
    enabled_pairs = [k for k, (ok, sids) in service._da._timbus_anchors.items() if ok and len(sids) >= 1]
    assert len(enabled_pairs) == 192

    # Tuyến 110 bị thiếu 1 chiều nên toàn tuyến phải bị khóa BusMap-only
    r110_id = service.resolve_route_id("110")
    assert r110_id is not None
    assert service._da.get_timbus_anchors(r110_id, 0) == (False, [])
    assert service._da.get_timbus_anchors(r110_id, 1) == (False, [])

    # Tuyến 40CT, 66, 87, 02TC đã cứu đủ 2 chiều đều phải bật
    for rc in ("32", "40", "40CT", "66", "87", "02TC"):
        rid = service.resolve_route_id(rc)
        assert rid is not None
        ok0, sids0 = service._da.get_timbus_anchors(rid, 0)
        ok1, sids1 = service._da.get_timbus_anchors(rid, 1)
        assert ok0 and sids0, f"{rc} dir=0 must be enabled"
        assert ok1 and sids1, f"{rc} dir=1 must be enabled"

    now_iso = datetime.now(TZ_HANOI).isoformat()
    called_timbus: List[Tuple[List[int], List[str], int]] = []

    def fake_live(route_id: int, direction: int = 0) -> RouteLiveResponse:
        pts = service._da.get_shape_points(route_id, "go" if direction == 0 else "re")
        sts = service.get_route_stations(route_id, direction).stations
        lat, lon, _ = _point_at_s(pts, max(0.0, sts[5].cum_distance_m - 250.0))
        return RouteLiveResponse(
            route_id=route_id,
            direction=direction,
            count=1,
            timestamp=now_iso,
            vehicles=[_make_bm_vehicle(1+direction, f"29F-099.9{direction}", route_id, lat, lon, now_iso).model_copy(update={'direction':direction})],
        )

    def fake_tb(station_ids, plates, direction=0, route_code="", timeout=3, inter_request_delay=0.05):
        called_timbus.append((list(station_ids), list(plates), direction))
        return {}

    monkeypatch.setattr(svc_mod, "fetch_live_vehicles_for_route", fake_live)
    monkeypatch.setattr(TimBusClient, "query_central_vehicles", classmethod(lambda cls, **kw: fake_tb(**kw)))

    # Gọi trên tuyến bị khóa 110 -> timbus_supported=False, poll_interval_sec=15, 0 lần gọi TimBus
    resp_ignored = service.get_station_eta("110", 0, 5)
    assert resp_ignored is not None
    assert resp_ignored.timbus_supported is False
    assert resp_ignored.poll_interval_sec == 15
    assert len(called_timbus) == 0

    live_ignored = service.get_live_vehicles("110", 0)
    assert live_ignored.timbus_supported is False

    # Gọi trên tuyến sạch 32 -> timbus_supported=True, poll_interval_sec=5, quét cả 2 chiều (dir=0 đúng anchor [1676, 161])
    resp_clean = service.get_station_eta("32", 0, 5)
    assert resp_clean is not None
    assert resp_clean.timbus_supported is True
    assert resp_clean.poll_interval_sec == 5
    assert len(called_timbus) == 2
    assert {d for _, _, d in called_timbus} == {0, 1}
    dir0_calls = [sids for sids, _, d in called_timbus if d == 0]
    assert dir0_calls == [[1676, 161]]


def test_zero_pass_tolerance_and_monotonicity_guard(service: BusMapServingService, monkeypatch: pytest.MonkeyPatch) -> None:
    """Dung sai vượt trạm = 0 (loại hẳn B1 khi s_tb > s_target, không fallback BM cũ) & guard không kéo lùi."""
    r32_id = service.resolve_route_id("32")
    pts = service._da.get_shape_points(r32_id, "go")
    sts = service.get_route_stations(r32_id, 0).stations
    target_order = 8
    s_target = sts[target_order].cum_distance_m

    lat_b1_bm, lon_b1_bm, _ = _point_at_s(pts, s_target - 180.0)
    lat_b1_passed, lon_b1_passed, _ = _point_at_s(pts, s_target + 25.0)
    lat_b2_bm, lon_b2_bm, _ = _point_at_s(pts, s_target - 900.0)
    lat_b2_tb, lon_b2_tb, s_b2_tb = _point_at_s(pts, s_target - 550.0)

    state = {"tb_mode": "active", "bm_ts": "2026-11-14T22:00:00+07:00"}

    def fake_live(route_id: int, direction: int = 0) -> RouteLiveResponse:
        return RouteLiveResponse(
            route_id=route_id,
            direction=direction,
            count=2,
            timestamp=state["bm_ts"],
            vehicles=[
                _make_bm_vehicle(101, "29F-051.01", route_id, lat_b1_bm, lon_b1_bm, state["bm_ts"]),
                _make_bm_vehicle(102, "29F-051.02", route_id, lat_b2_bm, lon_b2_bm, state["bm_ts"]),
            ],
        )

    def fake_tb(cls, station_ids, plates, direction=0, route_code="", timeout=3, inter_request_delay=0.05):
        if state["tb_mode"] == "active":
            return {
                "29F05101": _make_bus_record("29F05101", "32", lat_b1_passed, lon_b1_passed, 22),
                "29F05102": _make_bus_record("29F05102", "32", lat_b2_tb, lon_b2_tb, 26),
            }
        # Nhịp 2: TimBus tạm miss B2 nhưng B1 vẫn đã vượt trạm
        return {
            "29F05101": _make_bus_record("29F05101", "32", lat_b1_passed, lon_b1_passed, 22),
        }

    monkeypatch.setattr(svc_mod, "fetch_live_vehicles_for_route", fake_live)
    monkeypatch.setattr(TimBusClient, "query_central_vehicles", classmethod(fake_tb))

    # Nhịp 1: B1 vừa qua trạm (s_target + 25m) -> bị loại hẳn, không fallback BM cũ; chỉ còn B2 nguồn timbus
    resp1 = service.get_station_eta("32", 0, target_order)
    assert resp1 is not None
    plates1 = [b.plate for b in resp1.buses]
    assert "29F-051.01" not in plates1
    assert plates1 == ["29F-051.02"]
    assert resp1.buses[0].telemetry_source == "timbus"
    dist1 = resp1.buses[0].distance_to_station_m

    # Nhịp 2: Gói BusMap mới (s_bm lagged ở -900m) + TimBus tạm miss B2 -> guard giữ nguyên vị trí tiến tới (-550m), không kéo lùi!
    state["tb_mode"] = "miss_b2"
    state["bm_ts"] = datetime.now(TZ_HANOI).isoformat()
    resp2 = service.get_station_eta("32", 0, target_order)
    assert resp2 is not None
    assert [b.plate for b in resp2.buses] == ["29F-051.02"]
    assert resp2.buses[0].telemetry_source == "timbus"
    assert resp2.buses[0].distance_to_station_m == pytest.approx(dist1, abs=1.0)

    # Xe B1 vừa vượt trạm vẫn phải tiếp tục di chuyển trên /api/live-vehicles (không bị xóa khỏi _tb_last_valid hay tụt về BusMap cũ)
    live_map = service.get_live_vehicles("32", 0)
    b1_live = next((v for v in live_map.vehicles if v.plate == "29F-051.01"), None)
    assert b1_live is not None
    assert b1_live.telemetry_source == "timbus"
    assert b1_live.lat == pytest.approx(lat_b1_passed, abs=1e-6)
    assert b1_live.lng == pytest.approx(lon_b1_passed, abs=1e-6)


def test_three_tier_fallback_and_detour_recovery(service: BusMapServingService, monkeypatch: pytest.MonkeyPatch) -> None:
    """B2 ct_tb > 35m không làm rỗng ETA (fallback BM hợp lệ); B_detour được bắt lại ngay khi về tim đường."""
    r32_id = service.resolve_route_id("32")
    pts = service._da.get_shape_points(r32_id, "go")
    sm = ShapeProjectionModel.build(pts)
    sts = service.get_route_stations(r32_id, 0).stations
    target_order = 10
    s_target = sts[target_order].cum_distance_m

    lat_base, lon_base, _ = _point_at_s(pts, s_target - 600.0)
    # Điểm detour ~85m vuông góc ngoài tim đường (nằm trong (35m, 150m])
    _, _, base_seg_idx = sm.project_point(lat_base, lon_base)
    ux, uy = sm.segment_unit_tangent(base_seg_idx)
    lat_detour, lon_detour = _offset_point(lat_base, lon_base, -uy * 85.0, ux * 85.0)
    _, ct_check, _ = sm.project_point(lat_detour, lon_detour)
    assert 35.0 < ct_check <= 150.0

    lat_b3_bm, lon_b3_bm, _ = _point_at_s(pts, s_target - 1100.0)
    lat_returned, lon_returned, _ = _point_at_s(pts, s_target - 500.0)
    now_iso = datetime.now(TZ_HANOI).isoformat()

    mode = {"step": 1}

    def fake_live(route_id: int, direction: int = 0) -> RouteLiveResponse:
        return RouteLiveResponse(
            route_id=route_id,
            direction=direction,
            count=2,
            timestamp=now_iso,
            vehicles=[
                # 29F-052.81 trên BM ở vị trí B_detour (ct ~ 85m); 29F-052.23 ở -1100m trong hành lang
                _make_bm_vehicle(201, "29F-052.81", route_id, lat_detour, lon_detour, now_iso),
                _make_bm_vehicle(202, "29F-052.23", route_id, lat_b3_bm, lon_b3_bm, now_iso),
            ],
        )

    captured_queries: List[List[str]] = []

    def fake_tb(cls, station_ids, plates, direction=0, route_code="", timeout=3, inter_request_delay=0.05):
        captured_queries.append(list(plates))
        if mode["step"] == 1:
            # Cả 2 đều không lấy được bản ghi TimBus hợp lệ: 05281 vẫn lệch > 35m, 05223 thiếu TimBus
            return {
                "29F05281": _make_bus_record("29F05281", "32", lat_detour, lon_detour, 20),
            }
        # Nhịp 2: xe detour 05281 đã quay lại tim đường (ct <= 35m)
        return {
            "29F05281": _make_bus_record("29F05281", "32", lat_returned, lon_returned, 25),
        }

    monkeypatch.setattr(svc_mod, "fetch_live_vehicles_for_route", fake_live)
    monkeypatch.setattr(TimBusClient, "query_central_vehicles", classmethod(fake_tb))

    # Nhịp 1: Dù không còn xe TimBus nào sau lọc, Tầng 3 fallback trả về 29F-052.23 từ BusMap (không rỗng ETA),
    # đồng thời 29F-052.81 vẫn nằm trong tập plates được theo dõi.
    resp1 = service.get_station_eta("32", 0, target_order)
    assert resp1 is not None
    assert "29F05281" in captured_queries[0]
    assert [b.plate for b in resp1.buses] == ["29F-052.23"]
    assert resp1.buses[0].telemetry_source == "busmap"

    # Nhịp 2: 29F-052.81 quay lại tim đường trên TimBus -> được bắt lại ngay dù BusMap vẫn ở nhịp detour cũ!
    mode["step"] = 2
    resp2 = service.get_station_eta("32", 0, target_order)
    assert resp2 is not None
    assert resp2.buses[0].plate == "29F-052.81"
    assert resp2.buses[0].telemetry_source == "timbus"


def test_live_vehicles_5s_timbus_merge_and_poll_interval(
    service: BusMapServingService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lỗi 1: get_live_vehicles hợp nhất TimBus 5s trên tuyến sạch, trả poll_interval_sec=5 và chia sẻ cache 4s."""
    r32_id = service.resolve_route_id("32")
    assert r32_id is not None
    pts = service._da.get_shape_points(r32_id, "go")
    sts = service.get_route_stations(r32_id, 0).stations
    s_target = sts[10].cum_distance_m

    lat_bm, lon_bm, _ = _point_at_s(pts, s_target - 800.0)
    lat_tb, lon_tb, _ = _point_at_s(pts, s_target - 650.0)
    reverse_pts=service._da.get_shape_points(r32_id,'re')
    reverse_lat,reverse_lon,_=_point_at_s(reverse_pts,1000.)
    now_iso = datetime.now(TZ_HANOI).isoformat()

    def fake_live(route_id: int, direction: int = 0) -> RouteLiveResponse:
        return RouteLiveResponse(
            route_id=route_id,
            direction=direction,
            count=1,
            timestamp=now_iso,
            vehicles=[_make_bm_vehicle(301+direction, "29F-053.01" if direction==0 else "29F-053.02", route_id,
                                      lat_bm if direction==0 else reverse_lat,lon_bm if direction==0 else reverse_lon,
                                      now_iso, speed_kmh=22.0).model_copy(update={'direction':direction})],
        )

    tb_calls: List[List[str]] = []

    def fake_tb(cls, station_ids, plates, direction=0, route_code="", timeout=3, inter_request_delay=0.05):
        tb_calls.append(list(plates))
        if direction==0:return {"29F05301": _make_bus_record("29F05301", "32", lat_tb, lon_tb, speed_kmh=30)}
        return {"29F05302": _make_bus_record("29F05302", "32", reverse_lat, reverse_lon, speed_kmh=30)}

    monkeypatch.setattr(svc_mod, "fetch_live_vehicles_for_route", fake_live)
    monkeypatch.setattr(TimBusClient, "query_central_vehicles", classmethod(fake_tb))

    live_clean = service.get_live_vehicles("32", 0)
    assert live_clean.timbus_supported is True
    assert live_clean.poll_interval_sec == 5
    assert live_clean.count == 1
    assert live_clean.vehicles[0].telemetry_source == "timbus"
    assert live_clean.vehicles[0].lat == pytest.approx(lat_tb, abs=1e-6)
    assert len(tb_calls) == 2  # Query toàn bộ xe trên cả 2 chiều 0 và 1

    # Gọi get_station_eta ngay sau (< 4s) dùng lại cache _tb_last_valid trên cả 2 chiều, không gọi lặp TimBus
    eta_resp = service.get_station_eta("32", 0, 10)
    assert eta_resp is not None
    assert len(tb_calls) == 2
    b0 = eta_resp.buses[0]
    assert b0.telemetry_source == "timbus"
    assert b0.estimated_arrival_time
    assert len(b0.estimated_arrival_time) == 8  # HH:MM:SS
    assert b0.eta_seconds == pytest.approx(b0.safe_window.p50_seconds, abs=0.2)
    assert b0.optimistic_eta_seconds == pytest.approx(max(0.0, b0.eta_seconds - b0.safe_window.buffer_seconds), abs=0.2)

    # Đối chiếu estimated_arrival_time khớp time now + P50 (arrival_time_epoch) và optimistic_arrival_time
    expected_hms = datetime.fromtimestamp(b0.arrival_time_epoch, tz=TZ_HANOI).strftime("%H:%M:%S")
    assert b0.estimated_arrival_time == expected_hms
    assert b0.optimistic_arrival_time is not None and len(b0.optimistic_arrival_time) == 8

    # Tuyến khóa 110 giữ nguyên 15s và không gọi TimBus
    live_ignored = service.get_live_vehicles("110", 0)
    assert live_ignored.timbus_supported is False
    assert live_ignored.poll_interval_sec == 15
    assert len(tb_calls) == 2


def test_macro_speed_estimation_over_120s_suppresses_eta_jitter(
    service: BusMapServingService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lỗi 3: MacroSpeedTracker dùng delta_s / delta_t (> 120s) giữ vận tốc & ETA ổn định dù hộp đen giật 0..48 km/h."""
    r32_id = service.resolve_route_id("32")
    assert r32_id is not None
    pts = service._da.get_shape_points(r32_id, "go")
    sts = service.get_route_stations(r32_id, 0).stations
    target_order = 12
    s_target = sts[target_order].cum_distance_m

    # Nạp chuỗi lịch sử quãng đường 135 giây (~5.55 m/s = 20.0 km/h) với tốc độ hộp đen dao động mạnh
    t0 = 1_760_000_000.0
    s_start = s_target - 1800.0
    timeline_steps = [
        (0.0, 0.0, 20.0),
        (30.0, 166.0, 12.0),
        (60.0, 333.0, 35.0),
        (90.0, 500.0, 5.0),
        (125.0, 694.0, 0.0),   # Đèn đỏ tức thời 0 km/h nhưng trên 125s xe đi ~19.99 km/h
        (130.0, 722.0, 48.0),  # Tăng ga tức thời 48 km/h nhưng trên 130s xe vẫn đi ~20.0 km/h
    ]

    v_smooth = 0.0
    win_sec = 0.0
    outputs: List[Tuple[float, float, float]] = []
    for dt_s, ds_m, raw_spd in timeline_steps:
        lat, lon, s_proj = _point_at_s(pts, s_start + ds_m)
        t_cur = t0 + dt_s
        v_smooth, win_sec = service._speed_tracker.observe_and_estimate(
            route_id=r32_id,
            dir_int=0,
            plate_norm="29F05999",
            t_sample=t_cur,
            s_bus=s_proj,
            raw_speed_kmh=raw_spd,
            bm_speed_kmh=20.0,
            route_base_spd_kmh=21.0,
        )
        # Cập nhật song song extractor để kiểm chứng _speed_features trên cửa sổ 75s / 240s / 405s
        dto = _make_bm_vehicle(999, "29F-059.99", r32_id, lat, lon, datetime.fromtimestamp(t_cur, tz=TZ_HANOI).isoformat(), speed_kmh=v_smooth)
        service._extractor.update_observation(r32_id, 0, [dto], t_cur)
        outputs.append((dt_s, v_smooth, win_sec))

    # Sau > 120s (nhịp 125s -> 0 km/h và nhịp 130s -> 48 km/h), tốc độ ổn định chỉ quanh ~20 km/h, KHÔNG nhảy 0..48!
    _, spd_125, win_125 = outputs[-2]
    _, spd_130, win_130 = outputs[-1]
    assert win_125 > 120.0
    assert win_130 > 120.0
    assert 16.0 <= spd_125 <= 24.0
    assert 16.0 <= spd_130 <= 24.0
    assert abs(spd_130 - spd_125) < 2.0

    # Kiểm chứng ETA giữa hai nhịp hộp đen 0 km/h vs 48 km/h thông qua get_station_eta giả lập
    lat_130, lon_130, _ = _point_at_s(pts, s_start + 722.0)
    now_iso_130 = datetime.fromtimestamp(t0 + 130.0, tz=TZ_HANOI).isoformat()

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromtimestamp(t0 + 135.0, tz=tz)

    monkeypatch.setattr(svc_mod, "datetime", _FixedDatetime)
    monkeypatch.setattr(
        svc_mod,
        "fetch_live_vehicles_for_route",
        lambda route_id, direction=0: RouteLiveResponse(
            route_id=route_id,
            direction=direction,
            count=1,
            timestamp=now_iso_130,
            vehicles=[_make_bm_vehicle(999, "29F-059.99", route_id, lat_130, lon_130, now_iso_130, speed_kmh=20.0)],
        ),
    )
    lat_135, lon_135, _ = _point_at_s(pts, s_start + 750.0)
    monkeypatch.setattr(
        TimBusClient,
        "query_central_vehicles",
        classmethod(lambda cls, **kw: {"29F05999": _make_bus_record("29F05999", "32", lat_135, lon_135, speed_kmh=48)}),
    )

    eta_out = service.get_station_eta("32", 0, target_order)
    assert eta_out is not None and len(eta_out.buses) == 1
    b = eta_out.buses[0]
    assert b.raw_speed_kmh == 48.0
    assert 16.0 <= b.speed_kmh <= 24.0
    assert b.speed_window_sec is not None and b.speed_window_sec > 120.0
    assert b.estimated_arrival_time == datetime.fromtimestamp(b.arrival_time_epoch, tz=TZ_HANOI).strftime("%H:%M:%S")


def test_macro_speed_win_dt_cache_and_parked_dwell_trim(service: BusMapServingService) -> None:
    """MacroSpeedTracker: nhịp < 4s không thổi phồng win_dt và cắt phần đỗ bến ban đầu sau khi xe xuất phát."""
    r32_id = service.resolve_route_id("32")
    assert r32_id is not None
    t0 = 1_760_100_000.0
    # Xe đỗ 120s tại s=100m (chênh <= 3m < 15m)
    for dt in range(0, 125, 10):
        service._speed_tracker.observe_and_estimate(r32_id, 0, "29F05888", t0 + dt, 101.0 + (dt % 20 == 0), 0.0, 0.0, 20.0)

    # Xuất phát tiến 100m sau 20s -> vượt xa > 25m khỏi vùng đỗ bến, cắt bỏ 120s đỗ trước đó
    spd_dep, win_dep = service._speed_tracker.observe_and_estimate(
        r32_id, 0, "29F05888", t0 + 140.0, 201.0, 22.0, 22.0, 20.0
    )
    assert spd_dep >= 15.0
    assert win_dep <= 25.0

    # Nhịp lặp < 4s phải giữ nguyên win_dt đã tính chứ không cộng lại từ đầu hist
    spd_dup, win_dup = service._speed_tracker.observe_and_estimate(
        r32_id, 0, "29F05888", t0 + 141.0, 205.0, 22.0, 22.0, 20.0
    )
    assert spd_dup == spd_dep
    assert win_dup == win_dep


def test_web_app_live_vehicles_uses_hybrid_timbus_service(monkeypatch: pytest.MonkeyPatch) -> None:
    """/api/live-vehicles đi qua service.get_live_vehicles(), trả 5s + telemetry_source='timbus' trên tuyến sạch."""
    from fastapi.testclient import TestClient
    from modules.eta.web_demo import app as web_app_mod

    web_svc = web_app_mod.service
    r32_id = web_svc.resolve_route_id("32")
    assert r32_id is not None
    pts = web_svc._da.get_shape_points(r32_id, "go")
    sts = web_svc.get_route_stations(r32_id, 0).stations
    s_target = sts[8].cum_distance_m
    lat_bm, lon_bm, _ = _point_at_s(pts, s_target - 500.0)
    lat_tb, lon_tb, _ = _point_at_s(pts, s_target - 350.0)
    now_iso = datetime.now(TZ_HANOI).isoformat()

    monkeypatch.setattr(
        svc_mod,
        "fetch_live_vehicles_for_route",
        lambda route_id, direction=0: RouteLiveResponse(
            route_id=route_id,
            direction=direction,
            count=1,
            timestamp=now_iso,
            vehicles=[_make_bm_vehicle(401, "29F-054.01", route_id, lat_bm, lon_bm, now_iso)],
        ),
    )
    monkeypatch.setattr(
        TimBusClient,
        "query_central_vehicles",
        classmethod(lambda cls, **kw: {"29F05401": _make_bus_record("29F05401", "32", lat_tb, lon_tb, 26)}),
    )

    with TestClient(web_app_mod.app) as client:
        res = client.get("/api/live-vehicles", params={"route": "32", "direction": 0})
        assert res.status_code == 200
        body = res.json()
        assert body["timbus_supported"] is True
        assert body["poll_interval_sec"] == 5
        assert body["count"] == 1
        assert body["vehicles"][0]["telemetry_source"] == "timbus"
        assert body["vehicles"][0]["lat"] == pytest.approx(lat_tb, abs=1e-6)
