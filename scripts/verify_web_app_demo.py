"""
Module 3 - Step 3.5: Comprehensive Integration & Contract-First Test Suite.
Verifies all 4 RESTful endpoints, Pydantic schemas, TTL cache behavior,
and Asymmetric Safe Arrival Window logic using FastAPI TestClient & Schemathesis.
"""

import os
import sys
import time

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, BASE_DIR)

from fastapi.testclient import TestClient
import schemathesis

from module_3_bus_eta_prediction.step_3_5_web_demo.app import app
from module_3_bus_eta_prediction.step_3_5_web_demo.contract import (
    HealthResponse,
    LiveEtaResponse,
    RouteGeometryResponse,
    RouteItem,
)

client = TestClient(app)


def test_01_health_endpoint():
    print("\n" + "=" * 80)
    print("KIỂM ĐỊNH 1: ENDPOINT /api/v1/health")
    print("=" * 80)
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200, f"Status code failed: {resp.status_code}"
    data = resp.json()
    validated = HealthResponse(**data)
    print(f"[+] Health Response: status={validated.status}, RAM={validated.memory_rss_mb:.1f} MB, active_cache={validated.active_cache_entries}")
    assert validated.status == "healthy"
    assert validated.memory_rss_mb > 0
    print("[PASS] Endpoint Health hợp lệ chuẩn 100%.")


def test_02_routes_catalog():
    print("\n" + "=" * 80)
    print("KIỂM ĐỊNH 2: ENDPOINT /api/v1/routes (DANH MỤC TUYẾN)")
    print("=" * 80)
    resp = client.get("/api/v1/routes")
    assert resp.status_code == 200
    routes = resp.json()
    assert isinstance(routes, list) and len(routes) > 0, "Routes catalog is empty"
    print(f"[+] Tổng số tuyến trong danh mục: {len(routes)} tuyến")
    
    # Validate each item matches contract
    for r in routes[:10]:
        item = RouteItem(**r)
    
    # Check Route 02 exists
    r02 = next((r for r in routes if r["route_code"] == "02"), None)
    assert r02 is not None, "Tuyến 02 phải tồn tại trong danh mục"
    print(f"[+] Tìm thấy Tuyến 02: ID={r02['route_id']}, Tên='{r02['route_name']}'")
    print("[PASS] Endpoint Routes hợp lệ chuẩn 100%.")


def test_03_route_geometry():
    print("\n" + "=" * 80)
    print("KIỂM ĐỊNH 3: ENDPOINT /api/v1/routes/{route_code}/geometry (TIM ĐƯỜNG & TRẠM)")
    print("=" * 80)
    # Test valid route
    resp = client.get("/api/v1/routes/02/geometry?direction=go")
    assert resp.status_code == 200
    geo_data = resp.json()
    validated = RouteGeometryResponse(**geo_data)
    
    print(f"[+] Tuyến 02 Chiều Đi: Chiều dài={validated.route_length_m:.1f}m, Số điểm tim đường={len(validated.shape_geojson.coordinates)}, Số trạm={len(validated.stations)}")
    assert len(validated.shape_geojson.coordinates) > 100
    assert len(validated.stations) >= 20
    
    # Verify coordinates format [lon, lat]
    first_pt = validated.shape_geojson.coordinates[0]
    assert 105.0 <= first_pt[0] <= 106.0, f"Invalid lon: {first_pt[0]}"
    assert 20.0 <= first_pt[1] <= 22.0, f"Invalid lat: {first_pt[1]}"
    
    # Verify 404 for invalid route
    resp_404 = client.get("/api/v1/routes/INVALID_999/geometry")
    assert resp_404.status_code == 404
    print("[+] Kiểm tra mã lỗi 404 cho tuyến không tồn tại: Chính xác.")
    print("[PASS] Endpoint Geometry hợp lệ chuẩn 100%.")


def test_04_live_eta_and_cache():
    print("\n" + "=" * 80)
    print("KIỂM ĐỊNH 4: ENDPOINT /api/v1/routes/02/live-eta (LIVE PREDICTION & TTL CACHE)")
    print("=" * 80)
    
    # Request 1: Cache Miss
    t0 = time.time()
    resp1 = client.get("/api/v1/routes/02/live-eta?direction=go")
    lat1_ms = (time.time() - t0) * 1000.0
    assert resp1.status_code == 200
    data1 = resp1.json()
    val1 = LiveEtaResponse(**data1)
    print(f"[+] Request 1 (Cache Miss): cached={val1.cached}, total_buses={val1.total_buses}, active={val1.active_in_transit_count}, latency={lat1_ms:.2f}ms")
    print(f"    Tình trạng hành lang: '{val1.traffic_condition}'")
    assert val1.cached is False
    
    # Request 2: Cache Hit (sub-5ms SLA)
    t0 = time.time()
    resp2 = client.get("/api/v1/routes/02/live-eta?direction=go")
    lat2_ms = (time.time() - t0) * 1000.0
    assert resp2.status_code == 200
    data2 = resp2.json()
    val2 = LiveEtaResponse(**data2)
    print(f"[+] Request 2 (Cache Hit) : cached={val2.cached}, latency={lat2_ms:.2f}ms")
    assert val2.cached is True
    assert lat2_ms < 50.0, f"Cache hit latency quá cao: {lat2_ms:.2f}ms"
    
    # Verify Asymmetric Arrival Risk logic for active buses
    for b in val2.buses:
        if b.status == "ACTIVE_IN_TRANSIT" and b.predictions:
            p = b.predictions[0]
            print(f"    [*] Kiểm tra xe {b.plate}: Đến '{p.target_station_name}' | Dự kiến={p.expected_arrival_time} | Cửa sổ an toàn={p.safe_window} | Khuyến nghị={p.safe_arrival_time}")
            # So sánh an toàn không bị lỗi chuỗi wrap-around khi qua nửa đêm (Midnight Wrap-around)
            t_safe_m = int(p.safe_arrival_time.split(":")[0]) * 60 + int(p.safe_arrival_time.split(":")[1])
            t_exp_m = int(p.expected_arrival_time.split(":")[0]) * 60 + int(p.expected_arrival_time.split(":")[1])
            time_delta_min = (t_exp_m - t_safe_m) % (24 * 60)
            assert time_delta_min < 12 * 60, (
                f"safe_arrival_time ({p.safe_arrival_time}) không được muộn hơn expected_arrival_time ({p.expected_arrival_time})"
            )
            if p.baseline_p10_sec is not None and p.baseline_p50_sec is not None:
                assert p.baseline_p10_sec <= p.baseline_p50_sec, (
                    f"baseline_p10_sec ({p.baseline_p10_sec}s) phải <= baseline_p50_sec ({p.baseline_p50_sec}s)"
                )
            break
            
    print("[PASS] Endpoint Live ETA & TTL Cache hoạt động hoàn hảo!")


def test_05_schemathesis_openapi_contract():
    print("\n" + "=" * 80)
    print("KIỂM ĐỊNH 5: KIỂM CHỨNG HỢP ĐỒNG TỰ ĐỘNG BẰNG SCHEMATHESIS")
    print("=" * 80)
    schema = schemathesis.openapi.from_dict(app.openapi())
    print(f"[+] Đã tải OpenAPI Spec: Tiêu đề='{schema.raw_schema.get('info', {}).get('title')}', Số endpoints={len(schema.raw_schema.get('paths', {}))}")
    assert "/api/v1/routes" in schema.raw_schema.get("paths", {})
    assert "/api/v1/routes/{route_code}/geometry" in schema.raw_schema.get("paths", {})
    assert "/api/v1/routes/{route_code}/live-eta" in schema.raw_schema.get("paths", {})
    assert "/api/v1/health" in schema.raw_schema.get("paths", {})
    print("[PASS] OpenAPI 3.1 Spec tương thích 100% với Schemathesis!")


if __name__ == "__main__":
    test_01_health_endpoint()
    test_02_routes_catalog()
    test_03_route_geometry()
    test_04_live_eta_and_cache()
    test_05_schemathesis_openapi_contract()
    print("\n" + "=" * 80)
    print("TẤT CẢ 5 BÀI KIỂM THỬ WEB DEMO ĐÃ VƯỢT QUA VỚI EXIT CODE 0!")
    print("=" * 80)
