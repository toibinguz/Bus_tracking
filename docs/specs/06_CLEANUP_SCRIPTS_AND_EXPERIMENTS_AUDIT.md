# SPEC-06: ĐẶC TẢ KIỂM TOÁN VÀ ĐIỀU PHỐI TINH GỌN SCRIPTS VÀ EXPERIMENTS (CLEANUP AUDIT)
> **Status (2026-11-10):** Completed only for the script/experiment migration recorded here. Expected moved test files do not exist under `tests/`; they are not evidence of completed verification.
## Document ID: `06_CLEANUP_SCRIPTS_AND_EXPERIMENTS_AUDIT`

- **Tác giả:** `@architect`
- **Người thẩm định:** `@orchestrator`
- **Người thực thi điều phối:** `@leaf_coder`
- **Người nghiệm thu độc lập:** `@blind_tester`
- **Ngày ban hành:** 2026-11-09
- **Trạng thái:** APPROVED / READY FOR GOVERNANCE EXECUTION
- **Căn cứ kiến trúc:** 
  - `AGENTS.md` (Simplicity First - Minimum code, zero dead code, surgical changes)
  - `docs/specs/04_BUSMAP_ONLY_DISCRETE_TRACKING_SPEC.md` (Bãi bỏ 100% TimBus, chuyển sang BusMap Rời rạc)
  - `docs/specs/05_ROUTE_SHAPE_AND_STATION_INTERACTIONS_SPEC.md` (Hiển thị tim tuyến và trạm dừng trên nền Esri Satellite)

---

## 1. BỐI CẢNH & MỤC TIÊU TINH GỌN (CONTEXT & OBJECTIVES)

### 1.1. Bối cảnh chuyển dịch kiến trúc
Hệ thống Hanoi Bus Big Data & Real-time ETA Prediction đã hoàn tất chuyển dịch dứt điểm sang **Kiến trúc Tối giản Thuần BusMap Rời rạc (Simplicity First)**:
1. **Bãi bỏ 100% TimBus:** Khai tử toàn bộ kết nối TCP socket cổng 9149, thuật toán giải mã nhị phân byte codec, mã hóa XOR cipher, suy diễn trạm TimBus (`StationID`), và cơ chế Fallback lai ghép (Hybrid FSM).
2. **Bãi bỏ 100% Thuật toán Nội suy 60 FPS:** Khai tử toàn bộ thuật toán Dead Reckoning ngoại suy chuyển động dọc tuyến Frenet, vòng lặp hoạt họa `requestAnimationFrame` 60 FPS, Cubic Hermite Spline, và bộ đệm khử giật động học (Jitter Smoother).
3. **Thống nhất Nguồn dữ liệu & Giao diện:** Sử dụng duy nhất API chính thức `route_bus_gps` của BusMap qua HTTPS, cập nhật vị trí xe giật cục rời rạc chu kỳ 15 giây trực tiếp lên bản đồ ảnh vệ tinh **Esri World Imagery**, cùng lớp tim tuyến (`canonical_shape_master`) và trạm dừng đánh số (`canonical_station_master`).

### 1.2. Vấn đề tồn dư kỹ thuật (Technical Debt)
Quá trình chuyển dịch diễn ra nhanh chóng đã để lại một lượng lớn file rác, mã kiểm thử lỗi thời và cấu trúc thư mục phân tán:
- Nhiều bộ test hộp đen phục vụ nghiệm thu kiến trúc mới đang nằm lẫn lộn trong `scripts/` thay vì tập trung tại `tests/`.
- Các file kiểm thử TimBus, dead reckoning và các đoạn mã gọi đến các module đã xóa (`eta_serving_service.py`, `contract.py`, `eta_inference_engine.py`) vẫn tồn tại trong `scripts/`, gây lỗi import khi chạy test runner toàn cục.
- Toàn bộ thư mục `experiments/timbus/` cùng các thực nghiệm TimBus trong `experiments/` đã mất hoàn toàn giá trị sử dụng.
- Các tệp bytecode `__pycache__` của các phiên bản cũ tích tụ rác.

### 1.3. Mục tiêu kiểm toán
1. Rà soát độc lập, định lượng 100% các tệp tin trong `scripts/`, `experiments/` (kèm `experiments/timbus/`).
2. Phân loại dứt khoát từng tệp vào đúng 3 nhóm:
   - **Nhóm 1: GIỮ LẠI (Keep)**: Các script phục vụ vận hành pipeline production cốt lõi.
   - **Nhóm 2: DI CHUYỂN (Move)**: Chuyển các bài test hộp đen đang hoạt động từ `scripts/` về `tests/`; quy hoạch các script EDA / kiểm định phần cứng GPS vào các thư mục con chuyên biệt trong `experiments/`.
   - **Nhóm 3: XÓA SỔ (Delete / Deprecate)**: Xóa bỏ triệt để toàn bộ mã nguồn TimBus, thuật toán mô phỏng 60 FPS, các file kiểm thử hỏng phụ thuộc module cũ, và toàn bộ thư mục `experiments/timbus/`.

---

## 2. BẢNG TỔNG HỢP KIỂM TOÁN TỔNG QUAN (EXECUTIVE SUMMARY)

Tổng số tệp được kiểm toán: **77 tệp** (42 tệp tại `scripts/`, 35 tệp tại `experiments/`).

| Thư mục kiểm toán | Tổng tệp | Giữ lại nguyên vị trí (Keep) | Di chuyển / Gom nhóm (Move) | Đề xuất Xóa bỏ (Delete) |
| :--- | :---: | :---: | :---: | :---: |
| **`scripts/` (Mã nguồn & Scripts)** | 30 | 15 | 4 (chuyển sang `tests/`) | 11 |
| **`scripts/__pycache__/` (Cache)** | 12 | 0 | 0 | 12 |
| **`experiments/` (Thư mục gốc)** | 15 | 0 | 14 (quy hoạch vào subfolder) | 1 |
| **`experiments/__pycache__/` (Cache)** | 2 | 0 | 0 | 2 |
| **`experiments/timbus/` (Toàn bộ)** | 14 | 0 | 0 | 14 |
| **`experiments/timbus/__pycache__/`** | 4 | 0 | 0 | 4 |
| **TỔNG CỘNG HỆ THỐNG** | **77** | **15** | **18** | **44** |

---

## 3. DANH MỤC KIỂM TOÁN CHI TIẾT TỪNG TỆP TIN

### 3.1. Phân tích Thư mục `scripts/` (42 tệp)

#### Bảng 1: Các script Pipeline Vận hành Cốt lõi — ĐỀ XUẤT: GIỮ LẠI (15 tệp)
Các tệp này là CLI Entry Points chính thức phục vụ toàn bộ chu trình dữ liệu từ Ingestion (Module 1), Lakehouse Storage (Module 2) đến Baseline & Training (Module 3).

| STT | Tên tệp | Kích thước | Vai trò kiến trúc | Đề xuất | Lý do kỹ thuật |
| :---: | :--- | :---: | :--- | :---: | :--- |
| 1 | `scripts/bulk_ingest_all_bus_pings.py` | 377 B | Module 1 - Step 1.3 | **GIỮ LẠI** | CLI nạp dữ liệu viễn trắc thô từ JSON crawler vào SQLite `vehicle_unique_pings`. |
| 2 | `scripts/parallel_multi_route_projector.py` | 404 B | Module 1 - Step 1.4 | **GIỮ LẠI** | CLI tính toán chiếu tọa độ 1D Frenet đa tiến trình lên tim tuyến cho toàn mạng lưới. |
| 3 | `scripts/build_fact_route_tomtom_incidents.py` | 374 B | Module 1 - Step 1.4 | **GIỮ LẠI** | CLI chiếu dữ liệu sự cố giao thông TomTom vào hệ tọa độ 1D tuyến buýt. |
| 4 | `scripts/ingest_canonical_busmap_master.py` | 522 B | Ingestion Master | **GIỮ LẠI** | CLI nạp dữ liệu chuẩn BusMap vào `canonical_shape_master`, `canonical_station_master`, `canonical_route_master`. |
| 5 | `scripts/cloud_crawler_step.py` | 599 B | Production CI/CD | **GIỮ LẠI** | Facade tương thích ngược cho GitHub Actions workflow (`.github/workflows/crawl_bus.yml`). |
| 6 | `scripts/daily_catalog_refresh.py` | 520 B | Production Cron | **GIỮ LẠI** | CLI tự động cập nhật danh mục tuyến, trạm và lịch trình BusMap định kỳ. |
| 7 | `scripts/run_production_crawler.py` | 488 B | Production Crawler | **GIỮ LẠI** | Script kích hoạt crawler thu thập viễn trắc 24/7 cho toàn bộ các tuyến buýt hoạt động. |
| 8 | `scripts/start_crawler.bat` | 428 B | Deployment Ops | **GIỮ LẠI** | File batch khởi động crawler trên môi trường Windows Host. |
| 9 | `scripts/start_crawler_background.vbs` | 339 B | Deployment Ops | **GIỮ LẠI** | Script VBS khởi chạy crawler chạy ngầm không chiếm cửa sổ console. |
| 10 | `scripts/sync_from_hf.py` | 465 B | Cloud Sync Ops | **GIỮ LẠI** | CLI đồng bộ dữ liệu hồ dữ liệu Lakehouse từ Hugging Face Data Lake. |
| 11 | `scripts/audit_silver_lakehouse_purity.py` | 410 B | Module 2 - Step 2.2 | **GIỮ LẠI** | CLI kiểm định độc lập chất lượng và độ tinh khiết của Silver Parquet Lakehouse. |
| 12 | `scripts/build_baseline_travel_time_matrix.py` | 431 B | Module 3 - Step 3.1 | **GIỮ LẠI** | CLI xây dựng ma trận thời gian di chuyển lịch sử không rò rỉ dữ liệu (Leak-Free Baseline Matrix). |
| 13 | `scripts/build_gold_feature_store.py` | 413 B | Module 3 - Step 3.3 | **GIỮ LẠI** | CLI trích xuất kho đặc trưng Gold Feature Store phục vụ huấn luyện máy học. |
| 14 | `scripts/train_and_evaluate_ml_eta.py` | 448 B | Module 3 - Step 3.4 | **GIỮ LẠI** | CLI huấn luyện và đánh giá mô hình XGBoost ETA đa tuyến. |
| 15 | `scripts/verify_canonical_architecture.py` | 5,255 B | Lakehouse Audit | **GIỮ LẠI** | Script kiểm tra tính toàn vẹn end-to-end của CSDL SQLite và Bronze/Silver Lakehouse. |

---

#### Bảng 2: Các bài Test Hộp Đen Nghiệm Thu Kiến Trúc Mới — ĐỀ XUẤT: DI CHUYỂN SANG `tests/` (4 tệp)
Các file kiểm thử này đang hoạt động hoàn hảo (đạt 100% pass với 31 bài kiểm định nghiệm thu Spec 04 và Spec 05). Tuy nhiên, vị trí hiện tại nằm rải rác trong `scripts/` vi phạm quy chuẩn tổ chức dự án. Cần gom toàn bộ về thư mục quy chuẩn `tests/`.

| STT | Tên tệp hiện tại | Kích thước | Kết quả kiểm thử | Vị trí đích đề xuất | Lý do kỹ thuật |
| :---: | :--- | :---: | :---: | :--- | :--- |
| 1 | `scripts/test_discrete_busmap_tracking_blackbox.py` | 23,865 B | **8/8 PASSED** (0.97s) | `tests/test_discrete_busmap_tracking_blackbox.py` | Kiểm định chấp nhận Spec 04: Bãi bỏ TimBus, API Routes, Live Vehicles không lặp, giới hạn Hà Nội, Esri Satellite. |
| 2 | `scripts/test_esri_satellite_blackbox.py` | 4,495 B | **3/3 PASSED** (0.60s) | `tests/test_esri_satellite_blackbox.py` | Kiểm định chấp nhận cấu hình layer bản đồ vệ tinh Esri World Imagery mặc định. |
| 3 | `scripts/test_route_shape_and_stations_blackbox.py` | 23,538 B | **16/16 PASSED** (0.73s) | `tests/test_route_shape_and_stations_blackbox.py` | Kiểm định chấp nhận Spec 05: Tim tuyến, trạm dừng đánh số, popup thông tin trạm, tính đơn điệu lý trình. *(Ghi đè file stub 20 dòng hiện tại trong `tests/`)*. |
| 4 | `scripts/test_system_config_blackbox.py` | 3,423 B | **4/4 PASSED (22 subtests)** | `tests/test_system_config_blackbox.py` | Kiểm định chuẩn hóa hướng di chuyển và tính chịu lỗi của `config/system_config.py`. |

---

#### Bảng 3: Các tệp Mã Kiểm thử / Mô phỏng Lỗi thời — ĐỀ XUẤT: XÓA SỔ (11 tệp mã nguồn + 12 tệp cache)
Các file này trực tiếp liên quan đến TimBus (socket 9149, XOR cipher), thuật toán mô phỏng chuyển động 60 FPS (dead reckoning, marker tweening), hoặc tham chiếu đến các module/hàm đã bị xóa bỏ trong kiến trúc mới dẫn đến lỗi `ModuleNotFoundError`.

| STT | Tên tệp | Kích thước | Nguyên nhân phế bỏ kỹ thuật | Đề xuất |
| :---: | :--- | :---: | :--- | :---: |
| 1 | `scripts/test_dead_reckoning_kinematics.js` | 12,835 B | Mô phỏng Dead Reckoning và Continuous Reconciliation trên trình duyệt. Đã bị bãi bỏ 100% theo Spec 04 (bỏ 60 FPS, chuyển sang cập nhật giật cục rời rạc). | **XÓA BỎ** |
| 2 | `scripts/test_marker_tweening.js` | 706 B | Runner Node.js phục vụ kiểm tra Tweening 60 FPS. Không còn mục tiêu kiểm thử. | **XÓA BỎ** |
| 3 | `scripts/test_goal1_realtime_timbus_blackbox.py` | 34,843 B | Kiểm thử giải mã nhị phân, XOR cipher 2 khóa và socket 9149 của TimBus. TimBus đã bị bãi bỏ 100%. | **XÓA BỎ** |
| 4 | `scripts/test_hybrid_bus_tracking_parity.py` | 19,630 B | Kiểm thử đối soát xe lai ghép TimBus + BusMap. Mô hình lai ghép đã bị bãi bỏ hoàn toàn. | **XÓA BỎ** |
| 5 | `scripts/test_kinematic_smoothness_and_jitter.py` | 9,705 B | Đo độ rung lắc của chuyển động nội suy 60 FPS (ngủ 50s mỗi lần chạy). Hoàn toàn vô nghĩa với cơ chế discrete markers. | **XÓA BỎ** |
| 6 | `scripts/test_timbus_realtime_serving.py` | 11,270 B | Kiểm thử tích hợp serving luồng viễn trắc TimBus và Frenet Bridge. Không còn thành phần phục vụ TimBus. | **XÓA BỎ** |
| 7 | `scripts/test_anti_cheat_remediation.py` | 26,258 B | Gọi `ModuleNotFoundError: No module named '...eta_serving_service'` và subprocess gọi `test_marker_tweening.js`. | **XÓA BỎ** |
| 8 | `scripts/test_ground_truth_and_night_mode.py` | 15,735 B | Gọi `ModuleNotFoundError: No module named '...step_3_5_web_demo.api_routes'` và FSM trong JS cũ đã xóa. | **XÓA BỎ** |
| 9 | `scripts/verify_eta_serving.py` | 2,248 B | Gọi `ModuleNotFoundError: No module named '...eta_inference_engine'` (engine serving cũ đã tinh giản). | **XÓA BỎ** |
| 10 | `scripts/verify_online_serving_pipeline.py` | 9,676 B | Gọi `ImportError: cannot import name 'EtaServingService'` (dịch vụ phục vụ lai ghép cũ). | **XÓA BỎ** |
| 11 | `scripts/verify_web_app_demo.py` | 7,322 B | Gọi `ModuleNotFoundError: No module named '...contract'` (contract cũ đã được thay thế bởi Spec 04/05). | **XÓA BỎ** |
| 12-23 | `scripts/__pycache__/*.pyc` (12 tệp) | 338 KB | Toàn bộ các file bytecode cache của các test script cũ và mới trong `scripts/`. | **XÓA BỎ** |

---

### 3.2. Phân tích Thư mục `experiments/` (Thư mục gốc — 17 tệp)

Các tệp trong `experiments/` phản ánh quá trình nghiên cứu thực nghiệm khoa học dữ liệu (EDA) và kiểm định giao thức GPS phần cứng xe buýt.

#### Bảng 4: Các tệp Thực nghiệm Khoa học Dữ liệu & Giao thức — ĐỀ XUẤT: DI CHUYỂN / QUY HOẠCH (14 tệp)
Không nên xóa bỏ các phân tích dữ liệu quý giá này vì chúng ghi lại các đặc trưng nền tảng của Lakehouse và mạng lưới giao thông. Cần chuyển vào 2 thư mục con có tổ chức:
- `experiments/eda/`: Các phân tích thống kê, phân phối thời gian di chuyển, bất thường dữ liệu.
- `experiments/hardware_gps/`: Các thực nghiệm đo đạc chu kỳ phát GPS phần cứng và cơ chế API BusMap.

| STT | Tên tệp hiện tại | Kích thước | Nội dung khoa học | Thư mục đích đề xuất |
| :---: | :--- | :---: | :--- | :--- |
| 1 | `experiments/eda_daytype_and_hour_regimes.py` | 16,600 B | Nghiên cứu phân phối ngày trong tuần (T2-T6 vs T7 vs CN) và 18 khung giờ giao thông. | `experiments/eda/eda_daytype_and_hour_regimes.py` |
| 2 | `experiments/eda_route_90_underperformance.py` | 2,361 B | Điều tra nguyên nhân giảm độ chính xác trên tuyến 90 (đặc thù tuyến sân bay). | `experiments/eda/eda_route_90_underperformance.py` |
| 3 | `experiments/eda_silver_tier_comprehensive.py` | 11,786 B | Đánh giá độ phủ không gian - thời gian và cân bằng tập Train/Test trên tầng Silver. | `experiments/eda/eda_silver_tier_comprehensive.py` |
| 4 | `experiments/eda_step_3_1_baseline_anomalies.py` | 16,508 B | Điều tra sai lệch phân phối P50 đa trạm trên tầng phân đoạn chuyến đi. | `experiments/eda/eda_step_3_1_baseline_anomalies.py` |
| 5 | `experiments/eda_step_3_2_feature_store.py` | 10,372 B | Kiểm toán chất lượng dữ liệu 15 triệu bản ghi trên Gold Feature Store. | `experiments/eda/eda_step_3_2_feature_store.py` |
| 6 | `experiments/eda_step_3_4_ml_diagnostics.py` | 1,044 B | Chẩn đoán phân chia dữ liệu Train/Test theo chuỗi thời gian. | `experiments/eda/eda_step_3_4_ml_diagnostics.py` |
| 7 | `experiments/eda_tier0_and_tier3_root_causes.py` | 3,802 B | Phân tích nguyên nhân tỷ lệ Tier 0 và Tier 3 trên ma trận thời gian di chuyển. | `experiments/eda/eda_tier0_and_tier3_root_causes.py` |
| 8 | `experiments/audit_vehicle_gps_stream_continuity.py` | 13,760 B | Kiểm định tính liên tục chuỗi GPS của từng xe, trôi trạm và hành vi tại 2 đầu bến. | `experiments/eda/audit_vehicle_gps_stream_continuity.py` |
| 9 | `experiments/verify_frenet_projection_step_by_step.py` | 7,743 B | Harness kiểm tra từng bước phép chiếu Frenet trên các tuyến mẫu (01, 02, 05). | `experiments/eda/verify_frenet_projection_step_by_step.py` |
| 10 | `experiments/audit_api_parity_vehicle_vs_route.py` | 5,047 B | Đối soát tính nhất quán giữa API `vehicle_hn/get` và `route_bus_gps` của BusMap. | `experiments/hardware_gps/audit_api_parity_vehicle_vs_route.py` |
| 11 | `experiments/audit_hardware_gps_update_interval.py` | 7,925 B | Thực nghiệm đo chu kỳ phát GPS phần cứng trên các xe buýt đang chạy thực tế. | `experiments/hardware_gps/audit_hardware_gps_update_interval.py` |
| 12 | `experiments/audit_route_40_crawler.py` | 1,319 B | Rà quét dải biển số xe để tìm kiếm ID phương tiện tuyến 40 trên hệ thống BusMap. | `experiments/hardware_gps/audit_route_40_crawler.py` |
| 13 | `experiments/test_consecutive_polls.py` | 4,537 B | Đo chu kỳ ping phần cứng qua cửa sổ thăm dò 150 giây liên tục. | `experiments/hardware_gps/test_consecutive_polls.py` |
| 14 | `experiments/test_route_query_vs_vehicle_query.py` | 2,143 B | Kiểm tra cơ chế chống crawler, tham số proof/epoch và header của API BusMap. | `experiments/hardware_gps/test_route_query_vs_vehicle_query.py` |

---

#### Bảng 5: Các tệp Thực nghiệm Lỗi thời trong Thư mục gốc `experiments/` — ĐỀ XUẤT: XÓA SỔ (1 tệp + 2 cache)

| STT | Tên tệp | Kích thước | Nguyên nhân phế bỏ kỹ thuật | Đề xuất |
| :---: | :--- | :---: | :--- | :---: |
| 1 | `experiments/verify_timbus_single_anchor_parity.py` | 13,959 B | Thực nghiệm kết nối trực tiếp cổng 9149 TimBus và giải mã gói tin để đối soát BusMap. Vì TimBus đã bị khai tử hoàn toàn, mã thực nghiệm này không còn giá trị. | **XÓA BỎ** |
| 2-3 | `experiments/__pycache__/*.pyc` (2 tệp) | 10 KB | Bytecode cache của `test_consecutive_polls` và `test_route_query_vs_vehicle_query`. | **XÓA BỎ** |

---

### 3.3. Phân tích Toàn bộ Thư mục `experiments/timbus/` — ĐỀ XUẤT: XÓA SỔ HOÀN TOÀN (14 tệp + 4 cache)

Toàn bộ thư mục `experiments/timbus/` được sinh ra trong giai đoạn khảo sát và giải mã giao thức nhị phân của ứng dụng TimBus (Bình Anh GPS). Theo quyết định kiến trúc tại **Spec 04**, hệ thống đã loại bỏ 100% TimBus để chuyển sang kiến trúc BusMap Rời rạc. Toàn bộ thư mục này trở thành nợ kỹ thuật (dead code) và phải được xóa sổ sạch sẽ.

| STT | Tên tệp | Kích thước | Mô tả nội dung kỹ thuật | Đề xuất |
| :---: | :--- | :---: | :--- | :---: |
| 1 | `experiments/timbus/timbus_tracker.py` | 15,432 B | Thư viện client giải mã gói tin nhị phân và mã hóa XOR cổng 9149 TimBus. | **XÓA BỎ** |
| 2 | `experiments/timbus/audit_realtime_parity_timbus_vs_busmap.py` | 12,239 B | Script đối soát tọa độ TimBus với BusMap theo thời gian thực. | **XÓA BỎ** |
| 3 | `experiments/timbus/check_missing_buses.py` | 1,236 B | Tìm kiếm các xe có trong TimBus nhưng thiếu trong BusMap. | **XÓA BỎ** |
| 4 | `experiments/timbus/esri_deviation_inspector.py` | 30,741 B | Bộ tạo trang HTML hiển thị độ lệch tọa độ giữa TimBus và BusMap. | **XÓA BỎ** |
| 5 | `experiments/timbus/esri_deviation_inspector.html` | 114,814 B | Trang HTML tĩnh chứa dữ liệu trực quan hóa sai số vị trí TimBus. | **XÓA BỎ** |
| 6 | `experiments/timbus/inspect_busmap_unmatched.py` | 1,058 B | Script rà quét các bản ghi không khớp danh mục TimBus. | **XÓA BỎ** |
| 7 | `experiments/timbus/inspect_parity_details.py` | 2,460 B | Trích xuất chi tiết kết quả đối soát parity từ file JSON. | **XÓA BỎ** |
| 8 | `experiments/timbus/print_outliers.py` | 1,002 B | In ra các trường hợp ngoại lai có sai số khoảng cách cực lớn giữa TimBus và BusMap. | **XÓA BỎ** |
| 9 | `experiments/timbus/recalc_true_leads.py` | 2,400 B | Tính toán lại khoảng cách dẫn đầu (station lead distance) dựa trên TimBus. | **XÓA BỎ** |
| 10 | `experiments/timbus/reproject_dual_direction.py` | 2,147 B | Thử nghiệm chiếu tọa độ TimBus theo 2 chiều để phát hiện xe chạy ngược. | **XÓA BỎ** |
| 11 | `experiments/timbus/scan_station_ids.py` | 714 B | Dò quét bảng mã định danh trạm dừng nội bộ của server TimBus. | **XÓA BỎ** |
| 12 | `experiments/timbus/test_live_bridge.py` | 2,978 B | Thử nghiệm cầu nối truyền dữ liệu trực tiếp từ TimBus vào EtaServingService cũ. | **XÓA BỎ** |
| 13 | `experiments/timbus/test_st_probe.py` | 730 B | Thăm dò socket gửi gói tin ping đến cổng 9149 của `timbus.vn`. | **XÓA BỎ** |
| 14 | `experiments/timbus/verify_single_anchor_results.json` | 1,498 B | File JSON lưu kết quả đối soát viễn trắc TimBus cũ. | **XÓA BỎ** |
| 15-18 | `experiments/timbus/__pycache__/*.pyc` (4 tệp) | 46 KB | Toàn bộ cache bytecode trong `experiments/timbus/__pycache__/`. | **XÓA BỎ** |

---

## 4. BỨC TRANH TOÀN CẢNH SAU TINH GỌN (TO-BE ARCHITECTURE)

Sau khi hoàn tất đợt dọn dẹp và điều phối theo đặc tả này, cấu trúc các thư mục phụ trợ sẽ hoàn toàn trong sạch, tường minh và đạt chuẩn công nghiệp:

```text
Bus_tracking/
│
├── scripts/                                       # CHỈ CHỨA CÁC SCRIPT VẬN HÀNH PIPELINE & LAKEHOUSE
│   ├── audit_silver_lakehouse_purity.py           # Module 2: Kiểm toán Silver Lakehouse
│   ├── build_baseline_travel_time_matrix.py       # Module 3: Xây dựng Baseline Matrix
│   ├── build_fact_route_tomtom_incidents.py       # Module 1: Chiếu dữ liệu TomTom Incidents
│   ├── build_gold_feature_store.py                # Module 3: Trích xuất Gold Feature Store
│   ├── bulk_ingest_all_bus_pings.py               # Module 1: Nạp telemetry vào SQLite
│   ├── cloud_crawler_step.py                      # CI/CD: Step crawler GitHub Actions
│   ├── daily_catalog_refresh.py                   # Ops: Cronjob cập nhật danh mục BusMap
│   ├── ingest_canonical_busmap_master.py          # Module 1: Nạp Canonical Route/Station/Shape
│   ├── parallel_multi_route_projector.py          # Module 1: 1D Frenet Projection song song
│   ├── run_production_crawler.py                  # Ops: Runner crawler 24/7
│   ├── start_crawler.bat                          # Ops: File khởi động Windows
│   ├── start_crawler_background.vbs               # Ops: File khởi động ngầm
│   ├── sync_from_hf.py                            # Ops: Đồng bộ từ Hugging Face
│   ├── train_and_evaluate_ml_eta.py               # Module 3: Huấn luyện XGBoost ETA
│   └── verify_canonical_architecture.py           # Verification: Kiểm toán toàn vẹn CSDL & Lakehouse
│
├── tests/                                         # TOÀN BỘ CÁC BỘ KIỂM THỬ HỘP ĐEN (UNIFIED TEST SUITE)
│   ├── test_busmap_discrete.py                    # Smoke test & Contract test BusMap Discrete
│   ├── test_discrete_busmap_tracking_blackbox.py  # (Mới chuyển từ scripts/) Bộ kiểm thử nghiệm thu Spec 04
│   ├── test_esri_satellite_blackbox.py            # (Mới chuyển từ scripts/) Bộ kiểm thử bản đồ Esri
│   ├── test_route_shape_and_stations_blackbox.py  # (Mới chuyển từ scripts/) Bộ kiểm thử nghiệm thu Spec 05
│   └── test_system_config_blackbox.py             # (Mới chuyển từ scripts/) Bộ kiểm thử cấu hình hệ thống
│
└── experiments/                                   # LƯU TRỮ NGHIÊN CỨU DỮ LIỆU & KIỂM ĐỊNH PHẦN CỨNG
    ├── eda/                                       # Phân tích khám phá dữ liệu Lakehouse (7 scripts EDA)
    │   ├── audit_vehicle_gps_stream_continuity.py
    │   ├── eda_daytype_and_hour_regimes.py
    │   ├── eda_route_90_underperformance.py
    │   ├── eda_silver_tier_comprehensive.py
    │   ├── eda_step_3_1_baseline_anomalies.py
    │   ├── eda_step_3_2_feature_store.py
    │   ├── eda_step_3_4_ml_diagnostics.py
    │   ├── eda_tier0_and_tier3_root_causes.py
    │   └── verify_frenet_projection_step_by_step.py
    │
    └── hardware_gps/                              # Nghiên cứu thực nghiệm chu kỳ GPS & API BusMap
        ├── audit_api_parity_vehicle_vs_route.py
        ├── audit_hardware_gps_update_interval.py
        ├── audit_route_40_crawler.py
        ├── test_consecutive_polls.py
        └── test_route_query_vs_vehicle_query.py
```

---

## 5. HƯỚNG DẪN THỰC THI CHO `@leaf_coder` (MIGRATION EXECUTION PROTOCOL)

Tuân thủ nghiêm ngặt nguyên tắc phân quyền của `AGENTS.md`: `@architect` chỉ lập đặc tả, nghiêm cấm tự ý xóa sửa mã nguồn; `@leaf_coder` là tác nhân duy nhất thực thi các thao tác di chuyển và xóa tệp trong workspace.

### Bước 1: Tạo các thư mục đích cần thiết
```powershell
New-Item -ItemType Directory -Force -Path "experiments/eda"
New-Item -ItemType Directory -Force -Path "experiments/hardware_gps"
```

### Bước 2: Di chuyển các bộ kiểm thử hộp đen từ `scripts/` sang `tests/`
```powershell
# Di chuyển 4 bộ test sang tests/ (ghi đè file stub nếu cần)
Move-Item -Force -Path "scripts/test_discrete_busmap_tracking_blackbox.py" -Destination "tests/"
Move-Item -Force -Path "scripts/test_esri_satellite_blackbox.py" -Destination "tests/"
Move-Item -Force -Path "scripts/test_route_shape_and_stations_blackbox.py" -Destination "tests/"
Move-Item -Force -Path "scripts/test_system_config_blackbox.py" -Destination "tests/"
```

### Bước 3: Di chuyển các script EDA và thực nghiệm vào đúng nhóm
```powershell
# Nhóm EDA
Move-Item -Force -Path "experiments/eda_daytype_and_hour_regimes.py" -Destination "experiments/eda/"
Move-Item -Force -Path "experiments/eda_route_90_underperformance.py" -Destination "experiments/eda/"
Move-Item -Force -Path "experiments/eda_silver_tier_comprehensive.py" -Destination "experiments/eda/"
Move-Item -Force -Path "experiments/eda_step_3_1_baseline_anomalies.py" -Destination "experiments/eda/"
Move-Item -Force -Path "experiments/eda_step_3_2_feature_store.py" -Destination "experiments/eda/"
Move-Item -Force -Path "experiments/eda_step_3_4_ml_diagnostics.py" -Destination "experiments/eda/"
Move-Item -Force -Path "experiments/eda_tier0_and_tier3_root_causes.py" -Destination "experiments/eda/"
Move-Item -Force -Path "experiments/audit_vehicle_gps_stream_continuity.py" -Destination "experiments/eda/"
Move-Item -Force -Path "experiments/verify_frenet_projection_step_by_step.py" -Destination "experiments/eda/"

# Nhóm Hardware GPS & API
Move-Item -Force -Path "experiments/audit_api_parity_vehicle_vs_route.py" -Destination "experiments/hardware_gps/"
Move-Item -Force -Path "experiments/audit_hardware_gps_update_interval.py" -Destination "experiments/hardware_gps/"
Move-Item -Force -Path "experiments/audit_route_40_crawler.py" -Destination "experiments/hardware_gps/"
Move-Item -Force -Path "experiments/test_consecutive_polls.py" -Destination "experiments/hardware_gps/"
Move-Item -Force -Path "experiments/test_route_query_vs_vehicle_query.py" -Destination "experiments/hardware_gps/"
```

### Bước 4: Xóa sạch toàn bộ tệp tin lỗi thời trong `scripts/`
```powershell
Remove-Item -Force -Path @(
    "scripts/test_dead_reckoning_kinematics.js",
    "scripts/test_marker_tweening.js",
    "scripts/test_goal1_realtime_timbus_blackbox.py",
    "scripts/test_hybrid_bus_tracking_parity.py",
    "scripts/test_kinematic_smoothness_and_jitter.py",
    "scripts/test_timbus_realtime_serving.py",
    "scripts/test_anti_cheat_remediation.py",
    "scripts/test_ground_truth_and_night_mode.py",
    "scripts/verify_eta_serving.py",
    "scripts/verify_online_serving_pipeline.py",
    "scripts/verify_web_app_demo.py"
)
Remove-Item -Recurse -Force -Path "scripts/__pycache__"
```

### Bước 5: Xóa sạch toàn bộ mã nguồn TimBus trong `experiments/`
```powershell
Remove-Item -Force -Path "experiments/verify_timbus_single_anchor_parity.py"
Remove-Item -Recurse -Force -Path "experiments/timbus"
Remove-Item -Recurse -Force -Path "experiments/__pycache__"
```

---

## 6. TIÊU CHÍ NGHIỆM THU ĐỘC LẬP CHO `@blind_tester` (ACCEPTANCE CRITERIA)

Sau khi `@leaf_coder` thực thi xong, `@blind_tester` chạy độc lập các lệnh kiểm tra sau để nghiệm thu dứt điểm:

1. **Kiểm tra Suite Test tại `tests/` đạt 100% PASS:**
   ```powershell
   python -m pytest tests/ -v
   ```
   *Yêu cầu bắt buộc:* Toàn bộ các bài test (`test_busmap_discrete.py`, `test_discrete_busmap_tracking_blackbox.py`, `test_esri_satellite_blackbox.py`, `test_route_shape_and_stations_blackbox.py`, `test_system_config_blackbox.py`) phải chạy thành công không có bất kỳ lỗi nào.

2. **Kiểm tra `scripts/` không còn tệp `test_*` hay `verify_*` lỗi thời:**
   ```powershell
   Get-ChildItem -Path scripts -Filter "test_*"
   ```
   *Yêu cầu bắt buộc:* Kết quả trả về rỗng (0 tệp).

3. **Kiểm tra thư mục `experiments/timbus/` hoàn toàn biến mất:**
   ```powershell
   Test-Path "experiments/timbus"
   ```
   *Yêu cầu bắt buộc:* Kết quả trả về `False`.
