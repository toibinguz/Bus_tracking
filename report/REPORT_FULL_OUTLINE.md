# Đề cương Chi tiết Nội dung Bản Báo cáo Đầy đủ (`report_full.pdf`)

> **Phạm vi:** Tài liệu này liệt kê đầy đủ toàn bộ nội dung, công thức, tham số SSOT, kiến trúc 3 tầng, sơ đồ và số liệu thực nghiệm sẽ được đưa vào **Bản Đầy đủ** (`report/report_full.tex` $\to$ `report/report_full.pdf`) — đảm bảo *không thiếu chi tiết kỹ thuật nào nhưng không viết thừa*.
> *(Bản Rút gọn `report/report_short.pdf` sẽ cô đọng các mục cốt lõi này trong giới hạn $\le 5$ trang.)*

---

## Chương 1. Tổng quan Bài toán & Kiến trúc Hệ thống (Lambda 3 Tầng)
- **1.1. Bối cảnh & Yêu cầu Thực tế tại Hà Nội:**
  - Nhược điểm của dữ liệu GPS BusMap công khai đơn nguồn: độ trễ cập nhật 15–60s+, biến mất xe tạm thời giữa tuyến, nhiễu vận tốc tức thời hộp đen và cold-start 3–5 phút khi mở ứng dụng.
  - Bài toán đặt ra: vừa lưu trữ/xử lý dữ liệu lịch sử quy mô lớn (Bronze–Silver–Gold), vừa phục vụ dự báo ETA thời gian thực chính xác, ổn định và minh bạch trạng thái cho hành khách lẫn kỹ sư vận hành.
- **1.2. Kiến trúc Lambda 3 Tầng (Batch Layer – Speed Layer – Serving Layer):**
  - **Batch Layer:** Thu thập 24/7 $\to$ HDFS Bronze/Silver/Gold $\to$ SQLite nền nhẹ + huấn luyện `causal-eta.v1`.
  - **Speed Layer:** `SpeedLayerPoller` chạy nền chu kỳ `45s` thu thập & lưu ấm RAM (`CausalFeatures`, `RouteProjectionTracker`, `RouteHMM`, `_tb_last_valid`) và đồng bộ TomTom live snapshot từ HF (`300s`) — không lọc trạm, không tính ETA.
  - **Serving Layer:** `BusMapServingService` (FastAPI) đọc RAM đã làm ấm, gọi BusMap `route_query` + TimBus Focus `5s`, thực hiện toàn bộ lọc trạm, suy luận ML và chính sách ổn định `eta_policy`.
  - **Sơ đồ kiến trúc tổng quan & phân tách Luồng Dữ liệu / Luồng Logic** của cả 3 tầng.

---

## Chương 2. Module 1 & 2 — Thu thập, Tiền xử lý & Medallion Lakehouse (Batch Layer)
- **2.1. Thu thập Dữ liệu Đa nguồn (`step_1_1`):**
  - Cloud Crawler 24/7 trên GitHub Actions (`crawl_bus.yml`): phiên `540s`, vòng lặp `75s`, micro-batch `18` xe, raw SSL socket (`socket_client.py`, DNS cache `_IP_CACHE_LOCK`, timeout `4.2s`).
  - TomTom Incidents (`incident_client.py`): chỉ lấy sự cố, giới hạn quota `80/ngày` và `2500/tháng` (`TOMTOM_INCIDENT_INTERVAL_SEC = 750s`, ~12.5 phút/lần), đẩy ngay `raw_data/latest_incidents.json` lên HF (`push_latest_incidents_to_hf`) để Speed Layer dùng chung 1 lần gọi API.
  - Làm mới danh mục đầu ngày (`catalog_refresher.py`): quét `route_bus_gps` toàn bộ 49 tuyến, cập nhật `routeId` khi xe đổi tuyến, chỉ xóa xe khi `status == "ERROR"`.
- **2.2. Làm sạch Động học & Tách chuyến (`step_1_3`):**
  - Bảng tham số SSOT (`config/system_config.py`):
    - `HANOI_BBOX`: lat `19.50..22.50`, lon `104.50..107.50`.
    - Phát hiện nhảy cóc (`GPS_DRIFT_JUMP`): đồng thời `dist >= 250.0m` và `v_calc > 80.0 km/h`; cô lập `OUT_OF_BOUNDS` và drift không cho ghi vào `kinematic_cache`.
    - `TERMINAL_STATIONARY_TOL_M = 15.0m`, phân loại `IDLE_DEPOT`, `ACTIVE_VALID`, `STALE_PING`.
  - Tách chuyến (`trip_segmenter.py`): `MAX_CONTINUOUS_GAP_SEC = 300.0s`, `MAX_BRIDGEABLE_DETOUR_GAP_SEC = 1800.0s`, `MAX_BACKWARD_RESET_M = 200.0m`, `trim_terminal_stationary_ends()`.
- **2.3. Chiếu Không gian 1D Frenet & Viterbi HMM (`step_1_4`):**
  - `ShapeProjectionModel` ánh xạ `(lat, lon)` $\to$ `(s_bus_m, cross_track_m)`.
  - `RouteHMM` (dùng chung Batch `BATCH_HMM_HORIZON_SEC = 300.0s` và Speed/Serving): emission Gaussian theo `cross_track` + transition theo hướng tiếp tuyến và tiến độ $\Delta s$; ngưỡng xuất Silver `MAX_CORRIDOR_CROSS_TRACK_M = 35.0m`.
- **2.4. Lưu trữ HDFS & Medallion Lakehouse (`Module 2`):**
  - **Bronze (`step_2_4`):** `/bus-eta/v1/bronze/hf_raw`, bất biến, kiểm chứng SHA-256 (`receipt.py`, `spool.py`).
  - **Silver (`step_2_4`, `step_2_2`):** Spark P2 (`p2_transform.py`) & Parquet Snappy (`route_projected_telemetry`, `fact_route_tomtom_incidents`).
  - **Gold (`step_3_1`, `step_2_4`):** Ma trận thời gian di chuyển lịch sử `agg_segment_travel_times` (`p10`, `p50`, `p90`, `mean`, `std` theo `(route_id, direction, segment_idx, day_type, hour_slot)`, `MIN_SAMPLES_FOR_BASELINE = 5`, `MAX_SEGMENT_TRAVEL_TIME_SEC = 1800.0s`) và release snapshot (`eta_snapshot.py`).
  - **SQLite (`hanoi_bus_system.db`, `step_2_1`):** Nền nhẹ chứa GTFS chuẩn (`canonical_routes`, `canonical_shapes`, `canonical_stations`) và bảng hứng Gold Baseline cho phục vụ độ trễ thấp.

---

## Chương 3. Speed Layer — Poller 45s, Phân loại & Chống Cold-Start
- **3.1. Cơ sở Thiết kế từ Thực nghiệm BusMap `route_query` vs `per_vehicle`:**
  - Đối chiếu trực tiếp trên 5 tuyến (`02, 27, 32, 01, E03`): độ lệch `0.0m` / `0.0s`; `17/17` xe vắng mặt trong `route_query` đều là xe ngoài hành trình (`curr_st=0, next_st=0`, `ct = 254.9..4,059.4m`) hoặc ping đóng băng (`29,361..109,161s`).
  - Kết luận: Cả Speed Layer và Serving Layer đều thống nhất dùng BusMap `route_bus_gps` (route-query).
  - Tập tuyến giao thoa: `48` tuyến Baseline (`756` xe), trong đó `31` tuyến hỗ trợ TimBus (`495` xe, `65.5%`) và `17` tuyến BusMap-only (`261` xe).
- **3.2. Kiến trúc `SpeedLayerPoller` (`speed_poller.py`):**
  - Chu kỳ `45s` quét Phase 1 (BusMap `route_bus_gps` 48 tuyến $\times$ 2 chiều) $\to$ gọi `ingest_speed_layer_vehicles` làm ấm `RouteProjectionTracker`, `RouteHMM` và `CausalFeatures`, kết hợp đồng bộ `raw_data/latest_incidents.json` từ HF (`300s`).
  - Phase 2 (TimBus Gap-Filler): `2` workers dàn trải (`stagger_delay_sec = 0.15s`), chỉ dùng `anchors[:1]` (`primary_anchor_sid`), kích hoạt cho xe `age >= 60s` hoặc biến mất giữa tuyến; tự động bỏ qua xe Serving Layer vừa focus `< 45s` trong `_tb_last_valid`.
  - **Đóng hoàn toàn ngoài giờ hoạt động (`22:30 – 04:45` giờ Hà Nội):** `is_operating_hours()` trả `False`, không gọi BusMap/TimBus ban đêm.
- **3.3. Cơ chế Phân loại 4 Trạng thái & Circuit Breaker:**
  - `RECOVERED_LIVE`: TimBus hit $\to$ nạp `_tb_last_valid` + `CausalFeatures`, `cooldown = 0s`, reset `error_streak`.
  - `TERMINAL_OR_DEPOT_PARKED`: Miss + `speed == 0` + (`ct > 35m` hoặc cách bến $\le 300\text{m}$) $\to$ `cooldown = 180s`.
  - `ON_CORRIDOR_GAP`: Miss dù đang bám tuyến (`ct <= 35m`, cách bến $> 300\text{m}$) $\to$ `cooldown = 45s`, ghi `gap_routes_top`.
  - `UPSTREAM_ERROR`: Timeout / lỗi mạng $\to$ tăng `error_streak`; nếu $\ge 3$ mở **Circuit Breaker `90s`** (`circuit_state = "OPEN"`).
- **3.4. An toàn Đa luồng (`--workers 1`):**
  - `threading.RLock` trong `CausalFeatures` (`causal_eta.py`) kết hợp `_causal_lock` và `_tb_lock` trong `BusMapServingService`.

---

## Chương 4. Serving Layer, Mô hình `causal-eta.v1` & Chính sách ETA
- **4.1. Luồng Phục vụ `BusMapServingService` (`serving_service.py`):**
  - Đọc RAM đã làm ấm từ Speed Layer + gọi BusMap `route_bus_gps` (`live_feed.py`, cache `15s`) + đồng bộ TimBus Focus `5s` (`_sync_route_both_directions`).
  - Lọc xe tại trạm (`_filter_station_vehicles` + `project_filter_extrapolate`): kiểm tra `cross_track <= 35m`, đúng chiều, `s_now <= s_target`, Pass Guard `_passed_station_plates` (chống hồi sinh xe đã qua trạm từ cache cũ), và làm mượt tốc độ vĩ mô `MacroSpeedTracker` ($\Delta s / \Delta t > 120\text{s}$).
- **4.2. Bộ 40 Đặc trưng Nhân quả `CausalFeatures` (`step_3_2`):**
  - Nguyên tắc tuyệt đối chỉ dùng tiền tố quan sát quá khứ (dùng chung 1 code path giữa replay train và serving inference), `MAX_POSITION_AGE = 90.0s`, `MAX_FLEET_SKEW = 45.0s`.
  - Liệt kê đủ 6 nhóm (40 biến): Tuyến & Thời gian (9), Hình học & Khoảng cách (7), Động học Ego (2), Thống kê Baseline (11), Đội xe cùng tuyến (7), và **Sự cố TomTom (4)**: `inc_ahead_total_delay_sec` *(monotone `+1`, chia tỷ lệ chồng lấp `ov_l / eff_inc_span`)*, `inc_dist_to_nearest_m`, `inc_ahead_jam_length_m`, `inc_info_age_sec` *(tuổi snapshot `t_cur - crawled_epoch`)*.
  - Chiếu sự cố đồng bộ Online = Offline: lọc `cos_theta >= 0.5` trước khi `argmin` (`ShapeProjectionModel.project_directed_point`) và gom run đơn điệu (`split_matched_vertices_into_runs`, TTL live `2700s`).
- **4.3. Mô hình Residual XGBoost (`causal-eta.v1`, `step_3_3` & `model_runtime.py`):**
  - Dự báo phần dư `delta = eta_actual - baseline_eta_p50_sec` bằng `XGBRegressor` (`reg:absoluteerror`, `max_depth = 6`, `1200` cây, `best_iteration = 1199`, huấn luyện streaming `xgb.QuantileDMatrix` trên GPU CUDA); tái dựng $\text{ETA}_{P50} = \max(5.0,\ \text{baseline\_p50} + \delta)$.
  - Phân tích điều kiện fallback (`predict_p50_with_reason`).
- **4.4. Chính sách Ổn định & Cửa sổ An toàn (`eta_policy.py`):**
  - Chặn trần tiệm cận khi 2 xe bám sát nhau (`compute_proximity_capped_etas`: `PROXIMITY_CAP_FULL_M = 80m`, `FADE_M = 120m`, `SPEED = 2.5 m/s`, `MARGIN = 15s`).
  - Công thức **Độ trễ (`delay_seconds`)**: $\Delta_{\text{delay}} = \max(0,\ \text{eta\_core\_p50} - \text{base\_rem\_p50})$, cờ `is_delayed` và phân loại `THONG_THOANG` / `BINH_THUONG` / `UN_TAC`.
  - Công thức **Độ đệm bất đối xứng LINEX (`buffer_seconds`)**:
    $$B = \min\Big(\text{MAX\_SAFE\_BUFFER\_CEILING\_SEC},\ \kappa(d_{\text{station}}) \cdot (\alpha\,\sigma_{\text{accum}} + \beta\,\text{HEARTBEAT} + \gamma\,\text{eta\_core\_p50})\Big)$$
    tạo 2 mốc: Lạc quan ($\text{eta\_core} - B$) và Bảo thủ ($\text{eta\_core} + B$), lượng tử hóa phút trần trong `SafeWindowDTO`.
- **4.5. Cơ chế Phản hồi Tường minh (Loại bỏ Silent Fallback):**
  - `upstream_status` (`ok | empty | upstream_error`) + `upstream_error` (`live_feed.py`).
  - `timbus_status` (`ok | partial_error | upstream_error | unsupported`) + `timbus_error` (`timbus_tracker.py`).
  - `fallback_reason` (`ok | cold_start_causal | model_unavailable | unknown_route | predict_error`).
  - Phân tách 2 mốc thời gian gói tin: `ping_time` (thời gian query TimBus) và `busmap_updated_at` (thời gian thiết bị GPS gốc của BusMap).
  - `/api/health` công bố `healthy` / `degraded`, `model_available` và snapshot đầy đủ của `SpeedLayerPoller`.

---

## Chương 5. Giao diện Web Demo (`/`, `/debug`) & Vận hành Trước Demo
- **5.1. Trang Hành khách Tối giản (`/`):**
  - Bản đồ Esri vệ tinh (`World_Imagery`), panel kéo dãn chiều rộng (`#panelResizer`, `280–680px`), thu gọn panel, bottom-sheet 3 mức trên mobile.
  - Ô tìm tuyến (`#routeCombobox`) và ô chọn/lọc trạm thu gọn (`#stationCombobox`) đặt phía trên vùng ETA để dành tối đa không gian cho thẻ ETA.
  - Click trạm $\to$ **tự động ghim ngay lập tức, không mở popup trên bản đồ**; làm nổi bật **xe gần trạm nhất** (thẻ hero + badge halo pulse trên bản đồ); hiển thị banner lỗi/dữ liệu cũ/ước tính nền tường minh.
- **5.2. Trang Debug Operations Console (`/debug`):**
  - Nền dark-slate tách biệt, chia 2 cột bản đồ Esri vệ tinh — bảng phân tích kéo dãn tỷ lệ (`#dbgSplitter`), **4 tab độc lập** không cuộn trang: *Trạm & ETA*, *Đoàn xe & Telemetry*, ***Sự cố TomTom*** (vẽ LineString theo mức độ, popup chi tiết, click dòng zoom tới sự cố), *Hệ thống & Poller* (hiển thị trạng thái `LIVE TOMTOM INCIDENTS (HF RELAY)`).
  - Hiển thị song song `TB query` và `BM thiết bị` (`busmap_updated_at`), highlight hàng xe gần nhất (`.is-leading`).
- **5.3. Script Khởi động Nền Trước Demo (`scripts/`):**
  - `start_demo_bg.ps1` / `.bat` và `stop_demo_bg.ps1` / `.bat`: chạy ngầm `uvicorn --workers 1` trước demo ~15 phút để làm ấm Speed Layer, chống chạy trùng cổng (`Exit=1`), dừng sạch bằng PID.

---

## Chương 6. Thực nghiệm, Kiểm chứng & Kết luận
- **6.1. Benchmark Speed Layer Poller (2 chu kỳ 45s trực tiếp):**
  - Cycle 1 (`44.1s`): `eff_stale60: 238 -> 38`, `eff_stale90: 18 -> 8`, TimBus `238/238` (`hit=200, miss=38, err=0`), `5.74 req/s`, `P50=145ms, P90=246ms`.
  - Cycle 2 (`33.8s`): `eff_stale60: 155 -> 28`, **`eff_stale90: 4 -> 2` (`99.5% < 90s`)**, TimBus `151/151` (`hit=127, miss=24, err=0`), `4.83 req/s`, `P50=176ms, P90=333ms`.
- **6.2. Soak Test Liên tục ~8 Phút (`32` ticks, `474s`, `4,365` gói tin upstream):**
  - `SpeedLayerPoller` hoàn thành `9` chu kỳ (`min=41.5s`, `median=46.40s`, `max=57.07s`), `status=healthy` & `circuit_state=CLOSED` ở `32/32` ticks (`busmap_ok=864`, `recovered_live=974`, `parked_skip=16`, `on_corridor_gap=96`, `upstream_error=1`).
  - Tỷ lệ thành công HTTP: BusMap `1,137/1,137` (`200 OK`), TimBus `3,224/3,228` (`4` timeout, `0` lỗi `429`/`403`). Tần suất TimBus trung bình `6.81 req/s` (`Speed=2.42 req/s`, `Serving=4.39 req/s`).
  - Độ tươi & chất lượng ETA: tuyến `32` & `27` đạt `P50=0.6s`, `P90=0.8–1.0s`; `0` lỗi logic (`negative_eta=0`, `extreme_implied_speed=0`, `dist_jump_backwards_gt300m=0`, `eta_sort_order_bug=0`). Phát hiện & xử lý đúng thiết kế trường hợp xe dừng $>90\text{s}$ (`29F-001.16` $\to$ `cold_start_causal`) và sửa `_last_cycle_epoch = end_ts`.
- **6.3. Benchmark Out-of-Time 7 ngày (`2026-11-13` → `2026-11-19`, `8,306,295` mẫu test, `17,866,649` mẫu train `2026-10-18..2026-11-12`):**
  - **Overall (`8,306,295` mẫu):** Baseline `186.11s` MAE | `causal_eta_v1` (36f, 900 cây) `159.55s` MAE | **Model mới (40f + TomTom, 1200 cây) `141.28s` MAE** (`-18.27s`, P90 giảm `379.86s → 327.87s`, Crossing-balanced MAE `113.36s → 102.13s`).
  - **Tách slice `by_incident`:**
    - `no_incident` (`3,664,284` mẫu): `99.25s → 95.09s` (`-4.16s`).
    - `has_incident` (`4,642,011` mẫu): Baseline `237.11s` | 36f `207.14s` | **40f + TomTom `177.74s`** (**`-29.40s` MAE**, P90 giảm `-81.26s`).
  - **Theo khoảng cách chặng (`by_horizon`):** `1 hop`: `45.71s` (baseline `62.50s`), `2–5 hops`: `73.81s` (`95.54s`), `6–15 hops`: `135.33s` (`171.92s`), `16+ hops`: `221.16s` (`301.58s`).
  - **Feature Importance TomTom:** `inc_ahead_total_delay_sec` (`1,613` splits, gain `3,414.0`), `inc_dist_to_nearest_m` (`581` splits, gain `475.46`), `inc_ahead_jam_length_m` (`979` splits, gain `315.57`), `inc_info_age_sec` (`312` splits, gain `183.78`).
- **6.4. Kiểm thử Tự động & Trình duyệt Thực tế:**
  - Bộ kiểm thử `pytest tests/ --basetemp=runtime/pytest_tmp -q`: **`200 passed, 12 skipped, 0 failed`**.
  - Chrome DevTools (`/` và `/debug`): `0` lỗi console, vẽ `5` LineString sự cố trên tuyến `01`, tab *Sự cố TomTom* & popup hoạt động đầy đủ; soak test `8` phút (`96/96` HTTP 200, `204/204` trace 40f hợp lệ, `0` vi phạm quantile).
