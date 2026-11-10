# Hanoi Bus Big Data & Real-time ETA Prediction System
> **Current-state note (2026-11-10):** Data counts below are snapshots, not live guarantees. Steps 3.4/3.5 are integration in progress: split serving modules exist, but the public app still uses the legacy `busmap_service.py` facade and no current test suite is stored. Do not treat references to raw sockets, a 15-second cache, 18.23 ms inference, 47 features, or passing tests below as verified current behavior; see [SPEC-16](docs/specs/16_REFACTOR_SPEC_STEP_3_4_SERVING_AND_3_5_WEB_DEMO.md) and [SPEC-18](docs/specs/18_DOCUMENTATION_CODEBASE_RECONCILIATION_SPEC.md).
### Hệ Thống Giám Sát Thời Gian Thực, Hồ Dữ Liệu Lớn & Dự Báo ETA Xe Buýt Hà Nội

> **Mục tiêu**: Xây dựng luồng hệ thống dữ liệu lớn và trí tuệ nhân tạo khép kín từ đầu đến cuối (End-to-End Vertical Slice):  
> `Ingestion (BusMap Telemetry 24/7 & TomTom Incidents) ➔ Master Ground Truth (BusMap Canonical) ➔ Medallion Lakehouse (Snappy Parquet & DuckDB) ➔ Unified Gold Feature Store ➔ Multi-Route ML ETA Model (XGBoost) ➔ Real-Time Serving Engine ➔ Contract-First Web App Demo (FastAPI + SPA Leaflet)`.  
> **Căn cứ quy chế hoạt động**: Tuân thủ vô điều kiện [AGENTS.md](AGENTS.md).

---

## 🚌 1. Quy Mô & Chỉ Số Dữ Liệu Thực Tế (Empirical Scale)

Toàn bộ các chỉ số dưới đây được đo đạc trực tiếp từ dữ liệu thực tế và các script kiểm toán độc lập đã nghiệm thu:

| Chỉ Tiêu Kỹ Thuật | Định Lượng Thực Tế | Nguồn / Cơ Chế Xác Thực |
| :--- | :--- | :--- |
| **Mạng lưới trạm dừng Master** | **13.301 trạm WGS84** | Master Ground Truth duy nhất từ BusMap Canonical (`canonical_station_master`) |
| **Điểm tim đường (Centerline)** | **118.563 điểm tọa độ** | Tim đường chính thức của 176 tuyến, gán sẵn khoảng cách tích lũy $s$ (mét) |
| **Tuyến buýt giám sát viễn trắc** | **48 tuyến trọng điểm** | Các tuyến trục đô thị (01–99), BRT01 và mạng VinBus điện (E01–E11) |
| **Đoàn xe Telemetry 24/7** | **~614 xe hoạt động thực tế** | Thu thập qua Raw Socket SSL; tự động thanh lọc xe chết/zombie qua Auto-Pruning |
| **Hồ dữ liệu Silver Telemetry** | (số liệu thay đổi theo thời điểm — xem docs/specs/16) | Phân vùng Snappy Parquet (`2026-10-08 .. 2026-11-07`), $0$ bản tin lệch $>35\text{m}$, $0$ lỗi nhảy lùi |
| **Hồ dữ liệu Silver TomTom** | **46 phân vùng Parquet** | Tích hợp sự cố, điểm nghẽn và độ trễ giao thông thực tế dọc theo hành lang tuyến |
| **Ma trận Thời gian Baseline** | **169.830 ô thống kê** | 3 loại ngày $\times$ 17 khung giờ $\times$ 1.665 phân đoạn; Tier 0 + 1 đạt **`93,8%`** |
| **Unified Gold Feature Store** | **15.069.481 dòng $\times$ 60 cột** | `1,29 GB` Snappy Parquet (11,36M Train + 3,70M Test); $0$ giá trị `NaN`; sinh trong `267,52s` |
| **Độ chính xác ML (XGBoost)** | (số liệu thay đổi theo thời điểm — xem docs/specs/16) | Đánh giá trên **3.704.820 mẫu Test** (47 tuyến); cự ly xa $>15$ trạm giảm MAE đáng kể |
| **Độ trễ Suy luận Trực tuyến** | **P50 `18,23 ms` / xe** | Tính toán toàn bộ 13 trạm phía trước; **Zero Train/Serve Skew** (0/200 mẫu sai lệch) |
| **Web App Demo Serving** | **Pydantic v2 + FastAPI** | Bộ đệm In-Memory TTL Cache 15s; tài nguyên bản đồ nạp qua CDN (Leaflet unpkg, Google Fonts, gạch Esri) |
| **Tần suất GPS Phần cứng** | **Cận dưới vật lý `30.0s`** | Mode `30s` (33,3%), Trung vị `45s`, Bội số rời rạc 15s, Độ trễ lan truyền máy chủ `37,9s` |

---

## 🏛️ 2. Kiến Trúc 3 Module Chuẩn Mực (Canonical Architecture)

Cấu trúc thư mục được phân định ranh giới nghiêm ngặt theo **Điều 3 của AGENTS.md** (Tách biệt Production, Lakehouse và Experiment):

```
Bus_tracking/
├── module_1_data_ingestion_and_preprocessing/    # MODULE 1: Thu thập, Tiền xử lý & Master Ground Truth
│   ├── step_1_1_busmap_crawler_and_relay/        # Crawler 24/7, Dynamic MD5 Token, Catalog Refresher
│   ├── step_1_3_telemetry_kinematic_sanitizer/    # Chuẩn hóa tọa độ, lọc hoán vị Lat/Lng, khử drift
│   ├── step_1_4_frenet_spatial_projection/        # Chiếu tọa độ 1D Frenet (s, d_perp), bóc tách dừng đỗ
│   └── step_1_5_busmap_canonical_migration/       # BusMap Canonical Master Ground Truth (176 tuyến, 13k trạm)
├── module_2_big_data_storage_and_lakehouse/      # MODULE 2: Lưu Trữ Dữ Liệu Lớn & Lakehouse Medallion
│   ├── step_2_1_sqlite_operational_store/         # CSDL SQLite vận hành (data/hanoi_bus_system.db)
│   ├── step_2_2_parquet_medallion_lakehouse/      # Hồ dữ liệu cột Snappy Parquet (Bronze & Silver)
│   └── step_2_3_columnar_query_engine/            # Động cơ truy vấn cột DuckDB phân tích tốc độ cao
├── module_3_bus_eta_prediction/                  # MODULE 3: Động Cơ Dự Báo ETA Xe Buýt Thời Gian Thực
│   ├── step_3_1_historical_baseline_model/        # Ma trận thời gian di chuyển phân đoạn lịch sử (P50/Mean/IQR)
│   ├── step_3_2_feature_store_extractor/          # Trích xuất 6 họ đặc trưng nhân quả (Unified Gold Feature Store)
│   ├── step_3_3_machine_learning_models/          # Huấn luyện mô hình XGBoost Regressor cắt tỉa (47 features)
│   ├── step_3_4_eta_serving_and_evaluation/       # OnlineFeatureExtractor & BusMapServingService (RAM P50 18ms)
│   └── step_3_5_web_demo/                         # Web App Demo Contract-First (FastAPI + SPA Leaflet)
├── data/
│   ├── ground_truth/canonical_busmap/             # Master Ground Truth chính thức WGS84
│   ├── lakehouse/
│   │   ├── bronze/tomtom_incidents_raw/           # Dữ liệu sự cố giao thông TomTom thô theo ngày
│   │   ├── silver/route_projected_telemetry/      # Phân vùng Parquet viễn trắc đã chiếu Frenet (số liệu thay đổi theo thời điểm — xem docs/specs/16)
│   │   ├── silver/fact_route_tomtom_incidents/    # Sự cố TomTom đã gắn vào tuyến xe buýt
│   │   └── gold/eta_feature_store/                # Feature Store 15M dòng (train / test)
│   ├── metadata/                                 # Danh bạ đoàn xe, hạn mức TomTom và health check
│   ├── models/                                   # Trọng số XGBoost (.json) và Calibrator metadata
│   └── hanoi_bus_system.db                       # CSDL SQLite vận hành trung tâm (3.08 GB)
├── docs/                                         # Tài liệu kỹ thuật (docs/01–04, 07, 08) + bộ đặc tả docs/specs/04–16
├── experiments/                                  # Mã nguồn nghiên cứu ad-hoc, kiểm toán GPS phần cứng
├── scripts/                                      # CLI entrypoints tinh gọn phục vụ kiểm định & vận hành
├── run_demo.ps1                                  # Script khởi chạy Web Demo PowerShell (UTF-8 BOM)
├── run_demo.bat                                  # Script khởi chạy Web Demo 1-Click Batch (Bypass ExecutionPolicy)
└── archive/                                      # Lưu trữ vĩnh viễn tài liệu và module cũ (tránh nhầm lẫn)
```

---

## 🌐 3. Trải Nghiệm Web App Demo (Giai Đoạn 7 / Bước 3.5)

Web App Demo được xây dựng theo triết lý **Lấy hành khách làm trung tâm (Station-Centric)** và nguyên lý **Rủi ro bất đối xứng trong giao thông công cộng**:
- **Cửa sổ giờ an toàn $[P_{10}, P_{90}]$**: Hiển thị rõ mốc thời gian sớm nhất ($P_{10}$) và muộn nhất ($P_{90}$) xe có thể đến trạm.
- **Khuyến nghị chống lỡ chuyến**: `👉 Có mặt tại trạm trước HH:MM để không lỡ xe!`.
- **Thông tin lưu thông hành lang**: Tự động đánh giá trạng thái đường sắp đi qua (`Thông thoáng`, `Ùn ứ chậm`, `Kẹt xe`) dựa trên vận tốc xe trước và dữ liệu sự cố TomTom.
- **Bản đồ trực quan & Radar Pulse**: Hiển thị icon xe buýt theo hướng quay đầu thực tế, hiệu ứng radar xung điện, hỗ trợ bản đồ **Google Maps Road** tiếng Việt, ảnh vệ tinh **Esri World Imagery** và **Esri Street Map**.
- **Tài nguyên bản đồ qua CDN**: Thư viện Leaflet 1.9.4 (unpkg), Google Fonts (Inter) và gạch bản đồ Esri World Imagery / Street Map được nạp trực tiếp từ CDN; dự án KHÔNG vendor offline và KHÔNG dùng thư mục `static/vendor/`.

---

## 🚀 4. Hướng Dẫn Vận Hành Nhanh (Quickstart Runbook)

### Yêu Cầu Môi Trường (Canonical Python Runtime Standard)
Hệ thống vận hành chính thức trên **Python 3.14 (64-bit)** (đăng ký chuẩn PEP 514):
- Sử dụng launcher chuẩn Windows: lệnh `py` hoặc binary trong môi trường ảo: `.\.venv\Scripts\python.exe`.
- Môi trường ảo `.venv` được khởi tạo với cờ kế thừa thư viện hệ thống: `py -m venv .venv --system-site-packages`.

---

### Cách 1: Khởi Chạy Web App Demo (1-Click)
Khởi động máy chủ phục vụ FastAPI và tự động mở giao diện Web trên trình duyệt mặc định:
```powershell
# Cách A: Nhấp đúp chuột vào file run_demo.bat
.\run_demo.bat

# Hoặc Cách B: Khởi chạy từ PowerShell (tự động xử lý xung đột cổng 8000)
.\run_demo.ps1
```
*Giao diện Web sẵn sàng tại*: `http://localhost:8000` (Tài liệu OpenAPI Swagger UI tại: `http://localhost:8000/docs`).

---

### Cách 2: Kiểm Định Tích Hợp Toàn Bộ Kiến Trúc Bronze & Silver
Chạy script kiểm toán kiến trúc chuẩn tắc trực tiếp trên CSDL vận hành và hồ Parquet Medallion:
```powershell
py scripts/verify_canonical_architecture.py
```

---

### Cách 3: Kiểm Chứng Tần Suất Phát GPS Phần Cứng
Thăm dò trực tiếp chu kỳ phát tín hiệu của phần cứng thiết bị GPS trên các xe đang lăn bánh thực tế:
```powershell
py experiments/hardware_gps/test_consecutive_polls.py
```

---

### Cách 4: Xây Dựng Hồ Dữ Liệu & Huấn Luyện Mô Hình ML
```powershell
# 1. Xây dựng Ma trận Thời gian Baseline Phân đoạn Lịch sử
py scripts/build_baseline_travel_time_matrix.py

# 2. Trích xuất Unified Gold Feature Store (15M dòng x 60 cột)
py scripts/build_gold_feature_store.py

# 3. Huấn luyện và Đánh giá 7 Mô hình ML ETA Đa tuyến
py scripts/train_and_evaluate_ml_eta.py
```

---

## 📚 5. Danh Mục Tài Liệu Kỹ Thuật Quy Chuẩn (Docs Index)

Toàn bộ phân tích lý thuyết, mô hình toán học và nhật ký bàn giao được lưu trữ trong thư mục [`docs/`](docs/):

1. [`docs/01_MASTER_WORK_BREAKDOWN_STRUCTURE_ROADMAP.md`](docs/01_MASTER_WORK_BREAKDOWN_STRUCTURE_ROADMAP.md): Đặc tả phân rã công việc tổng thể (WBS) 7 giai đoạn.
2. [`docs/02_CANONICAL_DATA_DIRECTORY_SPECIFICATION.md`](docs/02_CANONICAL_DATA_DIRECTORY_SPECIFICATION.md): Đặc tả kiến trúc thư mục dữ liệu chuẩn Medallion (Raw $\to$ Bronze $\to$ Silver $\to$ Gold).
3. [`docs/03_SILVER_TRAJECTORY_CONTINUITY_AND_ETA_CHECKLIST.md`](docs/03_SILVER_TRAJECTORY_CONTINUITY_AND_ETA_CHECKLIST.md): Đặc tả kiểm toán dòng GPS tầng Silver & 5 quy tắc bắt buộc khi xây dựng pipeline ETA.
4. [`docs/04_TECHNICAL_DEBT_AND_OPEN_ISSUES_LEDGER.md`](docs/04_TECHNICAL_DEBT_AND_OPEN_ISSUES_LEDGER.md): Sổ cái nợ kỹ thuật & checklist quản trị rủi ro toàn hệ thống.
5. [`docs/07_SESSION_HANDOVER_PHASE_7_WEB_DEMO_AND_HARDWARE_GPS_AUDIT.md`](docs/07_SESSION_HANDOVER_PHASE_7_WEB_DEMO_AND_HARDWARE_GPS_AUDIT.md): Bàn giao hoàn thành Web App Demo (Giai đoạn 7) & kiểm toán thực nghiệm tần suất GPS phần cứng.
6. [`docs/08_GROUND_TRUTH_TEST_SPEC_AND_ANTI_PATCHING_STANDARD.md`](docs/08_GROUND_TRUTH_TEST_SPEC_AND_ANTI_PATCHING_STANDARD.md): Chuẩn mực kiểm thử chân lý & bài trừ vá lỗi.

Ngoài ra, bộ đặc tả kỹ thuật chi tiết nằm trong [`docs/specs/`](docs/specs/) (SPEC-04 … SPEC-16).

---

## ⚖️ 6. Quản Trị Rủi Ro & Sổ Cái Nợ Kỹ Thuật (Technical Debt)

Căn cứ **Điều 8 của AGENTS.md**, mọi vấn đề tồn đọng và nợ kỹ thuật được công khai minh bạch trong [`docs/04_TECHNICAL_DEBT_AND_OPEN_ISSUES_LEDGER.md`](docs/04_TECHNICAL_DEBT_AND_OPEN_ISSUES_LEDGER.md):

- **`TD-28` [x] ĐÃ HOÀN TẤT**: Triển khai Web App Demo Contract-First, TTL Cache 15s, kiểm thử Schemathesis đạt 100% độ phủ hợp đồng.
- **`TD-29` [ ] ĐANG MỞ**: In-Memory TTL Cache hiện tại chạy trên RAM đơn tiến trình. Cần tích hợp Redis backend khi mở rộng chạy multi-worker hoặc Kubernetes multi-pod.
- **`TD-30` [x] ĐÃ HOÀN TẤT**: Cơ chế hiển thị UX khi xe buýt ngừng hoạt động ban đêm (sau 22:30) đã được triển khai.
- **`TD-31` [x] ĐÃ GIẢI QUYẾT (bởi TD-22 & SPEC-04)**: Đã huấn luyện mô hình XGBoost Global đa tuyến phủ toàn bộ 48 tuyến.
- **`TD-32` [x] ĐÃ HỦY BỎ (WONTFIX)**: Bảo lưu nhịp cào ổn định 75s của Crawler 24/7; không nâng lên 35–40s.
