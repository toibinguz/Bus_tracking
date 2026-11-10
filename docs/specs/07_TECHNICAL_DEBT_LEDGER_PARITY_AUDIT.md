# SPEC-07: ĐỐI SOÁT & KIỂM TOÁN SỰ SAI LỆCH CỦA SỔ CÁI NỢ KỸ THUẬT (TD-01 ĐẾN TD-64)
> **Historical audit note (2026-11-10):** References to deleted tests or retired telemetry artefacts are historical. The active ledger is [docs/04_TECHNICAL_DEBT_AND_OPEN_ISSUES_LEDGER.md](../04_TECHNICAL_DEBT_AND_OPEN_ISSUES_LEDGER.md).
## Document ID: `07_TECHNICAL_DEBT_LEDGER_PARITY_AUDIT`

- **Tác giả:** `@architect`
- **Người thẩm định:** `@orchestrator`
- **Tài liệu đối soát:** [`docs/04_TECHNICAL_DEBT_AND_OPEN_ISSUES_LEDGER.md`](../04_TECHNICAL_DEBT_AND_OPEN_ISSUES_LEDGER.md)
- **Căn cứ kiến trúc hiện hành:**
  - [`docs/specs/04_BUSMAP_ONLY_DISCRETE_TRACKING_SPEC.md`](04_BUSMAP_ONLY_DISCRETE_TRACKING_SPEC.md) (SPEC-04: Bãi bỏ 100% TimBus, chuyển sang BusMap Rời rạc)
  - [`docs/specs/05_ROUTE_SHAPE_AND_STATION_INTERACTIONS_SPEC.md`](05_ROUTE_SHAPE_AND_STATION_INTERACTIONS_SPEC.md) (SPEC-05: Tim tuyến, trạm dừng đánh số trên nền vệ tinh Esri)
  - [`docs/specs/06_CLEANUP_SCRIPTS_AND_EXPERIMENTS_AUDIT.md`](06_CLEANUP_SCRIPTS_AND_EXPERIMENTS_AUDIT.md) (SPEC-06: Tinh giản scripts và xóa bỏ toàn bộ mã TimBus / mô phỏng 60 FPS)
- **Ngày ban hành:** 2026-11-09
- **Trạng thái:** APPROVED / READY FOR GOVERNANCE ALIGNMENT

---

## 1. BỐI CẢNH & CĂN NGUYÊN SAI LỆCH KIẾN TRÚC (AUDIT CONTEXT & ROOT CAUSE)

### 1.1. Bước ngoặt Kiến trúc tại TD-62 (Spec-04)
Hệ thống đã trải qua một cuộc chuyển dịch chiến lược mang tính bước ngoặt:
- **Trước TD-62:** Dự án theo đuổi mô hình viễn trắc kép lai ghép (Hybrid TimBus + BusMap) kết hợp công nghệ nội suy động học 60 FPS trên trình duyệt (Dead Reckoning, Continuous Reconciliation, Linear/Hermite Tweening, FSM Fallback, TCP socket cổng 9149, XOR cipher 2 khóa, binary struct codec).
- **Từ TD-62 trở đi:** Người dùng ra chỉ thị dứt khoát áp dụng triết lý **Simplicity First**: Bãi bỏ 100% TimBus và bãi bỏ 100% thuật toán nội suy 60 FPS. Toàn bộ backend được tinh giản về `busmap_service.py` và `app.py`, frontend dùng `app.js` hiển thị vị trí xe giật cục rời rạc (chu kỳ 15 giây) trực tiếp trên bản đồ ảnh vệ tinh **Esri World Imagery** cùng tim tuyến và trạm dừng chính xác (Spec-05).

### 1.2. Hiện trạng Sai lệch trong Sổ cái `docs/04_TECHNICAL_DEBT_AND_OPEN_ISSUES_LEDGER.md`
Khi rà soát toàn bộ 64 mục nợ kỹ thuật (TD-01 đến TD-64), phát hiện **sự lệch pha nghiêm trọng giữa tài liệu và thực tế mã nguồn**:

1. **Sai lệch Loại 1: "Nợ ảo đang mở" (Phantom Open Debts):**
   Có **7 mục nợ kỹ thuật đang mở (`- [ ]`)** (TD-33, TD-34, TD-35, TD-36, TD-38, TD-39, TD-40) đặt ra các yêu cầu kiểm soát, lập bảng ánh xạ trạm (`Crosswalk Table`), xây dựng máy trạng thái fallback, hoặc theo dõi tỷ lệ mất dấu xe cho **hệ thống TimBus**. 
   *Thực tế:* Công nghệ TimBus đã bị khai tử hoàn toàn. Việc tiếp tục để các mục này ở trạng thái `[ ]` tạo cảm giác sai lệch rằng hệ thống vẫn còn nợ chưa trả đối với TimBus.

2. **Sai lệch Loại 2: "Thành tựu đã bị phế bỏ" (Superseded Implementations):**
   Có **6 mục đã đánh dấu `[x]`** (TD-46, TD-52, TD-53, TD-59, TD-60, TD-61) ghi nhận các giải pháp hoàn thành thuật toán 60 FPS Tweening, Dead Reckoning, `timbus_bridge.py`, TimBus client ID, v.v.
   *Thực tế:* Toàn bộ các file mã nguồn này (`timbus_bridge.py`, `map_manager.js`, `smooth_render_controller.js`, `test_dead_reckoning_kinematics.js`) đã bị loại bỏ hoặc đưa vào danh sách xóa sổ tại Spec-06. Nếu chỉ đọc các mục này mà không xem TD-62, kỹ sư sẽ bị ngộ nhận rằng hệ thống hiện tại đang vận hành bằng TimBus 60 FPS.

3. **Sai lệch Loại 3: "Tham chiếu Module đã xóa" (Broken References in Serving):**
   Các mục TD-26, TD-28, TD-30, TD-31 mô tả engine serving trực tuyến cũ (`OnlineFeatureExtractor`, `EtaServingService`, `contract.py`, `api_routes.py`). Các file này đã được tinh giản thành `busmap_service.py` và `app.py`.

---

## 2. BẢNG PHÂN LOẠI TỔNG HỢP 64 MỤC NỢ KỸ THUẬT

Tổng số mục kiểm toán: **64 mục** (TD-01 $\to$ TD-64).

| Nhóm phân loại | Số lượng | Danh sách mã TD | Đề xuất hành động chuẩn hóa |
| :--- | :---: | :--- | :--- |
| **Nhóm A: Nợ TimBus đang mở bị VÔ HIỆU HÓA HOÀN TOÀN** | **7** | `TD-33`, `TD-34`, `TD-35`, `TD-36`, `TD-38`, `TD-39`, `TD-40` | Đổi nhãn từ `[ ]` thành `[x]` kèm tag `[HỦY BỎ / VOID BY SPEC-04]`. |
| **Nhóm B: Giải pháp 60 FPS / TimBus đã xong nhưng BỊ PHẾ BỎ BỞI SPEC-04** | **6** | `TD-46`, `TD-52`, `TD-53`, `TD-59`, `TD-60`, `TD-61` | Giữ `[x]`, bổ sung nhãn cảnh báo `[ĐÃ BÃI BỎ / SUPERSEDED BY SPEC-04]`. |
| **Nhóm C: Module Serving cũ cần TÁI ĐỊNH HƯỚNG PHẠM VI** | **4** | `TD-26`, `TD-28`, `TD-30`, `TD-31` | Cập nhật ghi chú ranh giới giữa bản cũ và backend tinh giản (`busmap_service.py`). |
| **Nhóm D1: Nợ kỹ thuật ĐANG MỞ CÒN NGUYÊN HIỆU LỰC (Cần theo dõi sát)** | **14** | `TD-12`, `TD-13`, `TD-14`, `TD-15`, `TD-16`, `TD-17`, `TD-25`, `TD-27`, `TD-29`, `TD-54`, `TD-55`, `TD-56`, `TD-57`, `TD-64` | Giữ nguyên `[ ]`, bảo lưu quy tắc kiểm soát và tiêu chí rủi ro. |
| **Nhóm D2: Nợ kỹ thuật ĐÃ XỬ LÝ & BẢO LƯU GIÁ TRỊ LỊCH SỬ** | **33** | `TD-01` $\to$ `TD-11`, `TD-18` $\to$ `TD-24`, `TD-32`, `TD-37`, `TD-41` $\to$ `TD-45`, `TD-47` $\to$ `TD-51`, `TD-58`, `TD-62`, `TD-63` | Giữ nguyên `[x]` làm mốc lịch sử phát triển sạch sẽ. |
| **TỔNG CỘNG** | **64** | | |

---

## 3. ĐỐI SOÁT CHI TIẾT CÁC MỤC SAI LỆCH VÀ PHƯƠNG ÁN ĐIỀU CHỈNH

### 3.1. Nhóm A: 7 mục Nợ Kỹ thuật Đang Mở (`[ ]`) đã bị Vô hiệu hóa bởi Spec-04

Các mục này trước đây được lập ra để chuẩn bị cho việc tích hợp TimBus vào hệ thống. Do hệ thống đã **bãi bỏ 100% TimBus**, việc giữ các mục này ở trạng thái đang mở (`[ ]`) là hoàn toàn sai lệch thực tế.

| Mã TD | Tiêu đề hiện tại trong Sổ cái | Hiện trạng thực tế codebase | Phân tích sai lệch & Đề xuất điều chỉnh |
| :---: | :--- | :--- | :--- |
| **TD-33** | Sự phân kỳ danh bạ và mã trạm giữa TimBus vs. BusMap Canonical (Yêu cầu lập bảng ánh xạ Crosswalk Table). | Không còn mã nguồn nào truy vấn TimBus hay StationID của TimBus. CSDL chỉ dùng duy nhất `canonical_station_master`. | **ĐÃ VÔ HIỆU HÓA**. Chuyển sang `[x]` kèm nhãn: `[HỦY BỎ / VOID BY SPEC-04: Đã bãi bỏ 100% TimBus, không sử dụng StationID TimBus, không cần Crosswalk Table]`. |
| **TD-34** | Đóng băng ranh giới Tầng Thu thập 24/7 & Loại trừ TimBus khỏi Lakehouse Ingestion Pipeline. | Tầng Ingestion 100% thuần BusMap; TimBus bị loại bỏ khỏi toàn bộ hệ thống (không chỉ riêng Lakehouse). | **ĐÃ HOÀN TẤT & VƯỢT MỨC**. Chuyển sang `[x]` kèm nhãn: `[ĐÃ ĐÓNG BĂNG & XÓA SỔ: TimBus bị loại trừ 100% khỏi toàn bộ dự án theo Spec-04]`. |
| **TD-35** | Nguy cơ xung đột viễn trắc và trôi dạt đồng hồ nếu lai ghép hai nguồn (TimBus + BusMap). | Không còn logic lai ghép viễn trắc nào. Nguồn viễn trắc duy nhất là API HTTPS `route_bus_gps` của BusMap. | **ĐÃ VÔ HIỆU HÓA**. Chuyển sang `[x]` kèm nhãn: `[HỦY BỎ / VOID BY SPEC-04: Triệt tiêu nguy cơ do chỉ dùng duy nhất 1 nguồn BusMap]`. |
| **TD-36** | Ranh giới Tiếp thu Chọn lọc của TimBus (tiếp thu 60 FPS trong map_manager.js, lưu timbus_tracker.py làm oracle). | Spec-04 bãi bỏ 60 FPS tweening; Spec-06 xóa bỏ toàn bộ thư mục `experiments/timbus/`. | **ĐÃ HỦY BỎ TOÀN DIỆN**. Chuyển sang `[x]` kèm nhãn: `[HỦY BỎ / REVERTED BY SPEC-04 & SPEC-06: Bỏ hoàn toàn thuật toán 60 FPS và xóa sạch experiments/timbus/]`. |
| **TD-38** | Tỷ lệ mất dấu xe trên cổng TimBus (17.1% - 22.9%) & Cài đặt máy trạng thái Fallback State Machine. | Không kết nối TimBus, không còn bài toán mất dấu xe trên cổng 9149, không cần Fallback State Machine. | **ĐÃ VÔ HIỆU HÓA**. Chuyển sang `[x]` kèm nhãn: `[HỦY BỎ / VOID BY SPEC-04: Đã dừng kết nối cổng 9149 TimBus]`. |
| **TD-39** | Sự phụ thuộc động vào tham số trạm lọc (`FleId`) của máy chủ TimBus. | Không còn gửi bất kỳ request nào đến máy chủ TimBus. | **ĐÃ VÔ HIỆU HÓA**. Chuyển sang `[x]` kèm nhãn: `[HỦY BỎ / VOID BY SPEC-04: Đã chấm dứt tương tác với server TimBus]`. |
| **TD-40** | Các xe không ghép cặp thành công giữa TimBus và BusMap (Unmatched Vehicles 17% - 35%). | Không còn đối soát TimBus - BusMap. Danh mục xe được lấy tất định từ API BusMap. | **ĐÃ VÔ HIỆU HÓA**. Chuyển sang `[x]` kèm nhãn: `[HỦY BỎ / VOID BY SPEC-04: Đã loại bỏ hoàn toàn cơ chế ghép cặp TimBus]`. |

---

### 3.2. Nhóm B: 6 mục Đã Hoàn Tất (`[x]`) nhưng Giải pháp Đã Bị Bãi Bỏ trong Kiến Trúc Mới

Các mục này ghi nhận việc triển khai thành công các giải pháp kỹ thuật trước đây. Tuy nhiên, các giải pháp này sau đó đã bị User và Architect yêu cầu dỡ bỏ sạch sẽ (Spec-04). Cần gắn nhãn cảnh báo để người đọc không nhầm lẫn rằng các đoạn mã này vẫn đang vận hành.

| Mã TD | Giải pháp đã ghi nhận trong Sổ cái | Hiện trạng thực tế codebase hiện tại | Đề xuất Nhãn cảnh báo bổ sung |
| :---: | :--- | :--- | :--- |
| **TD-46** | Đã lập trình thuật toán `animateMarkerTo` dùng `requestAnimationFrame`, Lerp + Ease-out quad 60 FPS. | Toàn bộ `requestAnimationFrame` và hàm `animateMarkerTo` đã bị loại bỏ khỏi `static/app.js`. Bản đồ cập nhật giật cục rời rạc 15s (`marker.setLatLng`). | Bổ sung tag: `[ĐÃ BÃI BỎ / SUPERSEDED BY SPEC-04: Khai tử thuật toán 60 FPS Tweening, chuyển sang Discrete Stepped Updates 15s]`. |
| **TD-52** | Tích hợp Viễn trắc TimBus 5s (`timbus_bridge.py`) và nội suy mượt Linear Tweening 60 FPS. | File `timbus_bridge.py` đã bị xóa hoàn toàn khỏi codebase; web demo không còn phụ thuộc nhịp 5s TimBus. | Bổ sung tag: `[ĐÃ BÃI BỎ / SUPERSEDED BY SPEC-04: Khai tử timbus_bridge.py và kết nối 5s TimBus]`. |
| **TD-53** | Giải thuật Điều hòa Vi sai Động lượng Đón đầu (Dead Reckoning Kinematics & Continuous Reconciliation). | Spec-04 cấm triệt để Dead Reckoning. Script `test_dead_reckoning_kinematics.js` bị xóa theo Spec-06. | Bổ sung tag: `[ĐÃ BÃI BỎ / SUPERSEDED BY SPEC-04: Bãi bỏ 100% thuật toán Dead Reckoning và Continuous Reconciliation]`. |
| **TD-59** | Triển khai Clean-Slate Mục tiêu 1 — Viễn trắc Thời gian Thực & Bộ máy Nội suy TimBus 60 FPS. | Toàn bộ các module `TimBusCipherEngine`, `TimBusBinaryCodec`, `FailoverFSM` đã bị dỡ bỏ sạch sẽ. Script `test_goal1_realtime_timbus_blackbox.py` bị xóa. | Bổ sung tag: `[ĐÃ BÃI BỎ / SUPERSEDED BY SPEC-04 & SPEC-06: Clean-slate TimBus 60 FPS đã được thay thế bởi BusMap Discrete]`. |
| **TD-60** | Chuẩn hóa Client ID TimBus (`0x001B02F5`) và sửa bộ lọc lặp trong `smooth_render_controller.js`. | Không còn sử dụng Client ID TimBus; file `smooth_render_controller.js` đã bị loại bỏ. | Bổ sung tag: `[ĐÃ BÃI BỎ / SUPERSEDED BY SPEC-04: Không còn sử dụng Client ID TimBus]`. |
| **TD-61** | Khắc phục lỗi lặp thẻ xe trên UI trong `smooth_render_controller.js`. | Giao diện đã được viết lại tối giản trong `static/app.js` (không còn `smooth_render_controller.js`). | Bổ sung tag: `[ĐÃ BÃI BỎ / SUPERSEDED BY SPEC-04: Component smooth_render_controller.js đã được thay thế hoàn toàn]`. |

---

### 3.3. Nhóm C: 4 mục Tham Chiếu Module Cũ cần Tái Định Hướng Phạm Vi

| Mã TD | Tham chiếu module cũ | Hiện trạng thực tế | Hướng điều chỉnh tài liệu |
| :---: | :--- | :--- | :--- |
| **TD-26** | Tham chiếu `OnlineFeatureExtractor` & `EtaServingService` tại `step_3_4`. | Backend phục vụ trực tiếp hiện tại là `busmap_service.py` và `app.py`. | Ghi chú rõ: `TD-26` là mốc nghiệm thu logic trích xuất đặc trưng phục vụ đánh giá Train/Serve Skew cho pipeline ML; không áp dụng cho web demo tối giản hiện hành. |
| **TD-28** | Tham chiếu hợp đồng Pydantic `contract.py`, `cache_manager.py`, `api_routes.py`. | Web demo đã tinh giản thành `module_3_bus_eta_prediction/step_3_5_web_demo/app.py` thuần FastAPI trực tiếp. | Ghi chú rõ: Contract phức tạp đã được thay thế bởi API tối giản theo Spec-04/05 (`/api/health`, `/api/routes`, `/api/live-vehicles`, `/api/route-shape`, `/api/route-stations`). |
| **TD-30** | Tham chiếu Máy trạng thái Ca đêm trong `static/js/app.js` và `api_routes.py`. | Giao diện hiện tại dùng `static/app.js` và `static/style.css`. | Ghi chú rõ: Giao diện web mới tiếp thu triết lý không hiển thị xe khi ca đêm kết thúc, nhưng lược bỏ logic FSM phức tạp để giữ sự tối giản. |
| **TD-31** | Mở rộng ML residual cho các tuyến ngoài Tuyến 02 (`eta_serving_service.py`, `eta_inference_engine.py`). | Hai file trên không còn trong web serving. Pipeline huấn luyện ML nằm tại `step_3_3_machine_learning_models`. | Tái định hướng: Chuyển phạm vi sang Module 3 Offline Pipeline (huấn luyện mở rộng XGBoost cho toàn bộ 48 tuyến). |

---

### 3.4. Nhóm D: 14 mục Nợ Kỹ thuật Đang Mở (`- [ ]`) CÒN NGUYÊN HIỆU LỰC

Đây là **14 khoản nợ kỹ thuật thực tế và cốt lõi nhất** của dự án, hoàn toàn độc lập với TimBus, liên quan trực tiếp đến độ sạch của Lakehouse, thuật toán phân đoạn chuyến đi, ma trận Baseline P50, và sai lệch hình học trạm dừng:

1. **`TD-12` (Bản vá hình học tuyến E11, E11CT, 123):** Dữ liệu gốc BusMap có các đoạn chập ngược chiều, cần tiếp tục bảo lưu quy tắc kiểm soát khi nạp GeoJSON mới.
2. **`TD-13` (Lỗ thủng không gian $300\text{s} < \Delta t \le 1800\text{s}$ khi xe detour):** Phục vụ thuật toán nối chuyến `segment_trajectory_into_trips` trong Lakehouse.
3. **`TD-14` (4 tuyến 67, E11, 40, 42 chạy lệch tim đường $> 35\text{m}$):** Cần duy trì quy tắc `route_avg_mps` (Tier 3) trong ma trận Baseline.
4. **`TD-15` (Tuyến 67 và 92 ngoài vùng phủ TomTom Incidents):** Duy trì `LEFT JOIN` và `COALESCE(delay, 0)` trong Feature Store.
5. **`TD-16` (Chu kỳ mẫu lịch sử $\Delta t \approx 80\text{s}$, cấm mô hình hóa micro-dwell time):** Nguyên lý bất biến cho mô hình hóa thời gian dừng trạm.
6. **`TD-17` (Freelist Pages trong CSDL SQLite):** Cần chạy `VACUUM` cho file `data/hanoi_bus_system.db` trước khi đóng gói sản phẩm.
7. **`TD-25` (Tuyến 90 kém hơn Baseline do Covariate Shift giữa Train và Test):** Nghiên cứu tái huấn luyện có trọng số thời gian cho Tuyến 90.
8. **`TD-27` (Cực kỳ quan trọng — Bất đối xứng giữa 2 API BusMap `vehicle_hn/get` vs `route_bus_gps`):**
   - Hoán vị tọa độ: `vehicle_hn/get` đảo `Lat/Lng`, trong khi `route_bus_gps` chuẩn `Lat/Lng`.
   - Lọc ngầm phía server: `route_bus_gps` tự động giấu xe đỗ bãi (`direction = -1`) hoặc xe đi detour quá xa.
   - Bắt buộc bảo lưu nguyên tắc: Crawler 24/7 dùng `vehicle_hn/get`; Web Live Serving dùng `route_bus_gps`.
9. **`TD-29` (RAM Cache vs Distributed Redis Cache):** Hiện dùng memory cache cho demo; cần tính đến Redis khi tải cao đa worker.
10. **`TD-54` (Windows Runtime cho Big Data Hadoop/Hive Metastore):** Kế hoạch triển khai qua Docker/WSL2 để tránh lỗi Winutils.
11. **`TD-55` (Xung đột JVM giữa Java 25 hệ thống và Hadoop/Spark Java 17 LTS):** Cô lập môi trường Java 17 trong container hoặc thư mục độc lập.
12. **`TD-56` (Small Files Problem khi nạp 1.191 phân vùng Parquet lên HDFS):** Cần cơ chế Compaction/Coalescing trước khi đồng bộ.
13. **`TD-57` (Nợ định danh biến `BUS_STOPPED_SPEED_KMPH = 5.0` trong `telemetry_sanitizer.py`):** Đổi tên thành `GPS_STATIONARY_DRIFT_THRESHOLD_M`.
14. **`TD-64` (Cực kỳ quan trọng — Sai lệch không gian giữa trạm dừng và tim đường hình học BusMap vượt 35m):**
   - 157 trạm dừng lệch $> 35\text{m}$.
   - Tuyến E11 lệch cực đại $714.2\text{m}$ (tim đường đi qua Kim Mã - Giảng Võ trong khi trạm nằm ở Liễu Giai - Hoàng Hoa Thám).
   - Tuyến 35B lệch $870.7\text{m}$; Tuyến 11/40/52 lệch $425.3\text{m}$.
   - Cần kiểm soát chặt chẽ khi tính toán hình học hoặc suy luận khoảng cách trạm.

---

## 4. BẢNG MA TRẬN ĐỐI SOÁT TOÀN DIỆN (PARITY AUDIT MATRIX TD-01 ĐẾN TD-64)

| Mã TD | Hiện trạng trong Ledger | Hiện trạng thực tế Codebase | Nhóm phân loại | Đề xuất Trạng thái & Nhãn mới |
| :---: | :---: | :---: | :---: | :--- |
| **TD-01** | `[x]` | Đã tập trung hằng số vào `config/system_config.py`. | Nhóm D2 | Giữ nguyên `[x]` |
| **TD-02** | `[x]` | Đã xóa cột `is_dwell`, Silver chuẩn 13 cột. | Nhóm D2 | Giữ nguyên `[x]` |
| **TD-03** | `[x]` | Đã sửa `v_mps = max(0.0, ds) / dt` trong Frenet projector. | Nhóm D2 | Giữ nguyên `[x]` |
| **TD-04** | `[x]` | Đã lọc hành lang 35m trước khi tính đạo hàm vận tốc. | Nhóm D2 | Giữ nguyên `[x]` |
| **TD-05** | `[x]` | Đã chặn lùi và Direction-Run Coalescing. | Nhóm D2 | Giữ nguyên `[x]` |
| **TD-06** | `[x]` | Phép chiếu trực giao vector Dot-Product ổn định. | Nhóm D2 | Giữ nguyên `[x]` |
| **TD-07** | `[x]` | Đã dọn dẹp dữ liệu rác, giữ đúng 48 tuyến HUST. | Nhóm D2 | Giữ nguyên `[x]` |
| **TD-08** | `[x]` | Đã mở rộng `HANOI_BBOX`, khôi phục 229k pings ngoại thành. | Nhóm D2 | Giữ nguyên `[x]` |
| **TD-09** | `[x]` | Ngưỡng kẹp thích ứng độ dài đoạn trạm trong Baseline. | Nhóm D2 | Giữ nguyên `[x]` |
| **TD-10** | `[x]` | Chuẩn hóa ngưỡng Tier 0 theo ngày quan sát. | Nhóm D2 | Giữ nguyên `[x]` |
| **TD-11** | `[x]` | Đã lưu 5 đại lượng phân phối (P10, P50, P90, Mean, Std). | Nhóm D2 | Giữ nguyên `[x]` |
| **TD-12** | `[ ]` | Bản vá hình học E11, E11CT, 123 vẫn đang có hiệu lực. | Nhóm D1 | **GIỮ NGUYÊN `[ ]` (Theo dõi rủi ro)** |
| **TD-13** | `[ ]` | Xử lý lỗ thủng detour $300\text{s} < \Delta t \le 1800\text{s}$ trong Lakehouse. | Nhóm D1 | **GIỮ NGUYÊN `[ ]` (Theo dõi rủi ro)** |
| **TD-14** | `[ ]` | 4 tuyến chạy lệch tim đường $> 35\text{m}$ (Fallback Tier 3). | Nhóm D1 | **GIỮ NGUYÊN `[ ]` (Theo dõi rủi ro)** |
| **TD-15** | `[ ]` | Tuyến 67 và 92 ngoài vùng phủ TomTom (COALESCE 0). | Nhóm D1 | **GIỮ NGUYÊN `[ ]` (Theo dõi rủi ro)** |
| **TD-16** | `[ ]` | Chu kỳ lấy mẫu $\Delta t \approx 80\text{s}$, không tách micro-dwell. | Nhóm D1 | **GIỮ NGUYÊN `[ ]` (Quy tắc bất biến)** |
| **TD-17** | `[ ]` | Freelist Pages trong `hanoi_bus_system.db` chờ VACUUM. | Nhóm D1 | **GIỮ NGUYÊN `[ ]` (Chờ đóng gói)** |
| **TD-18** | `[x]` | Tách 3 loại ngày (T2-T6, T7, CN) và 17 khung giờ. | Nhóm D2 | Giữ nguyên `[x]` |
| **TD-19** | `[x]` | Cổng bến đầu cuối (`EXCLUDE_TERMINAL_BOUNDARY_STATIONS`). | Nhóm D2 | Giữ nguyên `[x]` |
| **TD-20** | `[x]` | Trích xuất song song 8 nhân Gold Feature Store (Prefix Sum). | Nhóm D2 | Giữ nguyên `[x]` |
| **TD-21** | `[x]` | Khắc phục Tuyến 40 đổi dải ID xe 7 chữ số. | Nhóm D2 | Giữ nguyên `[x]` |
| **TD-22** | `[x]` | Huấn luyện XGBoost ETA đa tuyến đạt MAE 97.11s. | Nhóm D2 | Giữ nguyên `[x]` |
| **TD-23** | `[x]` | Mở rộng Validation split từ 2026-10-24. | Nhóm D2 | Giữ nguyên `[x]` |
| **TD-24** | `[x]` | Cập nhật danh bạ tự động bằng `route_bus_gps` token MD5. | Nhóm D2 | Giữ nguyên `[x]` |
| **TD-25** | `[ ]` | Tuyến 90 kém hơn Baseline do Covariate Shift. | Nhóm D1 | **GIỮ NGUYÊN `[ ]` (Theo dõi ML)** |
| **TD-26** | `[x]` | Nghiệm thu Online Feature Extractor (Module 3 ML). | Nhóm C | Giữ `[x]`, bổ sung chú thích phạm vi ML |
| **TD-27** | `[ ]` | Bất đối xứng `vehicle_hn/get` vs `route_bus_gps` (Hoán vị tọa độ, ẩn xe). | Nhóm D1 | **GIỮ NGUYÊN `[ ]` (Quy tắc vận hành sống còn)** |
| **TD-28** | `[x]` | Web Demo Contract-First cũ. | Nhóm C | Giữ `[x]`, ghi chú đã tinh giản theo Spec-04 |
| **TD-29** | `[ ]` | TTL Cache RAM vs Distributed Redis Cache. | Nhóm D1 | **GIỮ NGUYÊN `[ ]` (Theo dõi tải cao)** |
| **TD-30** | `[x]` | Cơ chế hiển thị ca đêm sau 22:30. | Nhóm C | Giữ `[x]`, ghi chú UI mới tinh giản |
| **TD-31** | `[ ]` | Mở rộng ML residual cho các tuyến khác. | Nhóm C | **GIỮ NGUYÊN `[ ]` (Tái định hướng về Step 3.3/3.4)** |
| **TD-32** | `[x]` | [WONTFIX] Không tăng nhịp crawler, giữ nguyên 75s. | Nhóm D2 | Giữ nguyên `[x]` |
| **TD-33** | `[ ]` | Bất đồng bộ StationID TimBus vs BusMap Canonical. | Nhóm A | **ĐỔI THÀNH `[x] [HỦY BỎ / VOID BY SPEC-04]`** |
| **TD-34** | `[ ]` | Loại trừ TimBus khỏi Lakehouse Ingestion. | Nhóm A | **ĐỔI THÀNH `[x] [ĐÃ XÓA SỔ 100% THEO SPEC-04]`** |
| **TD-35** | `[ ]` | Xung đột viễn trắc lai ghép TimBus + BusMap. | Nhóm A | **ĐỔI THÀNH `[x] [HỦY BỎ / VOID BY SPEC-04]`** |
| **TD-36** | `[ ]` | Tiếp thu thuật toán 60 FPS từ TimBus Dalvik. | Nhóm A | **ĐỔI THÀNH `[x] [HỦY BỎ / REVERTED BY SPEC-04]`** |
| **TD-37** | `[x]` | Phân định chiều chuyển động nghiêm ngặt (Bác bỏ heuristic d_perp). | Nhóm D2 | Giữ nguyên `[x]` (Nguyên lý chuẩn cho BusMap) |
| **TD-38** | `[ ]` | Tỷ lệ mất dấu xe trên cổng TimBus & Fallback FSM. | Nhóm A | **ĐỔI THÀNH `[x] [HỦY BỎ / VOID BY SPEC-04]`** |
| **TD-39** | `[ ]` | Phụ thuộc tham số trạm lọc FleId TimBus. | Nhóm A | **ĐỔI THÀNH `[x] [HỦY BỎ / VOID BY SPEC-04]`** |
| **TD-40** | `[ ]` | Xe không ghép cặp giữa TimBus và BusMap. | Nhóm A | **ĐỔI THÀNH `[x] [HỦY BỎ / VOID BY SPEC-04]`** |
| **TD-41** | `[x]` | Xác thực thực địa độ lệch bằng ảnh vệ tinh Esri. | Nhóm D2 | Giữ nguyên `[x]` |
| **TD-42** | `[x]` | Bỏ magic number trong cửa sổ an toàn P10-P90. | Nhóm D2 | Giữ nguyên `[x]` |
| **TD-43** | `[x]` | Sửa lỗi ngắt xe bến đích sớm trong terminal gate. | Nhóm D2 | Giữ nguyên `[x]` |
| **TD-44** | `[x]` | Chuẩn hóa hàm normalize_direction. | Nhóm D2 | Giữ nguyên `[x]` |
| **TD-45** | `[x]` | Ma trận đánh giá trạng thái giao thông. | Nhóm D2 | Giữ nguyên `[x]` |
| **TD-46** | `[x]` | Lập trình Tweening 60 FPS animateMarkerTo trong Leaflet. | Nhóm B | **GIỮ `[x]`, GẮN TAG `[ĐÃ BÃI BỎ / SPEC-04]`** |
| **TD-47** | `[x]` | Khử Train/Serve Skew giữa buffer trượt và Gold. | Nhóm D2 | Giữ nguyên `[x]` |
| **TD-48** | `[x]` | Triệt tiêu xe bóng ma khi quay đầu đổi chiều. | Nhóm D2 | Giữ nguyên `[x]` |
| **TD-49** | `[x]` | Dùng pool device-id động cho BusMap API. | Nhóm D2 | Giữ nguyên `[x]` |
| **TD-50** | `[x]` | Sửa lỗi Midnight Wrap-around trong test script. | Nhóm D2 | Giữ nguyên `[x]` |
| **TD-51** | `[x]` | Page Visibility API tạm dừng poll khi ẩn tab. | Nhóm D2 | Giữ nguyên `[x]` |
| **TD-52** | `[x]` | Tích hợp timbus_bridge.py và Tweening 60 FPS 5s. | Nhóm B | **GIỮ `[x]`, GẮN TAG `[ĐÃ BÃI BỎ / SPEC-04]`** |
| **TD-53** | `[x]` | Giải thuật Dead Reckoning Kinematics & Zero Teleport. | Nhóm B | **GIỮ `[x]`, GẮN TAG `[ĐÃ BÃI BỎ / SPEC-04]`** |
| **TD-54** | `[ ]` | Tương thích Native Windows Runtime cho Hadoop/Hive. | Nhóm D1 | **GIỮ NGUYÊN `[ ]` (Big Data Debt)** |
| **TD-55** | `[ ]` | Xung đột JVM giữa Java 25 và Hadoop/Spark Java 17. | Nhóm D1 | **GIỮ NGUYÊN `[ ]` (Big Data Debt)** |
| **TD-56** | `[ ]` | Small Files Problem 1.191 phân vùng Parquet trên HDFS. | Nhóm D1 | **GIỮ NGUYÊN `[ ]` (Big Data Debt)** |
| **TD-57** | `[ ]` | Đổi tên biến BUS_STOPPED_SPEED_KMPH sang DRIFT_M. | Nhóm D1 | **GIỮ NGUYÊN `[ ]` (Code Refactor)** |
| **TD-58** | `[x]` | Sửa lỗi import Any trong `config/system_config.py`. | Nhóm D2 | Giữ nguyên `[x]` |
| **TD-59** | `[x]` | Triển khai Clean-Slate TimBus 60 FPS, XOR, Codec, FSM. | Nhóm B | **GIỮ `[x]`, GẮN TAG `[ĐÃ BÃI BỎ / SPEC-04]`** |
| **TD-60** | `[x]` | Chuẩn hóa Client ID TimBus 0x001B02F5. | Nhóm B | **GIỮ `[x]`, GẮN TAG `[ĐÃ BÃI BỎ / SPEC-04]`** |
| **TD-61** | `[x]` | Khắc phục lặp thẻ xe trong `smooth_render_controller.js`. | Nhóm B | **GIỮ `[x]`, GẮN TAG `[ĐÃ BÃI BỎ / SPEC-04]`** |
| **TD-62** | `[x]` | **BƯỚC NGOẶT: Chuyển dịch toàn diện sang Thuần BusMap Rời rạc (Spec-04).** | Cốt lõi | Giữ nguyên `[x]` (Văn bản kiến trúc nền tảng) |
| **TD-63** | `[x]` | **Triển khai Tim tuyến Polyline, Trạm dừng đánh số trên nền Esri (Spec-05).** | Cốt lõi | Giữ nguyên `[x]` (Văn bản kiến trúc nền tảng) |
| **TD-64** | `[ ]` | **Sai lệch không gian trạm dừng và tim đường vượt 35m (E11 lệch 714m).** | Nhóm D1 | **GIỮ NGUYÊN `[ ]` (Nợ hình học cốt lõi)** |

---

## 5. ĐỀ XUẤT NỘI DUNG CẬP NHẬT CHUẨN XÁC CHO SỔ CÁI

Để `@leaf_coder` có thể cập nhật sổ cái `docs/04_TECHNICAL_DEBT_AND_OPEN_ISSUES_LEDGER.md` một cách chuẩn xác mà không vi phạm nguyên tắc giữ toàn vẹn lịch sử dự án, đề xuất áp dụng chuẩn định dạng như sau:

### 5.1. Cập nhật Nhóm A (Chuyển 7 mục TimBus đang mở thành Đã Hủy bỏ):
```markdown
- [x] **TD-33: [HỦY BỎ / VOID BY SPEC-04] Sự phân kỳ danh bạ và mã trạm giữa TimBus vs. BusMap Canonical (StationID Namespace Divergence)** — *Lý do đóng nợ*: Toàn bộ công nghệ TimBus đã bị khai tử 100% theo Spec-04; hệ thống sử dụng duy nhất CSDL `canonical_station_master` của BusMap, triệt tiêu hoàn toàn nhu cầu lập bảng ánh xạ Crosswalk Table.
- [x] **TD-34: [ĐÃ HOÀN TẤT & ĐÓNG BĂNG TRIỆT ĐỂ THEO SPEC-04] Đóng băng ranh giới Tầng Thu thập 24/7 & Loại trừ TimBus khỏi Lakehouse Ingestion Pipeline** — *Nghiệm thu*: TimBus đã bị loại trừ 100% khỏi toàn bộ dự án (cả Ingestion, Lakehouse lẫn Web Serving).
- [x] **TD-35: [HỦY BỎ / VOID BY SPEC-04] Nguy cơ xung đột viễn trắc và trôi dạt đồng hồ nếu lai ghép hai nguồn (Cross-Source Telemetry Conflict)** — *Lý do đóng nợ*: Không còn kiến trúc lai ghép; hệ thống vận hành trên nguồn dữ liệu độc nhất `route_bus_gps` của BusMap.
- [x] **TD-36: [HỦY BỎ / REVERTED BY SPEC-04 & SPEC-06] Ranh giới Tiếp thu Chọn lọc & Tiêu chí Ứng dụng An toàn của TimBus vào Dự án** — *Lý do đóng nợ*: Quyết định tiếp thu thuật toán 60 FPS và lưu trữ `experiments/timbus/` đã bị đảo ngược hoàn toàn bởi Spec-04 (loại bỏ 60 FPS) và Spec-06 (xóa sạch `experiments/timbus/`).
- [x] **TD-38: [HỦY BỎ / VOID BY SPEC-04] Tỷ lệ mất dấu xe trên cổng TimBus (Missing Fleet Rate: 17.1% - 22.9%) & Cài đặt Fallback State Machine** — *Lý do đóng nợ*: Đã chấm dứt kết nối TCP cổng 9149, không còn hiện tượng mất dấu xe trên cổng TimBus.
- [x] **TD-39: [HỦY BỎ / VOID BY SPEC-04] Sự phụ thuộc động vào tham số trạm lọc (FleId) của máy chủ TimBus** — *Lý do đóng nợ*: Đã ngừng gửi request đến server TimBus.
- [x] **TD-40: [HỦY BỎ / VOID BY SPEC-04] Các xe không ghép cặp thành công (Unmatched Vehicles: 17% – 35%) giữa TimBus và BusMap** — *Lý do đóng nợ*: Không còn cơ chế ghép cặp đa nguồn; danh mục xe được xác định tất định từ API BusMap.
```

### 5.2. Cập nhật Nhóm B (Bổ sung nhãn cảnh báo ĐÃ BÃI BỎ cho 6 mục 60 FPS):
```markdown
- [x] **TD-46: [ĐÃ BÃI BỎ / SUPERSEDED BY SPEC-04] Lời hứa ảo Tweening 60 FPS trong Web Demo (Chưa có hàm `animateMarkerTo` thực tế)** — *Trạng thái hiện tại*: Giải pháp `animateMarkerTo` dùng `requestAnimationFrame` và Lerp 60 FPS đã hoàn thành ở giai đoạn trước, nhưng đã bị bãi bỏ 100% theo Spec-04 để chuyển sang cơ chế Discrete Updates 15s.
- [x] **TD-52: [ĐÃ BÃI BỎ / SUPERSEDED BY SPEC-04] Triển khai Giải thuật Nội suy ETA Vi mô & Tích hợp Viễn trắc TimBus 5s vào Web Demo** — *Trạng thái hiện tại*: Module `timbus_bridge.py` và giải thuật nội suy 5s đã bị loại bỏ hoàn toàn khỏi codebase; web demo hiện tại chạy thuần BusMap rời rạc (`busmap_service.py`).
- [x] **TD-53: [ĐÃ BÃI BỎ / SUPERSEDED BY SPEC-04] Xóa bỏ Triệt để Cơ chế Teleport & Hoàn thiện Giải thuật Điều hòa Vi sai Động lượng Đón đầu** — *Trạng thái hiện tại*: Giải thuật Dead Reckoning Kinematics và Continuous Reconciliation đã được thay thế triệt để bằng cơ chế cập nhật tọa độ rời rạc tức thời `marker.setLatLng()`, loại bỏ hoàn toàn các lỗi teleport và overshoot.
- [x] **TD-59: [ĐÃ BÃI BỎ / SUPERSEDED BY SPEC-04 & SPEC-06] Triển khai Clean-Slate Mục tiêu 1 — Viễn trắc Thời gian Thực & Bộ máy Nội suy Mượt TimBus 60 FPS** — *Trạng thái hiện tại*: Toàn bộ kiến trúc TimBus Clean-Slate (`TimBusCipherEngine`, `TimBusBinaryCodec`, `FailoverFSM`, `TimBusGatewayClient`) đã được bãi bỏ và chuyển giao sang Kiến trúc Tối giản Thuần BusMap Rời rạc (TD-62 / Spec-04).
- [x] **TD-60: [ĐÃ BÃI BỎ / SUPERSEDED BY SPEC-04] Chuẩn hóa Client ID TimBus (`0x001B02F5`) và triệt tiêu dứt điểm giật cục / teleport** — *Trạng thái hiện tại*: Đã ngừng sử dụng Client ID TimBus; file `smooth_render_controller.js` đã được gỡ bỏ.
- [x] **TD-61: [ĐÃ BÃI BỎ / SUPERSEDED BY SPEC-04] Khắc phục lỗi lặp thẻ xe trên thanh thông báo "Đoàn xe trực tuyến" trong `smooth_render_controller.js`** — *Trạng thái hiện tại*: Component cũ đã được thay thế bằng giao diện tối giản chuẩn mực trong `static/app.js`.
```

---

## 6. KẾT LUẬN & KIẾN NGHỊ CHO ORCHESTRATOR

1. **Sổ cái nợ kỹ thuật hiện tại đang bị "nhiễu thông tin"** bởi 13 mục TD liên quan đến công nghệ cũ (7 mục đang mở và 6 mục đã hoàn thành nhưng đã bãi bỏ).
2. **Sau khi chuẩn hóa theo Spec-07:**
   - Số lượng nợ kỹ thuật thực sự đang mở (`- [ ]`) của toàn hệ thống sẽ giảm từ **21 mục xuống còn đúng 14 mục**.
   - 14 mục còn lại này tập trung 100% vào **giá trị cốt lõi**: Hồ dữ liệu Lakehouse (Hadoop/HDFS/Parquet), ma trận Baseline P50, cơ chế API BusMap (TD-27) và khắc phục sai lệch hình học trạm dừng (TD-64).
   - Loại bỏ hoàn toàn sự nhầm lẫn về việc hệ thống còn duy trì hay phụ thuộc vào TimBus.
3. **Kiến nghị:**
   - `@orchestrator` phê duyệt báo cáo kiểm toán Spec-07.
   - Giao nhiệm vụ cho `@leaf_coder` cập nhật nội dung văn bản `docs/04_TECHNICAL_DEBT_AND_OPEN_ISSUES_LEDGER.md` theo đúng các nội dung đã chuẩn hóa tại Mục 5 của đặc tả này.
