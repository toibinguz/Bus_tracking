# Đề cương Chi tiết Nội dung Báo cáo Kỹ thuật Đầy đủ (`report_full.pdf`)

> **Phạm vi:** Tài liệu này hệ thống hóa toàn bộ nội dung lý thuyết, công thức toán học, tham số chuẩn hóa (SSOT), kiến trúc hệ thống 3 tầng, sơ đồ luồng xử lý và kết quả thực nghiệm cho **Bản Báo cáo Đầy đủ** (`report/report_full.tex` $\to$ `report/report_full.pdf`), bảo đảm tính đầy đủ về mặt kỹ thuật, chặt chẽ và không trùng lặp.
> *(Bản Rút gọn `report/report_short.pdf` sẽ cô đọng các kết quả và đóng góp cốt lõi trong giới hạn $\le 5$ trang.)*

---

## Chương 1. Tổng quan Bài toán và Kiến trúc Hệ thống (Lambda 3 Tầng)
- **1.1. Bối cảnh và Yêu cầu Thực tiễn tại Hà Nội:**
  - Hạn chế của dữ liệu GPS BusMap công khai đơn nguồn: độ trễ cập nhật từ 15–60s trở lên, hiện tượng gián đoạn tín hiệu phương tiện tạm thời giữa tuyến, nhiễu vận tốc tức thời từ thiết bị đầu cuối, và trạng thái khởi động nguội (cold-start) kéo dài 3–5 phút khi khởi chạy ứng dụng.
  - Yêu cầu bài toán: vừa xây dựng kho lưu trữ và xử lý dữ liệu lịch sử quy mô lớn theo mô hình Bronze–Silver–Gold, vừa bảo đảm năng lực dự báo ETA thời gian thực chính xác, ổn định và minh bạch trạng thái vận hành cho hành khách cũng như kỹ sư hệ thống.
- **1.2. Kiến trúc Lambda 3 Tầng (Batch Layer – Speed Layer – Serving Layer):**
  - **Batch Layer:** Thu thập dữ liệu liên tục 24/7 $\to$ xử lý qua các tầng HDFS Bronze/Silver/Gold $\to$ lưu trữ bản trích rút gọn trên SQLite và huấn luyện mô hình `causal-eta.v1`.
  - **Speed Layer:** Tiến trình nền `SpeedLayerPoller` vận hành theo chu kỳ `45s` nhằm thu thập và duy trì trạng thái bộ nhớ đệm trong RAM (`CausalFeatures`, `RouteProjectionTracker`, `RouteHMM`, `_tb_last_valid`), đồng thời đồng bộ ảnh chụp sự cố TomTom trực tiếp từ Hugging Face theo chu kỳ `300s` — tách biệt hoàn toàn khỏi tác vụ lọc trạm và suy luận ETA.
  - **Serving Layer:** Dịch vụ `BusMapServingService` (FastAPI) khai thác trực tiếp trạng thái RAM đã được chuẩn bị sẵn, kết hợp truy vấn BusMap `route_query` và TimBus Focus `5s` để thực hiện lọc phương tiện theo trạm, suy luận mô hình học máy và áp dụng chính sách ổn định `eta_policy`.
  - **Sơ đồ kiến trúc tổng quan** cùng phần phân tách rõ ràng **Luồng Dữ liệu** và **Luồng Logic** trên cả 3 tầng.

---

## Chương 2. Module 1 & 2 — Thu thập, Tiền xử lý và Medallion Lakehouse (Batch Layer)
- **2.1. Thu thập Dữ liệu Đa nguồn (`step_1_1`):**
  - Bộ thu thập đám mây 24/7 trên GitHub Actions (`crawl_bus.yml`): thời lượng mỗi phiên `540s`, chu kỳ lặp `75s`, kích thước lô `18` xe, sử dụng raw SSL socket (`socket_client.py` với bộ nhớ đệm DNS `_IP_CACHE_LOCK` và ngưỡng timeout `4.2s`).
  - Thu thập sự cố giao thông TomTom (`incident_client.py`): chỉ truy vấn dữ liệu sự cố nhằm tuân thủ giới hạn quota `80/ngày` và `2500/tháng` (`TOMTOM_INCIDENT_INTERVAL_SEC = 750s`, tương đương ~12.5 phút/lần); ngay sau khi truy vấn, đẩy tệp `raw_data/latest_incidents.json` lên Hugging Face (`push_latest_incidents_to_hf`) để Speed Layer tái sử dụng từ cùng một lượt gọi API.
  - Cập nhật danh mục phương tiện đầu ngày (`catalog_refresher.py`): quét `route_bus_gps` trên toàn bộ 49 tuyến, cập nhật `routeId` khi phương tiện chuyển tuyến và chỉ loại bỏ phương tiện khi `status == "ERROR"`.
- **2.2. Làm sạch Động học và Phân đoạn Chuyến đi (`step_1_3`):**
  - Hệ tham số chuẩn hóa SSOT (`config/system_config.py`):
    - `HANOI_BBOX`: vĩ độ `19.50..22.50`, kinh độ `104.50..107.50`.
    - Phát hiện dịch chuyển bất thường (`GPS_DRIFT_JUMP`): thỏa mãn đồng thời `dist >= 250.0m` và `v_calc > 80.0 km/h`; loại trừ các điểm `OUT_OF_BOUNDS` và nhiễu drift khỏi `kinematic_cache`.
    - `TERMINAL_STATIONARY_TOL_M = 15.0m`, phân loại trạng thái thành `IDLE_DEPOT`, `ACTIVE_VALID` và `STALE_PING`.
  - Phân đoạn chuyến đi (`trip_segmenter.py`): `MAX_CONTINUOUS_GAP_SEC = 300.0s`, `MAX_BRIDGEABLE_DETOUR_GAP_SEC = 1800.0s`, `MAX_BACKWARD_RESET_M = 200.0m`, kết hợp hàm cắt tỉa điểm dừng đầu/cuối bến `trim_terminal_stationary_ends()`.
- **2.3. Chiếu Không gian 1D Frenet và Mô hình Viterbi HMM (`step_1_4`):**
  - `ShapeProjectionModel` thực hiện ánh xạ tọa độ `(lat, lon)` $\to$ `(s_bus_m, cross_track_m)`.
  - `RouteHMM` (sử dụng thống nhất giữa Batch Layer với `BATCH_HMM_HORIZON_SEC = 300.0s` và Speed/Serving Layer): kết hợp xác suất phát xạ Gaussian theo `cross_track` với xác suất chuyển trạng thái theo hướng tiếp tuyến và độ tiến triển $\Delta s$; ngưỡng lọc xuất dữ liệu Silver là `MAX_CORRIDOR_CROSS_TRACK_M = 35.0m`.
- **2.4. Lưu trữ HDFS và Kiến trúc Medallion Lakehouse (`Module 2`):**
  - **Bronze (`step_2_4`):** Lưu trữ tại `/bus-eta/v1/bronze/hf_raw`, bảo đảm tính bất biến và toàn vẹn dữ liệu thông qua mã băm SHA-256 (`receipt.py`, `spool.py`).
  - **Silver (`step_2_4`, `step_2_2`):** Xử lý phân tán bằng Spark P2 (`p2_transform.py`) và lưu trữ định dạng Parquet Snappy (`route_projected_telemetry`, `fact_route_tomtom_incidents`).
  - **Gold (`step_3_1`, `step_2_4`):** Tổng hợp ma trận thời gian di chuyển lịch sử `agg_segment_travel_times` (`p10`, `p50`, `p90`, `mean`, `std` phân nhóm theo `(route_id, direction, segment_idx, day_type, hour_slot)`, với `MIN_SAMPLES_FOR_BASELINE = 5`, `MAX_SEGMENT_TRAVEL_TIME_SEC = 1800.0s`) và tạo bản phát hành snapshot (`eta_snapshot.py`).
  - **SQLite (`hanoi_bus_system.db`, `step_2_1`):** Cơ sở dữ liệu gọn nhẹ chứa cấu trúc GTFS chuẩn hóa (`canonical_routes`, `canonical_shapes`, `canonical_stations`) cùng bảng tổng hợp Gold Baseline phục vụ truy xuất độ trễ thấp.

---

## Chương 3. Speed Layer — Poller 45s, Phân loại Trạng thái và Khắc phục Cold-Start
- **3.1. Cơ sở Thiết kế từ Thực nghiệm Đối chiếu BusMap `route_query` và `per_vehicle`:**
  - Thực nghiệm đối chiếu trực tiếp trên 5 tuyến (`02, 27, 32, 01, E03`): sai lệch vị trí và thời gian bằng `0.0m` / `0.0s`; toàn bộ `17/17` phương tiện không xuất hiện trong `route_query` đều là xe ngoài hành trình (`curr_st=0, next_st=0`, `ct = 254.9..4,059.4m`) hoặc tín hiệu đóng băng (`29,361..109,161s`).
  - Kết luận thiết kế: Cả Speed Layer và Serving Layer đều sử dụng thống nhất giao diện BusMap `route_bus_gps` (route-query).
  - Phạm vi tập tuyến giao thoa: `48` tuyến Baseline (`756` xe), bao gồm `31` tuyến hỗ trợ TimBus (`495` xe, chiếm `65.5%`) và `17` tuyến chỉ có dữ liệu BusMap (`261` xe).
- **3.2. Kiến trúc `SpeedLayerPoller` (`speed_poller.py`):**
  - Chu kỳ `45s` thực thi Phase 1 (quét BusMap `route_bus_gps` trên 48 tuyến $\times$ 2 chiều) $\to$ gọi `ingest_speed_layer_vehicles` để cập nhật sẵn `RouteProjectionTracker`, `RouteHMM` và `CausalFeatures`.
  - Phase 2 (Bổ khuyết dữ liệu TimBus): vận hành `2` luồng xử lý dàn trải (`stagger_delay_sec = 0.15s`), chỉ truy vấn `anchors[:1]` (`primary_anchor_sid`), kích hoạt đối với phương tiện có `age >= 60s` hoặc bị mất dấu giữa tuyến; tự động bỏ qua các phương tiện mà Serving Layer vừa truy vấn trong vòng `< 45s` trong `_tb_last_valid`.
  - Phase 3 (Chuyển tiếp sự cố TomTom trực tuyến qua Hugging Face, chu kỳ `300s`/lần): Bộ thu thập tải ngay tệp `raw_data/latest_incidents.json` lên Hugging Face ngay sau khi truy vấn TomTom nhằm dùng chung **1 lượt gọi API duy nhất** cho cả Batch Layer và Speed/Serving Layer dưới ràng buộc quota (`<= 80/ngày`, `<= 2,500/tháng`), qua đó loại bỏ độ trễ 12.5–22.5 phút; Speed Layer đồng bộ lại qua `fetch_latest_incidents_from_hf` $\to$ `ingest_live_incidents` (bảo lưu bộ nhớ đệm hiện tại nếu dữ liệu tải về không hợp lệ).
  - **Ngừng truy vấn ngoài giờ vận hành (`22:30 – 04:45` giờ Hà Nội):** Khi `is_operating_hours()` trả về `False`, hệ thống tạm dừng toàn bộ các lượt gọi BusMap và TimBus vào ban đêm.
- **3.3. Cơ chế Phân loại 4 Trạng thái và Circuit Breaker:**
  - `RECOVERED_LIVE`: Truy vấn TimBus thành công $\to$ cập nhật `_tb_last_valid` và `CausalFeatures`, đặt `cooldown = 0s`, đặt lại `error_streak`.
  - `TERMINAL_OR_DEPOT_PARKED`: Không có phản hồi kèm `speed == 0` và (`ct > 35m` hoặc khoảng cách tới bến $\le 300\text{m}$) $\to$ áp dụng `cooldown = 180s`.
  - `ON_CORRIDOR_GAP`: Không có phản hồi dù phương tiện vẫn bám hành lang tuyến (`ct <= 35m`, cách bến $> 300\text{m}$) $\to$ áp dụng `cooldown = 45s`, ghi nhận vào `gap_routes_top`.
  - `UPSTREAM_ERROR`: Xảy ra timeout hoặc lỗi kết nối $\to$ tăng `error_streak`; khi đạt ngưỡng $\ge 3$, kích hoạt **Circuit Breaker `90s`** (`circuit_state = "OPEN"`).
- **3.4. An toàn Đa luồng (`--workers 1`):**
  - Sử dụng `threading.RLock` trong `CausalFeatures` (`causal_eta.py`) kết hợp cùng `_causal_lock` và `_tb_lock` trong `BusMapServingService` nhằm bảo đảm tính nhất quán bộ nhớ chia sẻ.

---

## Chương 4. Serving Layer, Mô hình `causal-eta.v1` và Chính sách ETA
- **4.1. Luồng Phục vụ `BusMapServingService` (`serving_service.py`):**
  - Khai thác dữ liệu RAM đã chuẩn bị từ Speed Layer, kết hợp truy vấn BusMap `route_bus_gps` (`live_feed.py`, bộ nhớ đệm `15s`) và đồng bộ TimBus Focus `5s` (`_sync_route_both_directions`).
  - Lọc phương tiện phục vụ từng trạm (`_filter_station_vehicles` + `project_filter_extrapolate`): kiểm tra ràng buộc `cross_track <= 35m`, đúng chiều di chuyển, `s_now <= s_target`, cơ chế Pass Guard `_passed_station_plates` (ngăn chặn tình trạng phương tiện đã đi qua trạm xuất hiện trở lại từ bộ nhớ đệm cũ), đồng thời làm mượt vận tốc vĩ mô qua `MacroSpeedTracker` ($\Delta s / \Delta t > 120\text{s}$).
  - Chiếu hình học và nạp dữ liệu sự cố TomTom trực tuyến (`get_live_incidents_for_route` $\to$ `observe_incidents`): áp dụng ngưỡng thời gian sống TTL `2700s` (45 phút) cho ảnh chụp `latest`, thực hiện phép chiếu LineString đồng nhất giữa môi trường Online và Offline (`ShapeProjectionModel.project_directed_point` với điều kiện `cos_theta >= 0.5` trước khi lấy `argmin`, kết hợp `split_matched_vertices_into_runs` để gom đoạn đơn điệu), quy đổi `delay_seconds` theo tỷ lệ `span_route / eff_inc_span` cho `CausalFeatures`, và đính kèm `polylines` trong `RouteIncidentDTO`.
- **4.2. Bộ 40 Đặc trưng Nhân quả `CausalFeatures` (`step_3_2`):**
  - Tuân thủ nguyên tắc nhân quả nghiêm ngặt: chỉ sử dụng tiền tố quan sát trong quá khứ (dùng chung một luồng xử lý duy nhất giữa giai đoạn huấn luyện tái lập và suy luận trực tuyến), với `MAX_POSITION_AGE = 90.0s` và `MAX_FLEET_SKEW = 45.0s`.
  - Cấu trúc gồm 6 nhóm với tổng cộng 40 biến đầu vào: Tuyến và Thời gian (9), Hình học và Khoảng cách (7), Động học phương tiện chủ thể (2), Thống kê Baseline (11), Trạng thái đội xe cùng tuyến (7), và **Sự cố TomTom (4)**: `inc_ahead_total_delay_sec` *(ràng buộc đơn điệu `+1`, phân bổ theo tỷ lệ chồng lấp `ov_l / eff_inc_span`)*, `inc_dist_to_nearest_m`, `inc_ahead_jam_length_m`, và `inc_info_age_sec` *(tuổi thông tin sự cố `t_cur - crawled_epoch`)*.
- **4.3. Mô hình Residual XGBoost (`causal-eta.v1`, `step_3_3` & `model_runtime.py`):**
  - Dự báo phần dư `delta = eta_actual - baseline_eta_p50_sec` thông qua `XGBRegressor` (`reg:absoluteerror`, `max_depth = 6`, `1200` cây, `best_iteration = 1199`, huấn luyện streaming `xgb.QuantileDMatrix` trên GPU CUDA); giá trị ETA trung vị được tái dựng theo biểu thức $\text{ETA}_{P50} = \max(5.0,\ \text{baseline\_p50} + \delta)$.
  - Phân tích các điều kiện kích hoạt cơ chế dự phòng (`predict_p50_with_reason`).
- **4.4. Chính sách Ổn định và Cửa sổ An toàn (`eta_policy.py`):**
  - Điều chỉnh tiệm cận khi hai phương tiện bám sát nhau (`compute_proximity_capped_etas`: `PROXIMITY_CAP_FULL_M = 80m`, `FADE_M = 120m`, `SPEED = 2.5 m/s`, `MARGIN = 15s`).
  - Công thức xác định **Độ trễ (`delay_seconds`)**: $\Delta_{\text{delay}} = \max(0,\ \text{eta\_core\_p50} - \text{base\_rem\_p50})$, kết hợp cờ `is_delayed` và các mức phân loại `THONG_THOANG` / `BINH_THUONG` / `UN_TAC`.
  - Công thức **Độ đệm bất đối xứng LINEX (`buffer_seconds`)**:
    $$B = \min\Big(\text{MAX\_SAFE\_BUFFER\_CEILING\_SEC},\ \kappa(d_{\text{station}}) \cdot (\alpha\,\sigma_{\text{accum}} + \beta\,\text{HEARTBEAT} + \gamma\,\text{eta\_core\_p50})\Big)$$
    xác định hai cận dự báo: Cận sớm ($\text{eta\_core} - B$) và Cận muộn ($\text{eta\_core} + B$), được lượng tử hóa theo phút trần trong `SafeWindowDTO`.
- **4.5. Cơ chế Phản hồi Trạng thái Tường minh (Loại bỏ Silent Fallback):**
  - `upstream_status` (`ok | empty | upstream_error`) kèm `upstream_error` (`live_feed.py`).
  - `timbus_status` (`ok | partial_error | upstream_error | unsupported`) kèm `timbus_error` (`timbus_tracker.py`).
  - `fallback_reason` (`ok | cold_start_causal | model_unavailable | unknown_route | predict_error`).
  - Phân tách hai mốc thời gian của gói tin: `ping_time` (thời điểm truy vấn TimBus) và `busmap_updated_at` (thời điểm ghi nhận từ thiết bị GPS gốc của BusMap).
  - Endpoint `/api/health` công bố trạng thái `healthy` / `degraded`, biến `model_available` và ảnh chụp trạng thái chi tiết của `SpeedLayerPoller`.

---

## Chương 5. Giao diện Web Trình diễn (`/`, `/debug`) và Vận hành Hệ thống
- **5.1. Giao diện Hành khách Tối giản (`/`):**
  - Nền bản đồ vệ tinh Esri (`World_Imagery`), bảng điều khiển có khả năng điều chỉnh độ rộng (`#panelResizer`, `280–680px`), hỗ trợ thu gọn bảng điều khiển và bố cục bottom-sheet 3 mức trên thiết bị di động.
  - Trường tìm kiếm tuyến (`#routeCombobox`) và trường chọn/lọc trạm tinh gọn (`#stationCombobox`) được bố trí phía trên vùng hiển thị ETA nhằm tối ưu hóa không gian trình bày kết quả.
  - Khi người dùng chọn trạm, hệ thống tự động ghim trạm ngay lập tức mà không mở popup trên bản đồ; làm nổi bật **phương tiện gần trạm nhất** (thẻ nổi bật kèm vòng phát sáng định vị trên bản đồ), đồng thời hiển thị biểu ngữ cảnh báo tường minh khi phát sinh lỗi nguồn dữ liệu, dữ liệu cũ hoặc chế độ ước tính nền.
- **5.2. Bảng Điều khiển Giám sát Vận hành (`/debug`):**
  - Giao diện nền tối tách biệt, bố cục 2 cột gồm bản đồ vệ tinh Esri và bảng phân tích có thể kéo dãn tỷ lệ (`#dbgSplitter`), tích hợp **4 thẻ nội dung độc lập** không cuộn trang: *Trạm & ETA*, *Đoàn xe & Telemetry*, ***Sự cố TomTom*** (hiển thị LineString theo mức độ nghiêm trọng, hộp thoại thông tin chi tiết và thao tác phóng tới vị trí sự cố khi chọn dòng), và *Hệ thống & Poller* (hiển thị trạng thái `LIVE TOMTOM INCIDENTS (HF RELAY)`).
  - Trình bày song song hai mốc `TB query` và `BM thiết bị` (`busmap_updated_at`), đồng thời đánh dấu nổi bật hàng phương tiện dẫn đầu (`.is-leading`).
- **5.3. Kịch bản Khởi chạy Nền Phục vụ Demo (`scripts/`):**
  - `start_demo_bg.ps1` / `.bat` và `stop_demo_bg.ps1` / `.bat`: khởi chạy tiến trình nền `uvicorn --workers 1` trước thời điểm trình diễn khoảng 15 phút để chuẩn bị sẵn trạng thái Speed Layer, ngăn ngừa xung đột cổng (`Exit=1`) và hỗ trợ dừng tiến trình an toàn theo PID.

---

## Chương 6. Thực nghiệm, Kiểm chứng và Kết luận
- **6.1. Đánh giá Hiệu năng Speed Layer Poller (2 chu kỳ `45s` trực tiếp):**
  - Chu kỳ 1 (`44.1s`): `eff_stale60: 238 -> 38`, `eff_stale90: 18 -> 8`, TimBus `238/238` (`hit=200, miss=38, err=0`), tốc độ `5.74 req/s`, độ trễ `P50=145ms, P90=246ms`.
  - Chu kỳ 2 (`33.8s`): `eff_stale60: 155 -> 28`, **`eff_stale90: 4 -> 2` (`99.5% < 90s`)**, TimBus `151/151` (`hit=127, miss=24, err=0`), tốc độ `4.83 req/s`, độ trễ `P50=176ms, P90=333ms`.
- **6.2. Kiểm thử Vận hành Liên tục ~8 Phút (`32` ticks, `474s`, `4,365` gói tin từ nguồn dữ liệu):**
  - `SpeedLayerPoller` hoàn thành `9` chu kỳ (`min=41.5s`, `median=46.40s`, `max=57.07s`), duy trì `status=healthy` và `circuit_state=CLOSED` trên toàn bộ `32/32` ticks (`busmap_ok=864`, `recovered_live=974`, `parked_skip=16`, `on_corridor_gap=96`, `upstream_error=1`).
  - Tỷ lệ phản hồi HTTP thành công: BusMap `1,137/1,137` (`200 OK`), TimBus `3,224/3,228` (`4` timeout, `0` lỗi `429`/`403`). Tần suất truy vấn TimBus trung bình đạt `6.81 req/s` (`Speed=2.42 req/s`, `Serving=4.39 req/s`).
  - Độ tươi dữ liệu và tính đúng đắn ETA: tuyến `32` và `27` đạt `P50=0.6s`, `P90=0.8–1.0s`; ghi nhận `0` lỗi logic (`negative_eta=0`, `extreme_implied_speed=0`, `dist_jump_backwards_gt300m=0`, `eta_sort_order_bug=0`). Hệ thống nhận diện và xử lý đúng thiết kế đối với phương tiện dừng quá `90s` (`29F-001.16` $\to$ `cold_start_causal`), đồng thời khắc phục cập nhật `_last_cycle_epoch = end_ts`.
- **6.3. Đánh giá Ngoài Tập Huấn luyện 7 Ngày (`2026-11-13` → `2026-11-19`, `8,306,295` mẫu kiểm thử, `17,866,649` mẫu huấn luyện giai đoạn `2026-10-18..2026-11-12`):**
  - **Tổng thể (`8,306,295` mẫu):** Baseline đạt `186.11s` MAE | `causal_eta_v1` (36 đặc trưng, 900 cây) đạt `159.55s` MAE | **Mô hình mới (40 đặc trưng + TomTom, 1200 cây) đạt `141.28s` MAE** (giảm `-18.27s`, P90 giảm từ `379.86s → 327.87s`, MAE cân bằng theo lượt qua điểm cắt giảm từ `113.36s → 102.13s`).
  - **Phân tách theo điều kiện sự cố (`by_incident`):**
    - Nhóm `no_incident` (`3,664,284` mẫu): giảm từ `99.25s → 95.09s` (`-4.16s`).
    - Nhóm `has_incident` (`4,642,011` mẫu): Baseline `237.11s` | 36 đặc trưng `207.14s` | **40 đặc trưng + TomTom `177.74s`** (**giảm `-29.40s` MAE**, P90 giảm `-81.26s`).
  - **Phân tích theo tầm dự báo (`by_horizon`):** `1 hop`: `45.71s` (baseline `62.50s`), `2–5 hops`: `73.81s` (`95.54s`), `6–15 hops`: `135.33s` (`171.92s`), `16+ hops`: `221.16s` (`301.58s`).
  - **Mức độ đóng góp của các đặc trưng TomTom:** `inc_ahead_total_delay_sec` (`1,613` splits, gain `3,414.0`), `inc_dist_to_nearest_m` (`581` splits, gain `475.46`), `inc_ahead_jam_length_m` (`979` splits, gain `315.57`), `inc_info_age_sec` (`312` splits, gain `183.78`).
- **6.4. Kiểm thử Tự động và Kiểm chứng trên Trình duyệt Thực tế:**
  - Bộ kiểm thử đơn vị và tích hợp `pytest tests/ --basetemp=runtime/pytest_tmp -q`: **`200 passed, 12 skipped, 0 failed`**.
  - Kiểm chứng qua Chrome DevTools trên `/` và `/debug`: `0` lỗi console, hiển thị chính xác `5` LineString sự cố trên tuyến `01`, thẻ *Sự cố TomTom* cùng hộp thoại thông tin hoạt động ổn định; thử nghiệm vận hành liên tục `8` phút ghi nhận `96/96` phản hồi HTTP 200, `204/204` bản ghi đặc trưng 40 biến hợp lệ và `0` vi phạm thứ tự quantile.
