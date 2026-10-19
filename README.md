# Hanoi Bus Big Data & Real-time ETA Prediction System
### Hệ Thống Giám Sát Thời Gian Thực, Lưu Trữ Dữ Liệu Lớn & Dự Báo ETA Xe Buýt Hà Nội

> **Mục tiêu**: Xây dựng luồng hệ thống dữ liệu lớn khép kín từ đầu đến cuối (End-to-End Vertical Slice):  
> `Ingestion (BusMap/TomTom) ➔ Master Ground Truth (TimBus) ➔ Big Data Lakehouse (Parquet/DuckDB) ➔ Feature Store ➔ ETA Model (XGBoost) ➔ Evaluation`.  
> **Căn cứ quy chế hoạt động**: [AGENTS.md](AGENTS.md) & [GEMINI.md](GEMINI.md).

---

## 🚌 1. Quy Mô & Chỉ Số Dữ Liệu Thực Tế (Empirical Scale)

Dự án không dừng lại ở mức thử nghiệm vài tuyến nhỏ mà đã mở rộng bao phủ toàn bộ mạng lưới vận tải hành khách công cộng thành phố Hà Nội:

| Chỉ Tiêu Kỹ Thuật | Định Lượng Thực Tế | Nguồn / Cơ Chế Xác Thực |
| :--- | :--- | :--- |
| **Tuyến buýt giám sát** | **48 tuyến hoạt động** | Các tuyến trục đô thị (01-99), BRT01 và mạng VinBus điện (E01-E11) |
| **Đoàn xe Telemetry 24/7** | **504 xe buýt** | Thu thập định kỳ qua Raw Socket SSL & DNS Cache tại RAM |
| **Danh bạ trạm dừng Master** | **3.646 trạm WGS84** | Trích xuất có thẩm quyền từ [TimBus.vn](http://timbus.vn) (TRAMOC / Sở GTVT Hà Nội) |
| **Điểm tim đường (Centerline)** | **17.631 điểm** | Hình học tim đường chính thức, gán sẵn khoảng cách tích lũy $s$ (mét) |
| **Telemetry chiếu 1D Frenet** | **285.621 bản ghi** | Ánh xạ vuông góc $s, d_\perp$, tính vận tốc dẫn xuất $\bar{v}$ và dừng đỗ `is_dwell` |
| **Big Data Lakehouse** | **101 phân vùng Parquet** | Lưu trữ cột Snappy nén theo Medallion Silver Lakehouse |
| **Độ chính xác ETA (XGBoost)** | **MAE 38.80s (0.65 min)** | Vượt trội **+45.72%** so với Baseline Historical Segment Average |

---

## 🏛️ 2. Kiến Trúc 3 Module Chuẩn Mực (Canonical 3-Tier Architecture)

Toàn bộ workspace đã được dọn dẹp sạch sẽ, đóng gói vào đúng **3 Module duy nhất**:

```
Bus_tracking/
├── module_1_data_ingestion_and_preprocessing/    # MODULE 1: Thu thập, Tiền xử lý & Ground Truth
│   ├── step_1_1_busmap_crawler_and_relay/        # Crawler 24/7, TomTom Governor & HF Dataset Sync
│   ├── step_1_2_timbus_master_ground_truth/       # Ingestion 48 tuyến, 3.646 trạm WGS84 từ TimBus
│   ├── step_1_3_telemetry_kinematic_sanitizer/    # Lọc hoán vị Lat/Lon, tính EMA & khử drift
│   └── step_1_4_frenet_spatial_projection/        # Chiếu 1D Frenet 285k pings & cờ dừng đỗ is_dwell
├── module_2_big_data_storage_and_lakehouse/      # MODULE 2: Lưu Trữ Dữ Liệu Lớn & Lakehouse
│   ├── step_2_1_sqlite_operational_store/         # CSDL SQLite (.db), Crosswalk & View trạm kế tiếp
│   ├── step_2_2_parquet_medallion_lakehouse/      # Engine xuất 101 Phân vùng Snappy Parquet Silver
│   └── step_2_3_columnar_query_engine/            # Động cơ phân tích cột DuckDB / PySpark
├── module_3_bus_eta_prediction/                  # MODULE 3: Động Cơ Dự Báo ETA Xe Buýt
│   ├── step_3_1_historical_baseline_model/        # Baseline ma trận thời gian di chuyển phân đoạn
│   ├── step_3_2_feature_store_extractor/          # Trích xuất 8 đặc trưng động học & dừng đỗ
│   ├── step_3_3_machine_learning_models/          # Huấn luyện mô hình XGBoost Regressor (MAE 38.8s)
│   └── step_3_4_evaluation_and_benchmarking/      # Đánh giá đối chuẩn đa tuyến (MAE, RMSE, MAPE)
├── data/
│   ├── ground_truth/timbus_official/             # Master Ground Truth chính thức Sở GTVT
│   ├── lakehouse/silver/route_telemetry/         # 101 Phân vùng Parquet (Medallion Silver)
│   ├── metadata/                                 # Cấu hình đoàn xe và hạn mức TomTom
│   ├── visualizations/                           # Bản đồ trực quan hóa HTML nghiệm thu
│   └── telemetry_audit_2026_10_17_18.db          # SQLite Database chính (.db đã VACUUM)
├── models/                                       # Tệp trọng số mô hình ML (.json)
├── docs/                                         # 49 Tài liệu kỹ thuật chuẩn hóa (Doc 00 - 48)
├── scripts/                                      # CLI entrypoints tinh gọn phục vụ nhóm & CI/CD
└── archive/                                      # Lưu trữ lịch sử dữ liệu và mã nguồn cũ
```

---

## 🚀 3. Hướng Dẫn Vận Hành Từng Bước (Step-by-Step Pipeline Runbook)

### Bước 1: Thu Thập & Đồng Bộ Dữ Liệu (Ingestion Layer)
- **Chạy Cloud Crawler 24/7 trên GitHub Actions**: Tự động kích hoạt qua workflow [`.github/workflows/crawl_bus.yml`](.github/workflows/crawl_bus.yml).
- **Chạy Crawler trên máy tính cá nhân**:
  ```powershell
  python scripts/run_production_crawler.py
  # Hoặc nhấp đúp: scripts/start_crawler.bat
  ```
- **Kéo dữ liệu tích lũy từ Cloud về máy**:
  ```powershell
  python scripts/sync_from_hf.py
  ```

### Bước 2: Nạp Master Ground Truth & Chiếu Tọa Độ 1D Frenet
- **Nạp toàn bộ 48 tuyến và trạm dừng từ TimBus**:
  ```powershell
  python module_1_data_ingestion_and_preprocessing/step_1_2_timbus_master_ground_truth/ingest_all_active_routes.py
  ```
- **Chiếu trực giao Telemetry lên tim đường (Frenet Linear Referencing)**:
  ```powershell
  python module_1_data_ingestion_and_preprocessing/step_1_4_frenet_spatial_projection/multi_route_projector.py
  ```

### Bước 3: Xuất Dữ Liệu Lớn Sang Columnar Parquet Lakehouse
- **Chuyển đổi dữ liệu SQLite sang 101 phân vùng Snappy Parquet (Silver Lake)**:
  ```powershell
  python module_2_big_data_storage_and_lakehouse/step_2_2_parquet_medallion_lakehouse/lakehouse_exporter.py
  ```

### Bước 4: Huấn Luyện & Đánh Giá Mô Hình Dự Báo ETA
- **Huấn luyện mô hình XGBoost ETA cho tuyến chỉ định (ví dụ Tuyến 02)**:
  ```powershell
  python module_3_bus_eta_prediction/step_3_3_machine_learning_models/train_eta_model.py --route 02
  ```
- **Đánh giá đối chuẩn sai số so với Baseline Historical Segment Average**:
  ```powershell
  python module_3_bus_eta_prediction/step_3_4_evaluation_and_benchmarking/benchmark_evaluator.py --routes 02
  ```

### Bước 5: Kiểm Tra Toàn Bộ Kiến Trúc Hệ Thống (Health Check)
```powershell
python scripts/verify_canonical_architecture.py
```

---

## 📚 4. Hệ Thống Tài Liệu Kỹ Thuật Chuẩn Hóa (Docs Index 00 - 48)

Toàn bộ cơ sở lý thuyết, công thức toán học và nhật ký thiết kế hệ thống được đánh số liên tục trong thư mục [`docs/`](docs/):

* **Phần 1 - Thu Thập Dữ Liệu & Tiền Xử Lý (00 - 18, 25, 43, 44):**
  - Khảo sát & Giao thức: `01_BUSMAP_INGESTION_STRATEGY.md`, `05_BUSMAP_API_FAILURE_ANALYSIS.md`, `06_EXTRACTED_APIS_AND_SYSTEM_DISCOVERY.md`, `08_DATA_CRAWLING_PIPELINE_PROCEDURE.md`
  - TomTom & Congestion: `02_TOMTOM_TWO_TIER_TRAFFIC_OPTIMIZATION.md`, `09_TOMTOM_FLOW_INTERPOLATION_THEORY.md`, `10_TOMTOM_EMPIRICAL_VALIDATION_REPORT.md`, `11_CONGESTION_DATA_SOURCES_AND_PROJECT_SCOPING.md`, `12_HERE_API_FREE_PLAN_EXPLOITATION_STRATEGY.md`, `13_CONGESTION_COVERAGE_CAPACITY_ANALYSIS.md`, `14_HUST_CLUSTER_ROUTES_SELECTION_AND_SPATIAL_FEASIBILITY.md`, `25_CLOUD_CRAWLER_SEMAPHORE_AND_TOMTOM_GOVERNOR.md`
  - Triển khai & Vận hành 24/7: `15_24x7_CRAWLER_DEPLOYMENT_GUIDE.md`, `16_HUGGING_FACE_SPACES_DEPLOYMENT_GUIDE.md`, `17_GITHUB_ACTIONS_CLOUD_CRAWLER_SETUP.md`, `18_TERMUX_ANDROID_24x7_INGESTION_GUIDE.md`
  - Phân tích Độ trễ Telemetry: `43_TELEMETRY_LATENCY_AND_DISCONTINUITY_ANALYSIS.md`, `44_DELTA_T_AND_DELTA_M_DUAL_PATTERN_ANALYSIS.md`
* **Phần 2 - Bản Đồ, Master Ground Truth & Big Data Lakehouse (19, 26 - 30, 32 - 42, 47):**
  - Cấu trúc Module & Hồ sơ dữ liệu: `19_WORKSPACE_MODULAR_ARCHITECTURE_AND_SRP.md`, `27_INTEGRATED_STAGE_ARCHITECTURE_AND_FLEET_SCALE.md`, `28_DATA_CLEANING_AND_FUSION_PIPELINE_SPECIFICATION.md`, `29_BIG_DATA_APACHE_ECOSYSTEM_AND_SCALABILITY_SPECIFICATION.md`
  - Khảo sát OSM ban đầu: `26_GROUND_TRUTH_ROUTE_AND_STATION_DETERMINATION_METHODOLOGY.md`, `30_OSM_TELEMETRY_FUSION_AND_AUDIT.md`, `32_STATION_UNIFICATION_AND_DISCREPANCY_ANALYSIS.md`, `33_HANOI_BUS_STATION_CATALOG_SOURCES_AND_ALIGNMENT.md`
  - Master Ground Truth TimBus (TRAMOC / Sở GTVT): `34_TIMBUS_TRAMOC_GROUND_TRUTH_DISCOVERY.md`, `36_TIMBUS_PIPELINE_AND_DATA_TRACEABILITY.md`, `38_TIMBUS_VS_BUSMAP_IDENTIFIER_MAPPING.md`, `39_MASTER_GROUND_TRUTH_TIMBUS_SPECIFICATION.md`
  - Chiếu hóa Frenet 1D & Đánh giá không gian: `35_LINEAR_REFERENCING_AND_CENTERLINE_PROJECTION_STRATEGY.md`, `37_FRENET_PROJECTION_AND_EMPIRICAL_SPATIAL_EVALUATION.md`, `40_INTERACTIVE_MAP_VALIDATION_REPORT.md`, `41_WORKSPACE_CLEANUP_AND_UNIFIED_DATABASE_STATUS.md`, `42_1D_LINEAR_REFERENCING_AND_DOWNSTREAM_STATION_VIEW.md`
  - Chuẩn hóa Kiến trúc & Dọn dẹp Root: `47_CANONICAL_MODULE_STANDARDIZATION_AND_LEGACY_ARCHIVING.md`
* **Phần 3 - Lộ Trình & Mô Hình Dự Báo ETA (00, 03, 04, 20 - 24, 31, 45, 46, 48, 49):**
  - Định hướng & Nghiệp vụ: `00_OVERVIEW_ROADMAP.md`, `03_BUS_BUNCHING_AND_DISPATCH_REGULATION.md`, `04_ETA_MODELING_AND_LAMBDA_ARCHITECTURE.md`, `20_DATA_PROCESSING_AND_ETA_PIPELINE_ROADMAP.md`, `31_ETA_ROADMAP_AND_TECHNICAL_OBSTACLES.md`
  - Đặc trưng & Ý kiến Chuyên gia ML: `21_SEGMENTATION_AND_FEATURE_ENGINEERING_SPECIFICATION.md`, `22_ML_EXPERT_CONSULTATION_DOSSIER.md`, `23_ML_EXPERT_CONSULTATION_ANSWERS.md`, `24_ML_CORE_BACKBONE_ARCHITECTURE.md`
  - Đối soát Tiến độ, Bàn giao Nhóm & Lộ trình Tiếp theo: `45_COMPREHENSIVE_DOC_AUDIT_AND_PROGRESS_CROSSCHECK.md`, `46_CANONICAL_3_TIER_ARCHITECTURE_AND_MULTI_ROUTE_HANDOVER.md`, `48_COMPREHENSIVE_REMAINING_TASKS_AND_SYSTEM_ROADMAP.md`
  - Đặc tả Ma trận Thời gian Di chuyển (Travel Time Matrix Core): `49_HISTORICAL_TRAVEL_TIME_MATRIX_SPECIFICATION_AND_STRATEGY.md`
