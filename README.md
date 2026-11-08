# Hanoi Bus Big Data & Real-time ETA Prediction System
### Hệ Thống Giám Sát Thời Gian Thực, Hồ Dữ Liệu Lớn & Dự Báo ETA Xe Buýt Hà Nội

> **Mục tiêu**: Xây dựng luồng hệ thống dữ liệu lớn và trí tuệ nhân tạo khép kín từ đầu đến cuối (End-to-End Vertical Slice):  
> `Ingestion (BusMap Telemetry 24/7 & TomTom Incidents) ➔ Master Ground Truth (BusMap Canonical) ➔ Medallion Lakehouse (Snappy Parquet & DuckDB) ➔ Unified Gold Feature Store ➔ Multi-Route ML ETA Model (XGBoost) ➔ Real-Time Serving Engine ➔ Contract-First Web App Demo (FastAPI + SPA Leaflet)`.  
> **Căn cứ quy chế hoạt động**: Tuân thủ vô điều kiện [AGENTS.md](AGENTS.md) và [GEMINI.md](GEMINI.md).

---

## 🚌 1. Quy Mô & Chỉ Số Dữ Liệu Thực Tế (Empirical Scale)

Toàn bộ các chỉ số dưới đây được đo đạc trực tiếp từ dữ liệu thực tế và các script kiểm toán độc lập đã nghiệm thu:

| Chỉ Tiêu Kỹ Thuật | Định Lượng Thực Tế | Nguồn / Cơ Chế Xác Thực |
| :--- | :--- | :--- |
| **Mạng lưới trạm dừng Master** | **13.301 trạm WGS84** | Master Ground Truth duy nhất từ BusMap Canonical (`canonical_station_master`) |
| **Điểm tim đường (Centerline)** | **118.563 điểm tọa độ** | Tim đường chính thức của 176 tuyến, gán sẵn khoảng cách tích lũy $s$ (mét) |
| **Tuyến buýt giám sát viễn trắc** | **48 tuyến trọng điểm** | Các tuyến trục đô thị (01–99), BRT01 và mạng VinBus điện (E01–E11) |
| **Đoàn xe Telemetry 24/7** | **~614 xe hoạt động thực tế** | Thu thập qua Raw Socket SSL; tự động thanh lọc xe chết/zombie qua Auto-Pruning |
| **Hồ dữ liệu Silver Telemetry** | **5.565.232 bản ghi** | `1.191` phân vùng Snappy Parquet (`2026-10-08 .. 2026-11-07`), $0$ bản tin lệch $>35\text{m}$, $0$ lỗi nhảy lùi |
| **Hồ dữ liệu Silver TomTom** | **46 phân vùng Parquet** | Tích hợp sự cố, điểm nghẽn và độ trễ giao thông thực tế dọc theo hành lang tuyến |
| **Ma trận Thời gian Baseline** | **169.830 ô thống kê** | 3 loại ngày $\times$ 17 khung giờ $\times$ 1.665 phân đoạn; Tier 0 + 1 đạt **`93,8%`** |
| **Unified Gold Feature Store** | **15.069.481 dòng $\times$ 60 cột** | `1,29 GB` Snappy Parquet (11,36M Train + 3,70M Test); $0$ giá trị `NaN`; sinh trong `267,52s` |
| **Độ chính xác ML (XGBoost)** | **MAE `97,14s` \| RMSE `173,30s`** | Đánh giá trên **3.704.820 mẫu Test** (47 tuyến); cự ly xa $>15$ trạm giảm MAE **`-18,6%`** |
| **Độ trễ Suy luận Trực tuyến** | **P50 `18,23 ms` / xe** | Tính toán toàn bộ 13 trạm phía trước; **Zero Train/Serve Skew** (0/200 mẫu sai lệch) |
| **Web App Demo Serving** | **Pydantic v2 + FastAPI** | Bộ đệm In-Memory TTL Cache 15s (RAM 197 MB); 100% Offline Vendor Assets; Schemathesis PASS |
| **Tần suất GPS Phần cứng** | **Cận dưới vật lý `30.0s`** | Mode `30s` (33,3%), Trung vị `45s`, Bội số rời rạc 15s, Độ trễ lan truyền máy chủ `37,9s` |

---

## 🏛️ 2. Kiến Trúc 3 Module Chuẩn Mực (Canonical Architecture)

Cấu trúc thư mục được phân định ranh giới nghiêm ngặt theo **Điều 3 của AGENTS.md** (Tách biệt Production, Lakehouse và Experiment):

```
Bus_tracking/
├── module_1_data_ingestion_and_preprocessing/    # MODULE 1: Thu thập, Tiền xử lý & Master Ground Truth
│   ├── step_1_1_busmap_crawler_and_relay/        # Crawler 24/7, Dynamic MD5 Token, Catalog Refresher
│   ├── step_1_2_timbus_master_ground_truth/       # BusMap Canonical Master Ground Truth (176 tuyến, 13k trạm)
│   ├── step_1_3_telemetry_kinematic_sanitizer/    # Chuẩn hóa tọa độ, lọc hoán vị Lat/Lng, khử drift
│   └── step_1_4_frenet_spatial_projection/        # Chiếu tọa độ 1D Frenet (s, d_perp), bóc tách dừng đỗ
├── module_2_big_data_storage_and_lakehouse/      # MODULE 2: Lưu Trữ Dữ Liệu Lớn & Lakehouse Medallion
│   ├── step_2_1_sqlite_operational_store/         # CSDL SQLite vận hành (data/hanoi_bus_system.db)
│   ├── step_2_2_parquet_medallion_lakehouse/      # Hồ dữ liệu cột Snappy Parquet (Bronze & Silver)
│   └── step_2_3_columnar_query_engine/            # Động cơ truy vấn cột DuckDB phân tích tốc độ cao
├── module_3_bus_eta_prediction/                  # MODULE 3: Động Cơ Dự Báo ETA Xe Buýt Thời Gian Thực
│   ├── step_3_1_historical_baseline_model/        # Ma trận thời gian di chuyển phân đoạn lịch sử (P50/Mean/IQR)
│   ├── step_3_2_feature_store_extractor/          # Trích xuất 6 họ đặc trưng nhân quả (Unified Gold Feature Store)
│   ├── step_3_3_machine_learning_models/          # Huấn luyện mô hình XGBoost Regressor cắt tỉa (47 features)
│   ├── step_3_4_eta_serving_and_evaluation/       # OnlineFeatureExtractor & EtaServingService (RAM P50 18ms)
│   └── step_3_5_web_demo/                         # Web App Demo Contract-First (FastAPI + SPA Leaflet)
├── data/
│   ├── ground_truth/canonical_busmap/             # Master Ground Truth chính thức WGS84
│   ├── lakehouse/
│   │   ├── bronze/tomtom_incidents_raw/           # Dữ liệu sự cố giao thông TomTom thô theo ngày
│   │   ├── silver/route_projected_telemetry/      # 1.191 phân vùng Parquet viễn trắc đã chiếu Frenet
│   │   ├── silver/fact_route_tomtom_incidents/    # Sự cố TomTom đã gắn vào tuyến xe buýt
│   │   └── gold/eta_feature_store/                # Feature Store 15M dòng (train / test)
│   ├── metadata/                                 # Danh bạ đoàn xe, hạn mức TomTom và health check
│   ├── models/                                   # Trọng số XGBoost (.json) và Calibrator metadata
│   └── hanoi_bus_system.db                       # CSDL SQLite vận hành trung tâm (3.08 GB)
├── docs/                                         # 9 Tài liệu kỹ thuật chuẩn mực (Doc 01 - 09)
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
- **Tự chủ hoàn toàn (100% Offline Assets)**: Toàn bộ thư viện Leaflet 1.9.4 và Tailwind CSS 3.4.17 được đóng gói cục bộ trong `static/vendor/`, không phụ thuộc bất kỳ CDN ngoại lai nào.

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

### Cách 2: Kiểm Định Tích Hợp Toàn Bộ Web Demo
Chạy bộ kiểm thử 5 bước bao gồm Schemathesis OpenAPI contract validation:
```powershell
py scripts/verify_web_app_demo.py
```
*(Yêu cầu: Toàn bộ 5 bài kiểm thử phải đạt Exit code 0)*.

---

### Cách 3: Kiểm Chứng Tần Suất Phát GPS Phần Cứng
Thăm dò trực tiếp chu kỳ phát tín hiệu của phần cứng thiết bị GPS trên các xe đang lăn bánh thực tế:
```powershell
py experiments/test_consecutive_polls.py
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

# 4. Kiểm chứng luồng Phục vụ Thời gian Thực (Zero Train/Serve Skew)
py scripts/verify_online_serving_pipeline.py
```

---

## 📚 5. Danh Mục Tài Liệu Kỹ Thuật Quy Chuẩn (Docs Index)

Toàn bộ phân tích lý thuyết, mô hình toán học và nhật ký bàn giao được lưu trữ độc lập và đánh số liên tục trong thư mục [`docs/`](docs/):

1. [`docs/01_MASTER_WORK_BREAKDOWN_STRUCTURE_ROADMAP.md`](docs/01_MASTER_WORK_BREAKDOWN_STRUCTURE_ROADMAP.md): Đặc tả phân rã công việc tổng thể (WBS) 7 giai đoạn.
2. [`docs/02_CANONICAL_DATA_DIRECTORY_SPECIFICATION.md`](docs/02_CANONICAL_DATA_DIRECTORY_SPECIFICATION.md): Đặc tả kiến trúc thư mục dữ liệu chuẩn Medallion (Raw $\to$ Bronze $\to$ Silver $\to$ Gold).
3. [`docs/03_SILVER_TRAJECTORY_CONTINUITY_AND_ETA_CHECKLIST.md`](docs/03_SILVER_TRAJECTORY_CONTINUITY_AND_ETA_CHECKLIST.md): Đặc tả kiểm toán dòng GPS tầng Silver & 5 quy tắc bắt buộc khi xây dựng pipeline ETA.
4. [`docs/04_TECHNICAL_DEBT_AND_OPEN_ISSUES_LEDGER.md`](docs/04_TECHNICAL_DEBT_AND_OPEN_ISSUES_LEDGER.md): Sổ cái nợ kỹ thuật & Checklist quản trị rủi ro toàn hệ thống (Tuân thủ Điều 8 Hiến pháp).
5. [`docs/05_SESSION_HANDOVER_STEP_3_4_AND_CRAWLER_AUDIT.md`](docs/05_SESSION_HANDOVER_STEP_3_4_AND_CRAWLER_AUDIT.md): Bàn giao: Kiểm toán Crawler Tuyến 40 & Huấn luyện mô hình ML ETA Đa tuyến (Bước 3.3 – 3.4).
6. [`docs/06_ETA_INFERENCE_ENGINE_SPEC.md`](docs/06_ETA_INFERENCE_ENGINE_SPEC.md): Đặc tả luồng suy luận thời gian thực và mô hình phục vụ ETA.
7. [`docs/07_ONLINE_FEATURE_EXTRACTOR_AND_SERVING_SPEC.md`](docs/07_ONLINE_FEATURE_EXTRACTOR_AND_SERVING_SPEC.md): Đặc tả trích xuất đặc trưng trực tuyến thời gian thực (Online Feature Extractor) và Serving Service (Bước 3.5).
8. [`docs/08_WEB_APP_DEMO_SPECIFICATION_AND_PLAN.md`](docs/08_WEB_APP_DEMO_SPECIFICATION_AND_PLAN.md): Đặc tả kiến trúc & kế hoạch triển khai Web App Demo theo Contract-First.
9. [`docs/09_SESSION_HANDOVER_PHASE_7_WEB_DEMO_AND_HARDWARE_GPS_AUDIT.md`](docs/09_SESSION_HANDOVER_PHASE_7_WEB_DEMO_AND_HARDWARE_GPS_AUDIT.md): Bàn giao: Hoàn thành Web App Demo (Giai đoạn 7), Tối ưu bản đồ Offline & Kiểm toán thực nghiệm tần suất GPS phần cứng.

---

## ⚖️ 6. Quản Trị Rủi Ro & Sổ Cái Nợ Kỹ Thuật (Technical Debt)

Căn cứ **Điều 8 của AGENTS.md**, mọi vấn đề tồn đọng và nợ kỹ thuật được công khai minh bạch trong [`docs/04_TECHNICAL_DEBT_AND_OPEN_ISSUES_LEDGER.md`](docs/04_TECHNICAL_DEBT_AND_OPEN_ISSUES_LEDGER.md):

- **`TD-28` [x] ĐÃ HOÀN TẤT**: Triển khai Web App Demo Contract-First, TTL Cache 15s, kiểm thử Schemathesis đạt 100% độ phủ hợp đồng.
- **`TD-29` [ ] ĐANG MỞ**: In-Memory TTL Cache hiện tại chạy trên RAM đơn tiến trình. Cần tích hợp Redis backend khi mở rộng chạy multi-worker hoặc Kubernetes multi-pod.
- **`TD-30` [ ] ĐANG MỞ**: Bổ sung banner thông báo trên giao diện khi mạng lưới xe buýt ngừng hoạt động ban đêm (sau 22:30).
- **`TD-31` [ ] ĐANG MỞ**: Mở rộng huấn luyện trọng số ML XGBoost residual cho các nhóm tuyến ngoài Tuyến 02 (các tuyến khác hiện đang fallback an toàn về Baseline P50).
- **`TD-32` [ ] KẾ HOẠCH**: Nâng nhịp tim của Crawler 24/7 từ 75s lên 35–40s nhằm gom trọn 100% các bản tin phát 30–45s của phần cứng thiết bị GPS, tăng gấp đôi độ mịn của quỹ đạo xe buýt.
