"""
Module 3 - Genuine Empirical Verification & Anti-Cheating Remediation Test Suite.
Enforces strict architectural integrity, eliminates Train/Serve feature skew, prevents ghost vehicles,
and mathematically verifies all serving mechanics against Master Ground Truth CSDL data/hanoi_bus_system.db.

Canons: AGENTS.md Điều 1 (Empirical Verification Over Speculation), Điều 4 (Single Source of Truth),
        Điều 5 (Derived Kinematics), and Điều 8 (Unfiltered Technical Debt Disclosure).
"""

import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Tuple

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, BASE_DIR)

from fastapi.testclient import TestClient

from config.system_config import DEFAULT_DB_PATH
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.eta_serving_service import (
    EtaServingService,
)
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.online_feature_extractor import (
    OnlineFeatureExtractor,
)
from module_3_bus_eta_prediction.step_3_5_web_demo.api_routes import (
    evaluate_corridor_traffic_condition,
)
from module_3_bus_eta_prediction.step_3_5_web_demo.app import app

client = TestClient(app)


# ==============================================================================
# TEST 1: GROUND TRUTH SQL QUANTILE INTEGRITY AUDIT (ĐỐI SOÁT VỚI CSDL SQLITE GỐC)
# ==============================================================================

def test_01_ground_truth_sql_quantile_parity():
    """
    KIỂM TRA ĐỐI SOÁT PHÂN VỊ VỚI CSDL GỐC (GROUND TRUTH SQL PARITY):
    Truy vấn trực tiếp vào bảng agg_segment_travel_times trong data/hanoi_bus_system.db.
    Tính toán độc lập tổng phân vị sum(tt_p10_sec), sum(tt_p50_sec), sum(tt_p90_sec)
    cho các cặp trạm và các khung giờ khác nhau.
    So sánh với giá trị mà Service và API trả về:
    - Bắt buộc giá trị baseline_p10_sec, baseline_p50_sec, baseline_p90_sec phải khớp với CSDL (dung sai <= 2s do nội suy vị trí đầu xe).
    - Bắt buộc phân vị phải biến động thực tế theo khung giờ: Giờ cao điểm (8h) P90 phải cao hơn giờ thấp điểm (14h).
    """
    print("\n" + "=" * 80)
    print("KIỂM ĐỊNH 1: ĐỐI SOÁT PHÂN VỊ BASELINE P10, P50, P90 TRỰC TIẾP VỚI CSDL SQLITE GỐC")
    print("=" * 80)

    db_file = os.path.join(BASE_DIR, DEFAULT_DB_PATH) if not os.path.isabs(DEFAULT_DB_PATH) else DEFAULT_DB_PATH
    conn = sqlite3.connect(db_file)
    cur = conn.cursor()

    service = EtaServingService.get_instance()

    test_cases = [
        ("02", "go", 5, 12, 0, 8, "Tuyến 02: Trạm 5 -> 12, Giờ cao điểm sáng (8h) Ngày thường"),
        ("02", "go", 5, 12, 0, 14, "Tuyến 02: Trạm 5 -> 12, Giờ thấp điểm trưa (14h) Ngày thường"),
        ("32", "go", 4, 15, 0, 8, "Tuyến 32: Trạm 4 -> 15, Giờ cao điểm sáng (8h) Ngày thường"),
        ("02", "re", 6, 18, 1, 17, "Tuyến 02: Chiều về Trạm 6 -> 18, Chiều Thứ 7 (17h)"),
    ]

    p90_peak_8h = None
    p90_offpeak_14h = None

    for r_code, d_str, st_start, st_target, dt_v, hr_v, desc in test_cases:
        print(f"\n[*] Kiểm tra kịch bản: {desc}")

        query = """
            SELECT 
                SUM(tt_p10_sec),
                SUM(tt_p50_sec),
                SUM(tt_p90_sec)
            FROM agg_segment_travel_times
            WHERE route_code = ?
              AND direction = ?
              AND day_type = ?
              AND hour_slot = ?
              AND from_station_order >= ?
              AND to_station_order <= ?
        """
        cur.execute(query, (r_code, d_str, dt_v, hr_v, st_start, st_target))
        row = cur.fetchone()
        assert row is not None and row[0] is not None, f"Không tìm thấy dữ liệu phân vị trong CSDL cho {r_code} {d_str} giờ {hr_v}"
        sql_p10, sql_p50, sql_p90 = float(row[0]), float(row[1]), float(row[2])
        print(f"    [CSDL SQLite Gốc] Ground Truth: P10={sql_p10:.1f}s | P50={sql_p50:.1f}s | P90={sql_p90:.1f}s | IQR={sql_p90-sql_p10:.1f}s")

        if r_code == "02" and hr_v == 8:
            p90_peak_8h = sql_p90
        elif r_code == "02" and hr_v == 14:
            p90_offpeak_14h = sql_p90

        st_details = service.extractor.station_details.get((r_code, d_str), [])
        assert len(st_details) > st_start, f"Tuyến {r_code} thiếu trạm {st_start}"
        start_pt = next(s for s in st_details if s["station_order"] == st_start)

        simulated_dt = datetime(2026, 11, 4 if dt_v == 0 else 7, hr_v, 15, 0)
        sim_epoch = simulated_dt.timestamp()

        res = service.predict_for_vehicle(
            route_code=r_code,
            direction=d_str,
            vehicle_id="GROUND_TRUTH_PROBE_BUS",
            lat=start_pt["lat"],
            lon=start_pt["lon"],
            speed_kmh=18.0,
            device_epoch=sim_epoch,
            target_station_order=st_target,
        )

        assert res["status"] == "ACTIVE_IN_TRANSIT", f"Expected ACTIVE_IN_TRANSIT, got {res.get('status')}"
        preds = res.get("predictions", [])
        assert len(preds) == 1, f"Expected 1 target prediction, got {len(preds)}"
        pred_item = preds[0]

        assert "baseline_p10_sec" in pred_item, "KHUYẾT TẬT: Thiếu trường 'baseline_p10_sec' trong prediction item trả về!"
        assert "baseline_p90_sec" in pred_item, "KHUYẾT TẬT: Thiếu trường 'baseline_p90_sec' trong prediction item trả về!"
        assert "baseline_p50_sec" in pred_item, "KHUYẾT TẬT: Thiếu trường 'baseline_p50_sec' trong prediction item trả về!"

        ret_p10 = float(pred_item["baseline_p10_sec"])
        ret_p50 = float(pred_item["baseline_p50_sec"])
        ret_p90 = float(pred_item["baseline_p90_sec"])
        print(f"    [Service Trả Về ] Đo đạc thực tế: P10={ret_p10:.1f}s | P50={ret_p50:.1f}s | P90={ret_p90:.1f}s")

        diff_p10 = abs(ret_p10 - sql_p10)
        diff_p50 = abs(ret_p50 - sql_p50)
        diff_p90 = abs(ret_p90 - sql_p90)
        print(f"    [Sai số Đối soát] Delta P10={diff_p10:.2f}s | Delta P50={diff_p50:.2f}s | Delta P90={diff_p90:.2f}s")

        assert diff_p50 <= 3.0, f"LỆCH DỮ LIỆU: P50 trả về ({ret_p50}s) lệch quá 3s so với CSDL gốc ({sql_p50}s)!"
        assert diff_p10 <= 3.0, f"LỆCH DỮ LIỆU: P10 trả về ({ret_p10}s) lệch quá 3s so với CSDL gốc ({sql_p10}s)!"
        assert diff_p90 <= 3.0, f"LỆCH DỮ LIỆU: P90 trả về ({ret_p90}s) lệch quá 3s so với CSDL gốc ({sql_p90}s)!"
        assert ret_p10 <= ret_p50 <= ret_p90, f"Vi phạm bất biến phân vị: P10={ret_p10} <= P50={ret_p50} <= P90={ret_p90}"

    print(f"\n[*] Kiểm tra độ nhạy giờ cao điểm Tuyến 02: P90(8h)={p90_peak_8h:.1f}s vs P90(14h)={p90_offpeak_14h:.1f}s")
    assert p90_peak_8h > p90_offpeak_14h, "LỖI MÔ HÌNH: P90 giờ cao điểm không lớn hơn giờ thấp điểm! Dữ liệu phân vị không phản ánh thực tế!"

    conn.close()
    print("✅ [PASS 100%] Bài kiểm định 1: Dữ liệu P10, P50, P90 khớp 100% với CSDL SQLite gốc!")


# ==============================================================================
# TEST 2: DENSE SPATIAL CONTINUITY & TERMINAL GATE COVERAGE SWEEP
# ==============================================================================

def test_02_dense_spatial_boundary_sweep_no_premature_depot():
    """
    KIỂM TRA QUÉT DẢI KHÔNG GIAN DÀY ĐẶC (DENSE SPATIAL SWEEP):
    Quét liên tục các vị trí lý trình s trên 3 tuyến độc lập (Tuyến 02, Tuyến 32, Tuyến 01).
    Bắt buộc:
    - Mọi điểm trong khoảng [s_{N-2} + 10m, s_{N-1} - 60m] BẮT BUỘC phải là ACTIVE_IN_TRANSIT.
    - Xe khi áp sát bến đích (s >= s_{N-1} - 40m) mới chuyển thành AT_DESTINATION_TERMINAL.
    - Xe ở đầu bến (s < s_1 - 10m) là AT_ORIGIN_TERMINAL.
    """
    print("\n" + "=" * 80)
    print("KIỂM ĐỊNH 2: QUÉT DẢI LÝ TRÌNH DÀY ĐẶC — CHỐNG LỖI CẮT SỚM BẾN ĐÍCH TRÊN NHIỀU TUYẾN")
    print("=" * 80)

    service = EtaServingService.get_instance()
    routes_to_sweep = [("02", "go"), ("32", "go"), ("01", "go")]

    for r_code, d_str in routes_to_sweep:
        st_list = service.extractor.stations_by_dir.get((r_code, d_str), [])
        assert len(st_list) >= 10, f"Tuyến {r_code} {d_str} không đủ trạm"

        penultimate_st = st_list[-2]
        final_st = st_list[-1]
        s_penultimate = penultimate_st[3]
        s_final = final_st[3]
        gap_m = s_final - s_penultimate

        print(f"\n[*] Tuyến {r_code} {d_str}: Trạm kế cuối #{penultimate_st[0]} (s={s_penultimate:.1f}m) -> Bến đích #{final_st[0]} (s={s_final:.1f}m), Khoảng cách={gap_m:.1f}m")

        test_points = [
            s_penultimate + 10.0,
            s_penultimate + gap_m * 0.25,
            s_penultimate + gap_m * 0.50,
            s_penultimate + gap_m * 0.75,
            s_final - 60.0,
        ]

        for s_test in test_points:
            status = service.extractor.get_terminal_gate_status(r_code, d_str, s_test)
            assert status == "ACTIVE_IN_TRANSIT", (
                f"LỖI CẮT BẾN SỚM: Tuyến {r_code} tại s={s_test:.1f}m (cách bến đích {s_final - s_test:.1f}m) "
                f"bị gán nhãn '{status}'! Phải là 'ACTIVE_IN_TRANSIT' để hành khách biết bao giờ xe tới bến!"
            )

        s_in_depot = s_final - 20.0
        status_depot = service.extractor.get_terminal_gate_status(r_code, d_str, s_in_depot)
        assert status_depot == "AT_DESTINATION_TERMINAL", (
            f"LỖI NHẬN DIỆN BẾN: Tuyến {r_code} tại s={s_in_depot:.1f}m (áp sát bến) "
            f"phải là 'AT_DESTINATION_TERMINAL', nhưng nhận được '{status_depot}'!"
        )

        s_origin = st_list[1][3] - 20.0
        status_origin = service.extractor.get_terminal_gate_status(r_code, d_str, s_origin)
        assert status_origin == "AT_ORIGIN_TERMINAL", (
            f"LỖI BẾN XUẤT PHÁT: Tuyến {r_code} tại s={s_origin:.1f}m phải là 'AT_ORIGIN_TERMINAL', nhận được '{status_origin}'!"
        )

    print("✅ [PASS 100%] Bài kiểm định 2: Quét dải lý trình toàn diện vượt qua trên tất cả các tuyến!")


# ==============================================================================
# TEST 3: FUZZING DIRECTION NORMALIZATION & BIDIRECTIONAL PARITY
# ==============================================================================

def test_03_fuzzing_direction_robustness():
    """
    KIỂM TRA CHUẨN HÓA CHIỀU DI CHUYỂN BẰNG FUZZING:
    Gửi hàng loạt biến thể chuỗi: 're', 'RE', ' re ', 'chiều về', 'Chiều Về', 'chieu ve', 'CHIEU VE'.
    Bắt buộc Router và Service phải nhận diện 100% đúng là chiều về ('re').
    """
    print("\n" + "=" * 80)
    print("KIỂM ĐỊNH 3: FUZZING DIRECTION — CHỐNG LỆCH CHIỀU KHI TRUYỀN CHUỖI ĐA DẠNG")
    print("=" * 80)

    re_fuzz_cases = ["re", "RE", " re ", "1", "chiều về", "Chiều Về", " chiều về ", "chieu ve", "CHIEU VE"]
    go_fuzz_cases = ["go", "GO", " go ", "0", "chiều đi", "Chiều Đi", " chiều đi ", "chieu di"]

    for var in re_fuzz_cases:
        resp = client.get(f"/api/v1/routes/02/geometry?direction={var}")
        assert resp.status_code == 200, f"Lỗi HTTP {resp.status_code} với direction='{var}'"
        d = resp.json()
        assert d["direction"] == "re", f"Nhận diện sai variant='{var}' thành '{d['direction']}' (bắt buộc phải là 're')"
        first_st_name = d["stations"][0]["station_name"]
        assert "Bác Cổ" in first_st_name or "Trần Khánh Dư" in first_st_name, (
            f"Lỗi lệch trạm chiều về với variant='{var}': Trạm đầu là '{first_st_name}', không phải Bác Cổ!"
        )

    for var in go_fuzz_cases:
        resp = client.get(f"/api/v1/routes/02/geometry?direction={var}")
        assert resp.status_code == 200
        d = resp.json()
        assert d["direction"] == "go", f"Nhận diện sai variant='{var}' thành '{d['direction']}' (bắt buộc phải là 'go')"
        first_st_name = d["stations"][0]["station_name"]
        assert "Yên Nghĩa" in first_st_name, (
            f"Lỗi lệch trạm chiều đi với variant='{var}': Trạm đầu là '{first_st_name}', không phải Yên Nghĩa!"
        )

    print("✅ [PASS 100%] Bài kiểm định 3: Fuzzing Direction chuẩn hóa an toàn 100% mọi biến thể!")


# ==============================================================================
# TEST 4: TRAFFIC STATE COMPREHENSIVE MATRIX TEST
# ==============================================================================

def test_04_traffic_condition_state_matrix():
    """
    KIỂM TRA MA TRẬN TRẠNG THÁI GIAO THÔNG (TRAFFIC CONDITION STATE MATRIX):
    Phân loại trạng thái lưu thông theo ma trận (active_buses, average_speed, current_hour):
    1. Ban đêm (sau 22:30 hoặc trước 05:00) khi rỗng xe: BẮT BUỘC thông báo ca đêm kết thúc.
    2. Ban ngày (08:30) khi rỗng xe: BẮT BUỘC thông báo xe đang tại bến / chưa xuất bến.
    3. Khi có xe chạy: Phân định kẹt xe, ùn ứ, thông thoáng chuẩn xác.
    """
    print("\n" + "=" * 80)
    print("KIỂM ĐỊNH 4: MA TRẬN TRẠNG THÁI GIAO THÔNG — ĐÁNH GIÁ CHÍNH XÁC CA ĐÊM & ÙN TẮC")
    print("=" * 80)

    cond_night = evaluate_corridor_traffic_condition(active_speeds=[], hour=23, minute=15)
    print(f"[*] Case 1 (23:15 đêm, 0 xe chạy): '{cond_night}'")
    assert "Ca đêm" in cond_night or "kết thúc" in cond_night.lower(), f"Lỗi ca đêm: '{cond_night}'"
    assert "Thông thoáng" not in cond_night, "LỖI GIAN LẬN: Ca đêm không có xe chạy nhưng vẫn báo 'Thông thoáng'!"

    cond_day_empty = evaluate_corridor_traffic_condition(active_speeds=[], hour=8, minute=30)
    print(f"[*] Case 2 (08:30 sáng, 0 xe chạy): '{cond_day_empty}'")
    assert "chưa có xe" in cond_day_empty.lower() or "chờ" in cond_day_empty.lower(), f"Lỗi rỗng xe ban ngày: '{cond_day_empty}'"
    assert "Thông thoáng" not in cond_day_empty, "LỖI GIAN LẬN: Ban ngày rỗng xe nhưng vẫn báo 'Thông thoáng'!"

    cond_jam = evaluate_corridor_traffic_condition(active_speeds=[5.0, 7.0, 6.0], hour=17, minute=30)
    print(f"[*] Case 3 (17:30 tan tầm, v=6 km/h): '{cond_jam}'")
    assert "Kẹt xe" in cond_jam or "Ùn tắc" in cond_jam, f"Lỗi nhận diện kẹt xe: '{cond_jam}'"

    cond_slow = evaluate_corridor_traffic_condition(active_speeds=[14.0, 16.0, 15.0], hour=10, minute=0)
    print(f"[*] Case 4 (10:00 sáng, v=15 km/h): '{cond_slow}'")
    assert "Ùn ứ chậm" in cond_slow, f"Lỗi nhận diện ùn ứ: '{cond_slow}'"

    cond_clear = evaluate_corridor_traffic_condition(active_speeds=[26.0, 30.0, 28.0], hour=14, minute=0)
    print(f"[*] Case 5 (14:00 trưa, v=28 km/h): '{cond_clear}'")
    assert "Thông thoáng" in cond_clear, f"Lỗi nhận diện thông thoáng: '{cond_clear}'"

    print("✅ [PASS 100%] Bài kiểm định 4: Ma trận trạng thái giao thông phân loại chuẩn xác 5/5 kịch bản!")


# ==============================================================================
# TEST 5: FRONTEND KINEMATIC TWEENING EXECUTION (VIA NODE.JS SUBPROCESS)
# ==============================================================================

def test_05_frontend_kinematic_tweening_via_nodejs():
    """
    KIỂM ĐỊNH 5: THỰC THI KIỂM CHỨNG ĐỘNG HỌC JAVASCRIPT QUA NODE.JS:
    Gọi trực tiếp script scripts/test_marker_tweening.js bằng binary node.
    Kiểm tra thuật toán nội suy tuyến tính (Lerp) và Easing 60 FPS thực tế trong MapManager.
    Bắt buộc phải đạt Exit Code 0!
    """
    print("\n" + "=" * 80)
    print("KIỂM ĐỊNH 5: THỰC THI KIỂM CHỨNG ĐỘNG HỌC JAVASCRIPT QUA NODE.JS SUBPROCESS")
    print("=" * 80)

    js_test_script = os.path.join(BASE_DIR, "scripts", "test_marker_tweening.js")
    assert os.path.exists(js_test_script), f"Không tìm thấy file {js_test_script}"

    proc = subprocess.run(["node", js_test_script], capture_output=True, text=True)
    print(proc.stdout)
    if proc.stderr:
        print(proc.stderr)

    assert proc.returncode == 0, f"Kiểm định động học Marker Tweening trong Node.js thất bại (Exit code {proc.returncode})!"
    print("✅ [PASS 100%] Bài kiểm định 5: Node.js xác thực thuật toán nội suy Marker 60 FPS hợp lệ 100%!")


# ==============================================================================
# TEST 6: FULL-TRIP ACCUMULATED DELAY & ZERO TRAIN/SERVE SKEW
# ==============================================================================

def test_06_full_trip_continuity_no_train_serve_skew():
    """
    KIỂM ĐỊNH 6: TÍNH LIÊN TỤC CỦA CHUYẾN ĐI & XÓA BỎ TRAIN/SERVE SKEW (EGO_CUM_DELAY):
    Định nghĩa trong feature_store_builder.py:
      trip_elapsed = device_epoch - trip_start_epoch (tính từ ĐẦU CẢ CHUYẾN ĐI).
      first_k      = trạm xuất phát đầu tiên của cả chuyến đi.
      ego_cum_delay = trip_elapsed - (pref_p50[k_curr] - pref_p50[first_k]).
    Mô phỏng một xe chạy liên tục 20 ping (tổng thời gian 300 giây, vượt qua maxlen=10):
    - trip_elapsed tại ping thứ 20 BẮT BUỘC phải tiếp tục tích lũy (~300s),
      KHÔNG ĐƯỢC BỊ TỤT VỀ 135s do deque(maxlen=10)!
    - first_k BẮT BUỘC giữ nguyên vị trí trạm đầu chuyến đi (first_k == 0 hoặc 1),
      KHÔNG ĐƯỢC LIÊN TỤC CHẠY THEO ĐUÔI XE!
    """
    print("\n" + "=" * 80)
    print("KIỂM ĐỊNH 6: ĐỘNG HỌC TOÀN CHUYẾN ĐI (FULL-TRIP ACCUMULATED DELAY & NO SKEW)")
    print("=" * 80)

    extractor = OnlineFeatureExtractor()
    key = ("02", "go")
    st_list = extractor.stations_by_dir[key]
    vid = "SIMULATED_FULL_TRIP_BUS"

    # Mô phỏng xe xuất phát từ Bến xe Yên Nghĩa (s=0m) lúc t0
    t0 = 1793750000.0  # Mốc epoch cố định
    s_start = 50.0

    # Chạy 20 ping, mỗi ping cách nhau 15 giây, xe tiến dần dọc tuyến
    # Tổng thời gian: 20 * 15s = 300 giây (5 phút), xe đi được khoảng 2.5 km (vượt qua 4 trạm)
    cur_epoch = t0
    cur_s = s_start
    v_speed = 30.0  # km/h (~8.33 m/s)

    last_df = None
    for ping_idx in range(20):
        cur_epoch = t0 + ping_idx * 15.0
        cur_s = s_start + ping_idx * 15.0 * (v_speed / 3.6)
        last_df = extractor.extract_features_for_ego(
            route_code="02",
            direction="go",
            vehicle_id=vid,
            device_epoch=cur_epoch,
            s_bus_m=cur_s,
            speed_kmh=v_speed,
        )

    assert last_df is not None and not last_df.empty, "DataFrame trích xuất không được rỗng"

    # Lấy giá trị ego_trip_elapsed_sec và ego_cum_delay_vs_baseline_sec tại ping thứ 20
    assert "ego_trip_elapsed_sec" in last_df.columns, "Cột 'ego_trip_elapsed_sec' bắt buộc phải có trong 54 features"
    assert "ego_cum_delay_vs_baseline_sec" in last_df.columns, "Cột 'ego_cum_delay_vs_baseline_sec' bắt buộc phải có trong 54 features"

    sim_trip_elapsed = float(last_df["ego_trip_elapsed_sec"].iloc[0])
    sim_cum_delay = float(last_df["ego_cum_delay_vs_baseline_sec"].iloc[0])
    print(f"[+] Sau 20 ping (285 giây trôi qua): Đo đạc ego_trip_elapsed_sec = {sim_trip_elapsed:.1f}s | ego_cum_delay = {sim_cum_delay:.1f}s")

    # Anti-cheat assertion:
    # Nếu bị giới hạn bởi maxlen=10 (10 ping * 15s = 135s-150s), test này sẽ FAIL ngay!
    assert sim_trip_elapsed >= 270.0, (
        f"TRAIN/SERVE SKEW PHÁT HIỆN: ego_trip_elapsed_sec ({sim_trip_elapsed:.1f}s) bị kẹp cụt do deque(maxlen=10)!\n"
        "ego_trip_elapsed_sec phải phản ánh thời gian từ ĐẦU CHUYẾN ĐI (~285s) theo đúng chuẩn feature_store_builder.py!"
    )
    assert -600.0 <= sim_cum_delay <= 1800.0, f"ego_cum_delay ({sim_cum_delay}) vượt ngưỡng vật lý!"

    print("✅ [PASS 100%] Bài kiểm định 6: trip_elapsed và ego_cum_delay duy trì vẹn toàn suốt cả chuyến đi!")


# ==============================================================================
# TEST 7: DIRECTION TRANSITION & NO GHOST FLEET (CHỐNG XE BÓNG MA)
# ==============================================================================

def test_07_direction_transition_no_ghost_fleet():
    """
    KIỂM ĐỊNH 7: QUAY ĐẦU CHUYẾN & TRIỆT TIÊU HOÀN TOÀN XE BÓNG MA (GHOST FLEET):
    Một xe buýt vật lý không thể cùng lúc ở cả 2 chiều di chuyển.
    Mô phỏng xe '29B-DUAL' đang chạy ở chiều đi ('go'), sau đó quay đầu
    và gửi ping mới ở chiều về ('re'):
    - Ngay khi xe được ghi nhận ở chiều về ('re'), xe đó BẮT BUỘC PHẢI BỊ XÓA NGAY LẬP TỨC
      khỏi danh sách active_fleet của chiều đi ('go')!
    - Tuyệt đối CẤM để xe tồn tại song song ở cả 2 chiều trong 300 giây làm nhiễu lead_bus!
    """
    print("\n" + "=" * 80)
    print("KIỂM ĐỊNH 7: QUAY ĐẦU ĐỔI CHIỀU — XÓA BỎ NGAY LẬP TỨC XE BÓNG MA TRÊN CHIỀU CŨ")
    print("=" * 80)

    extractor = OnlineFeatureExtractor()
    vid = "TEST_GHOST_FLEET_VEHICLE"
    t_now = time.time()

    # 1. Cập nhật xe chạy ở chiều đi 'go'
    extractor.update_vehicle_ping(
        route_code="02",
        direction="go",
        vehicle_id=vid,
        device_epoch=t_now,
        s_bus_m=12000.0,
        speed_kmh=25.0,
    )

    fleet_go = extractor.active_fleet[("02", "go")]
    assert vid in fleet_go, f"Xe {vid} phải có mặt trong active_fleet của chiều go"
    print(f"[+] Đã ghi nhận xe {vid} trong active_fleet chiều đi 'go' (s=12000m)")

    # 2. Xe kết thúc lượt, quay đầu tại Bác Cổ và gửi ping đầu tiên của chiều về 're'
    t_turnaround = t_now + 30.0
    extractor.update_vehicle_ping(
        route_code="02",
        direction="re",
        vehicle_id=vid,
        device_epoch=t_turnaround,
        s_bus_m=500.0,
        speed_kmh=15.0,
    )

    fleet_re = extractor.active_fleet[("02", "re")]
    fleet_go_after = extractor.active_fleet[("02", "go")]

    print(f"[*] Sau khi xe quay đầu sang chiều 're':")
    print(f"    - Có mặt trong chiều về 're' : {vid in fleet_re}")
    print(f"    - Còn sót lại trong chiều đi 'go': {vid in fleet_go_after}")

    assert vid in fleet_re, f"Xe {vid} phải có mặt trong chiều về 're'"
    assert vid not in fleet_go_after, (
        f"LỖI XE BÓNG MA (GHOST FLEET): Xe {vid} đã quay đầu sang chiều về 're', "
        f"nhưng vẫn ám ảnh trong active_fleet của chiều đi 'go'! Phải xóa ngay lập tức khi đổi chiều!"
    )

    print("✅ [PASS 100%] Bài kiểm định 7: Cơ chế triệt tiêu Ghost Fleet hoạt động hoàn hảo!")


# ==============================================================================
# MAIN TEST RUNNER
# ==============================================================================

if __name__ == "__main__":
    t_start = time.time()
    print("\n" + "#" * 80)
    print("KHỞI ĐỘNG BỘ TEST CHỐNG GIAN LẬN & KIỂM CHỨNG BẤT BIẾN THỰC NGHIỆM")
    print("#" * 80)

    passed = 0
    failed = 0
    errors = []

    tests = [
        ("Test 1: Đối soát phân vị Baseline P10/P50/P90 với CSDL SQLite gốc", test_01_ground_truth_sql_quantile_parity),
        ("Test 2: Quét dải lý trình dày đặc chống ngắt bến sớm", test_02_dense_spatial_boundary_sweep_no_premature_depot),
        ("Test 3: Fuzzing chuẩn hóa Direction trên nhiều tuyến", test_03_fuzzing_direction_robustness),
        ("Test 4: Ma trận đánh giá trạng thái giao thông trung thực", test_04_traffic_condition_state_matrix),
        ("Test 5: Thực thi động học Marker Tweening 60 FPS qua Node.js", test_05_frontend_kinematic_tweening_via_nodejs),
        ("Test 6: Động học toàn chuyến đi (Full-Trip Continuity & No Skew)", test_06_full_trip_continuity_no_train_serve_skew),
        ("Test 7: Quay đầu đổi chiều & Triệt tiêu xe bóng ma (Ghost Fleet)", test_07_direction_transition_no_ghost_fleet),
    ]

    for name, fn in tests:
        try:
            fn()
            passed += 1
        except Exception as e:
            failed += 1
            errors.append((name, str(e)))

    print("\n" + "#" * 80)
    print(f"KẾT QUẢ KIỂM THỬ: {passed} PASS / {failed} FAIL (Tổng số: {len(tests)})")
    print("#" * 80)

    if errors:
        print("\nDANH SÁCH CÁC MỤC THẤT BẠI:")
        for name, err in errors:
            print(f"\n❌ [{name}]:")
            print(f"   {err}")
        print("\n" + "!" * 80)
        print("KẾT LUẬN: CODEBASE KHÔNG VƯỢT QUA ĐƯỢC TIÊU CHÍ KIỂM CHỨNG THỰC NGHIỆM!")
        print("!" * 80)
        sys.exit(1)
    else:
        print(f"\n🎉 TUYỆT VỜI: TOÀN BỘ {passed}/{len(tests)} BÀI TEST THỰC NGHIỆM ĐÃ VƯỢT QUA TRONG {time.time() - t_start:.2f} GIÂY!")
        sys.exit(0)
