# Đề cương Chi tiết Nội dung Báo cáo Kỹ thuật Đầy đủ (`report_full.pdf`)

> **Phạm vi:** Tài liệu này là khung cấu trúc chuẩn cho **Bản Báo cáo Đầy đủ** ([report_full.md](file:///z:/Desktop/Bus_tracking/report/report_full.md) $\to$ `report_full.pdf`), tổ chức thống nhất theo 3 tầng kiến trúc Lambda (**Batch Layer**, **Speed Layer**, **Serving Layer**), đặt sơ đồ tổng hợp ở cuối mỗi tầng và tách biệt chi tiết cài đặt khỏi tiêu đề chương.
> *(Bản Rút gọn `report_short.pdf` sẽ cô đọng các kết quả cốt lõi trong giới hạn $\le 5$ trang.)*

---

## Chương 1. Tổng quan Bài toán và Kiến trúc Hệ thống
- **1.1. Bối cảnh và Yêu cầu Thực tiễn tại Hà Nội:**
  - Nhược điểm dữ liệu GPS BusMap đơn nguồn: độ trễ `15–60s+`, mất dấu xe giữa tuyến, nhiễu vận tốc hộp đen, và `cold-start` 3–5 phút.
  - Bài toán đặt ra: xử lý dữ liệu lịch sử quy mô lớn (Bronze–Silver–Gold) kết hợp dự báo ETA thời gian thực chính xác, ổn định và minh bạch trạng thái.
- **1.2. Kiến trúc Lambda 3 Tầng:**
  - **Batch Layer:** Thu thập 24/7 $\to$ HDFS Bronze/Silver/Gold $\to$ SQLite + huấn luyện `causal-eta.v1`.
  - **Speed Layer:** `SpeedLayerPoller` chu kỳ `45s` làm ấm RAM + đồng bộ snapshot TomTom `300s` (không lọc trạm, không tính ETA).
  - **Serving Layer:** Backend FastAPI (`BusMapServingService`) suy luận ETA + Frontend Web (`/`, `/debug`) và script vận hành.
- **1.3. Sơ đồ Tổng hợp Kiến trúc Hệ thống:**
  - Sơ đồ kiến trúc tổng quan phân tách **Luồng Dữ liệu** và **Luồng Logic** xuyên suốt 3 tầng.

---

## Chương 2. Batch Layer
- **2.1. Thu thập Dữ liệu Đa nguồn:**
  - Cloud Crawler (`crawl_bus.yml`, phiên `540s`, chu kỳ `75s`, micro-batch `18` xe, raw SSL socket `4.2s`).
  - TomTom Incidents (`750s`/lần, quota `<= 80/ngày`, `<= 2500/tháng`, đẩy `raw_data/latest_incidents.json` lên HF).
  - Làm mới danh mục đầu ngày trên 49 tuyến (`catalog_refresher.py`).
- **2.2. Làm sạch Động học và Phân đoạn Chuyến đi:**
  - Bảng tham số SSOT (`HANOI_BBOX`, `GPS_DRIFT_JUMP`, `TERMINAL_STATIONARY_TOL_M = 15.0m`, `MAX_CONTINUOUS_GAP_SEC = 300.0s`, `MAX_BRIDGEABLE_DETOUR_GAP_SEC = 1800.0s`, `MAX_BACKWARD_RESET_M = 200.0m`, `trim_terminal_stationary_ends()`).
- **2.3. Chiếu Không gian 1D Frenet và Mô hình Viterbi HMM:**
  - `ShapeProjectionModel` (`(lat, lon)` $\to$ `(s_bus_m, cross_track_m)`), `RouteHMM` (`BATCH_HMM_HORIZON_SEC = 300.0s`, `MAX_CORRIDOR_CROSS_TRACK_M = 35.0m`).
- **2.4. Lưu trữ HDFS và Medallion Lakehouse:**
  - Bronze (`/bus-eta/v1/bronze/hf_raw`, SHA-256) $\to$ Silver (Spark P2 Parquet Snappy) $\to$ Gold (`agg_segment_travel_times`, `MIN_SAMPLES_FOR_BASELINE = 5`, `MAX_SEGMENT_TRAVEL_TIME_SEC = 1800.0s`) $\to$ SQLite (`hanoi_bus_system.db`).
- **2.5. Sơ đồ Tổng hợp Batch Layer:**
  - Liên kết toàn bộ luồng từ mục `2.1–2.4`.

---

## Chương 3. Speed Layer
- **3.1. Thực nghiệm Đối chiếu BusMap `route_query` và `per_vehicle`:**
  - Đối chiếu trên 5 tuyến (`02, 27, 32, 01, E03`): sai lệch `0.0m / 0.0s`; `17/17` xe vắng mặt đều ngoài hành trình hoặc ping đóng băng.
  - Tập tuyến giao thoa: `48` tuyến Baseline (`756` xe), gồm `31` tuyến có TimBus (`495` xe, `65.5%`) và `17` tuyến BusMap-only (`261` xe).
- **3.2. Bộ thu thập Nền 45s và Bổ khuyết Dữ liệu Thời gian thực:**
  - Phase 1 (BusMap `45s`), Phase 2 (TimBus Gap-Filler: `2` worker, `stagger = 0.15s`, `anchors[:1]`, `age >= 60s`, bỏ qua xe Serving focus `< 45s`), Phase 3 (TomTom HF Relay `300s`).
  - Ngừng truy vấn ngoài giờ vận hành (`22:30 – 04:45` giờ Hà Nội).
- **3.3. Cơ chế Phân loại 4 Trạng thái và Circuit Breaker:**
  - `RECOVERED_LIVE` (`0s`), `TERMINAL_OR_DEPOT_PARKED` (`180s`), `ON_CORRIDOR_GAP` (`45s`), `UPSTREAM_ERROR` (Circuit Breaker `90s` khi `error_streak >= 3`).
- **3.4. Đồng bộ Đa luồng và Bảo toàn Trạng thái RAM:**
  - `--workers 1`, `threading.RLock`, `_causal_lock`, `_tb_lock`.
- **3.5. Sơ đồ Tổng hợp Speed Layer:**
  - Liên kết vòng đời xử lý từ mục `3.1–3.4`.

---

## Chương 4. Serving Layer
- **4.1. Luồng Phục vụ Truy vấn và Lọc Phương tiện theo Trạm:**
  - Đọc Warm RAM + BusMap cache `15s` + TimBus Focus `5s`; lọc trạm (`cross_track <= 35.0m`, hướng, `s_now <= s_target`, Pass Guard `_passed_station_plates`, `MacroSpeedTracker`).
- **4.2. Chiếu Hình học và Nạp Sự cố TomTom Trực tuyến:**
  - TTL `2700s`, `project_directed_point` (`cos_theta >= 0.5`), `split_matched_vertices_into_runs`, scale `delay_seconds`, trả `polylines` trên `RouteIncidentDTO`.
- **4.3. Trích xuất 40 Đặc trưng Nhân quả Thời gian thực:**
  - Nguyên tắc tiền tố quá khứ (`MAX_POSITION_AGE = 90.0s`, `MAX_FLEET_SKEW = 45.0s`), bảng đủ 6 nhóm (40 feature).
- **4.4. Mô hình Residual XGBoost (`causal-eta.v1`):**
  - `XGBRegressor` (`reg:absoluteerror`, `max_depth = 6`, `1200` cây, `best_iteration = 1199`, `QuantileDMatrix` CUDA), $\text{ETA}_{P50} = \max(5.0, \text{baseline\_p50} + \delta)$.
- **4.5. Chính sách Ổn định và Cửa sổ An toàn ETA:**
  - Proximity cap (`80m / 120m / 2.5 m/s / 15s`), `delay_seconds`, phân loại `THONG_THOANG` / `BINH_THUONG` / `UN_TAC`, LINEX buffer ($\alpha=0.60, \beta=0.5, \text{HEARTBEAT}=15.0\text{s}, \gamma=0.04$, $\kappa(d)$ trên $[30\text{m}, 150\text{m}]$, trần `180.0s`) và `SafeWindowDTO`.
- **4.6. Cơ chế Phản hồi Trạng thái Tường minh:**
  - `upstream_status`, `timbus_status`, `fallback_reason`, tách `ping_time` vs `busmap_updated_at`, `/api/health`.
- **4.7. Giao diện Web (`/`, `/debug`) và Vận hành Hệ thống:**
  - Trang hành khách (`/`), Debug Operations Console (`/debug` với 4 tab gồm *Sự cố TomTom*), và `scripts/start_demo_bg` / `stop_demo_bg`.
- **4.8. Sơ đồ Tổng hợp Serving Layer:**
  - Liên kết toàn bộ luồng Backend suy luận và Frontend API từ mục `4.1–4.7`.

---

## Chương 5. Benchmark và Kiểm chứng
- **5.1. Benchmark Speed Layer (2 chu kỳ 45s trực tiếp):**
  - Cycle 1 (`44.1s`) và Cycle 2 (`33.8s`, `eff_stale90: 4 -> 2`, `99.5% < 90s`).
- **5.2. Soak Test Vận hành Liên tục (~8 phút):**
  - `32` ticks, `474s`, `4,365` gói tin, `0` lỗi logic, `P50=0.6s`, `P90=0.8–1.0s`.
- **5.3. Benchmark Out-of-Time 7 Ngày:**
  - `2026-11-13` → `2026-11-19` (`8,306,295` mẫu test, `17,866,649` mẫu train): Overall MAE `141.28s`, `has_incident` `177.74s` (`-29.40s`), `by_horizon`, Feature Importance TomTom.
- **5.4. Kiểm thử Tự động và Trình duyệt Thực tế:**
  - `pytest` (`200 passed, 12 skipped, 0 failed`), Chrome DevTools (`/`, `/debug`), soak test API 8 phút.

---

## Chương 6. Kết luận
- **6.1. Kết quả Đạt được**
- **6.2. Tổng kết Đóng góp**
