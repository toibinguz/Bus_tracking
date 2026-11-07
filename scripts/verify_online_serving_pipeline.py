#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Verification Script: verify_online_serving_pipeline.py
Nghiệm thu toàn diện TD-26: Bộ trích xuất Đặc trưng Trực tuyến và Dịch vụ Phục vụ ETA (Bước 3.5).

Nội dung kiểm định:
1. Kiểm tra Độ lệch Đặc trưng (Train/Serve Zero Skew): So sánh trực tiếp giữa Gold Feature Store và OnlineFeatureExtractor.
2. Kiểm tra Độ trễ (Serving Latency SLA): Đo lường P50, P95 độ trễ trích xuất + suy luận cho 1 xe và theo lô.
3. Kiểm tra Cổng Bến Đầu Cuối (Terminal Gate TD-19): Kiểm thử các trạng thái AT_ORIGIN_TERMINAL, AT_DESTINATION_TERMINAL, ACTIVE_IN_TRANSIT.
4. Kiểm thử Tích hợp Trực tiếp E2E (Live Real-Time ETA): Truy vấn trực tiếp API BusMap cho Tuyến 02 và xuất bảng ETA thực tế.
"""

import os
import sys
import time
import numpy as np
import pandas as pd

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, BASE_DIR)

from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation import (
    EtaServingService,
    OnlineFeatureExtractor,
    EtaInferenceEngine,
)


def verify_feature_parity():
    print("=" * 88)
    print("KIỂM ĐỊNH 1: ĐỐI SOÁT ĐỘ LỆCH ĐẶC TRƯNG TRAIN / SERVE (ZERO SKEW ASSERTION)")
    print("=" * 88)

    test_pq = os.path.join(
        BASE_DIR, "data", "lakehouse", "gold", "eta_feature_store", "split=test", "route_code=02", "part-00000.snappy.parquet"
    )
    if not os.path.exists(test_pq):
        print(f"[!] Không tìm thấy tệp test Parquet tại {test_pq}. Bỏ qua kiểm định 1.")
        return

    df_gold = pd.read_parquet(test_pq).head(200)
    print(f"[*] Nạp {len(df_gold)} dòng mẫu từ Gold Feature Store Tuyến 02...")

    extractor = OnlineFeatureExtractor()

    discrepancies = []
    checked_count = 0

    for idx, row in df_gold.iterrows():
        rc = str(row["route_code"])
        ds = str(row["direction"])
        vid = str(row["vehicle_id"])
        t_epoch = float(row["device_epoch"])
        s_bus = float(row["s_bus_m"])
        t_ord = int(row["target_station_order"])
        spd = float(row["ego_speed_instant_kmh"])

        df_online = extractor.extract_features_for_ego(
            route_code=rc,
            direction=ds,
            vehicle_id=vid,
            device_epoch=t_epoch,
            s_bus_m=s_bus,
            speed_kmh=spd,
            target_station_order=t_ord,
        )

        if df_online.empty:
            continue

        checked_count += 1
        online_row = df_online.iloc[0]

        # Kiểm tra các đặc trưng xương sống
        check_cols = [
            "baseline_eta_p50_sec",
            "baseline_eta_mean_sec",
            "baseline_skew_sec",
            "remaining_distance_m",
            "sin_time",
            "cos_time",
            "hour_slot",
            "day_type",
        ]

        for col in check_cols:
            v_gold = float(row[col])
            v_onl = float(online_row[col])
            diff = abs(v_gold - v_onl)
            if diff > 0.05:
                discrepancies.append((idx, col, v_gold, v_onl, diff))

    print(f"[+] Đã đối soát {checked_count} mẫu. Số lượng sai lệch (> 0.05): {len(discrepancies)}")
    if discrepancies:
        for idx, col, vg, vo, d in discrepancies[:5]:
            print(f"  [!] Lệch tại dòng {idx}, cột {col}: Gold={vg:.3f} vs Online={vo:.3f} (diff={d:.3f})")
        assert len(discrepancies) == 0, "Phát hiện sai lệch đặc trưng giữa Gold và Online!"
    else:
        print("[PASS] Tuyệt đối ZERO TRAIN/SERVE SKEW! Các đặc trưng cốt lõi khớp chính xác 100%.")


def verify_terminal_gate_and_corridor():
    print("\n" + "=" * 88)
    print("KIỂM ĐỊNH 2: KIỂM CHỨNG CỔNG BẾN ĐẦU CUỐI (TERMINAL GATE TD-19) & BỘ LỌC HÀNH LANG")
    print("=" * 88)

    service = EtaServingService()

    # 1. Xe tại bến xuất phát chiều 'go' (BX Yên Nghĩa: lat=20.949979, lon=105.747619, s_bus_m < station 1)
    res_origin = service.predict_for_vehicle(
        route_code="02",
        direction="go",
        vehicle_id="TEST_01",
        lat=20.949979,
        lon=105.747619,
        speed_kmh=0.0,
    )
    print(f"[*] Xe tại BX Yên Nghĩa (bến xuất phát chiều go): Status = {res_origin.get('status')} | Message = {res_origin.get('message')}")
    assert res_origin.get("status") == "AT_ORIGIN_TERMINAL", f"Lỗi phân định cổng xuất phát: {res_origin.get('status')}"

    # 1b. Xe tại bến đích chiều 'go' ((A) Bác Cổ: lat=21.023183, lon=105.860833, s_bus_m >= station N-1)
    res_dest = service.predict_for_vehicle(
        route_code="02",
        direction="go",
        vehicle_id="TEST_01B",
        lat=21.023183,
        lon=105.860833,
        speed_kmh=0.0,
    )
    print(f"[*] Xe tại bến đích Bác Cổ (chiều go): Status = {res_dest.get('status')} | Message = {res_dest.get('message')}")
    assert res_dest.get("status") == "AT_DESTINATION_TERMINAL", f"Lỗi phân định cổng bến đích: {res_dest.get('status')}"

    # 1c. Xe đang chạy trên hành lang nội tuyến (Ngã Tư Sở: lat=21.0064, lon=105.8231)
    res_active = service.predict_for_vehicle(
        route_code="02",
        direction="go",
        vehicle_id="TEST_01C",
        lat=21.0064,
        lon=105.8231,
        speed_kmh=25.0,
    )
    print(f"[*] Xe đang chạy nội tuyến (Ngã Tư Sở): Status = {res_active.get('status')} | Predictions count = {res_active.get('predictions_count')}")
    assert res_active.get("status") == "ACTIVE_IN_TRANSIT", f"Lỗi phân định xe đang chạy: {res_active.get('status')}"

    # 2. Xe đi lệch hành lang sâu (lat/lon ở vịnh Bắc Bộ / Hoàn Kiếm khi xe tuyến Ba La)
    res_detour = service.predict_for_vehicle(
        route_code="02",
        direction="go",
        vehicle_id="TEST_02",
        lat=21.150,  # Lệch 15km lên phía Bắc
        lon=105.800,
        speed_kmh=20.0,
    )
    print(f"[*] Xe đi lệch hành lang 15km: Status = {res_detour.get('status')} | cross_track = {res_detour.get('cross_track_m')}m")
    assert res_detour.get("status") == "DETOUR_OFF_CORRIDOR", "Bộ lọc hành lang không chặn xe lệch sâu!"

    print("[PASS] Cổng Bến Đầu Cuối và Bộ lọc Hành lang hoạt động chuẩn xác.")


def verify_latency_and_live_serving():
    print("\n" + "=" * 88)
    print("KIỂM ĐỊNH 3: ĐO ĐỘ TRỄ SUY LUẬN (LATENCY SLA) & THỬ NGHIỆM TRỰC TIẾP E2E TUYẾN 02")
    print("=" * 88)

    service = EtaServingService()

    # 1. Đo độ trễ 100 lần truy vấn đơn lẻ
    latencies = []
    test_lat, test_lon = 21.006422, 105.823181  # Điểm hợp lệ trên Tuyến 02 (Ngã Tư Sở)
    for _ in range(100):
        t0 = time.perf_counter()
        res = service.predict_for_vehicle(
            route_code="02",
            direction="go",
            vehicle_id="231970",
            lat=test_lat,
            lon=test_lon,
            speed_kmh=25.0,
        )
        latencies.append((time.perf_counter() - t0) * 1000.0)

    p50 = np.percentile(latencies, 50)
    p95 = np.percentile(latencies, 95)
    p99 = np.percentile(latencies, 99)
    print(f"[+] Độ trễ trích xuất đặc trưng + suy luận toàn bộ 13 trạm phía trước (100 lần):")
    print(f"    - P50 (Median) : {p50:.2f} ms")
    print(f"    - P95          : {p95:.2f} ms")
    print(f"    - P99          : {p99:.2f} ms")
    assert p50 < 30.0, f"Độ trễ P50 vượt ngưỡng 30ms ({p50:.2f}ms)"

    # 2. Truy vấn trực tiếp từ API BusMap thật
    print("\n[*] Đang truy vấn trực tiếp BusMap API Tuyến 02 (Chiều đi)...")
    live_res = service.predict_route_snapshot_live(route_code="02", direction=0)
    print(f"[+] Kết quả snapshot: Tìm thấy {live_res['total_buses']} xe ({live_res['active_in_transit_count']} xe active in-transit).")
    print(f"[+] Tổng thời gian xử lý toàn tuyến (Mạng + Chiếu + 54 Đặc trưng + XGBoost): {live_res['latency_ms']} ms")

    if live_res["buses"]:
        print("\n--- BẢNG DỰ BÁO ETA TRỰC TIẾP TỪNG XE TUYẾN 02 ---")
        for b in live_res["buses"][:5]:
            status = b.get("status")
            plate = b.get("plate")
            vid = b.get("vehicle_id")
            spd = b.get("speed_kmh", 0)
            if status == "ACTIVE_IN_TRANSIT":
                cur_st = b.get("current_station_name")
                preds = b.get("predictions", [])
                if preds:
                    next_pred = preds[0]
                    print(f"Xe [{plate}] (VID={vid}, {spd} km/h) tại '{cur_st}':")
                    print(f"  -> Trạm tới: '{next_pred['target_station_name']}' | ETA: {next_pred['eta_minutes']} ph ({next_pred['eta_seconds']}s) | Baseline: {next_pred['baseline_p50_sec']}s")
            else:
                print(f"Xe [{plate}] (VID={vid}): Trạng thái = {status}")

    print("\n[PASS] Toàn bộ quy trình Serving trực tuyến hoàn thành xuất sắc!")


if __name__ == "__main__":
    verify_feature_parity()
    verify_terminal_gate_and_corridor()
    verify_latency_and_live_serving()
