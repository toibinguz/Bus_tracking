# 47. CHUẨN HÓA KIẾN TRÚC 3 MODULE DUY NHẤT & LƯU TRỮ TOÀN BỘ MÃ NGUỒN CŨ (CANONICAL CLEANUP)

> **Mục tiêu**: Thực thi triệt để chỉ đạo dọn dẹp không gian làm việc của người dùng: loại bỏ toàn bộ 5 thư mục module rời rạc ở root, quy tụ 100% mã nguồn vào đúng **3 Module Chuẩn mực**, làm sạch thư mục `data/`, giải quyết dứt điểm tài liệu Ground Truth sai lệch cũ và bảo đảm hệ thống vận hành 100% không suy thoái (Zero Regression).  
> **Căn cứ quy tắc**: [AGENTS.md](../AGENTS.md) (Điều 1: End-to-End Delivery First, Điều 3: Data Contract Freeze, Điều 5: Tài liệu hóa bắt buộc).

---

## 1. THỰC TRẠNG TRƯỚC VÀ SAU DỌN DẸP

### 1.1. Vấn Đề Tồn Đọng Trước Khi Dọn Dẹp
- **Thư mục Root bị phân mảnh**: Tồn tại song song 5 thư mục module cũ (`module_1_telemetry_...`, `module_2_osm_...`, `module_3_spatial_...`, `module_4_traffic_...`, `module_5_system_...`) cùng 3 module mới.
- **Phụ thuộc chéo (Circular/Cross Import)**: Module thu thập mới vẫn phải import các hàm crawler từ module cũ.
- **Thư mục `data/` chứa rác**: Chứa các file JSON kiểm toán tạm thời (`telemetry_audit_dashboard_data.json`), metadata lỗi thời.
- **Tài liệu Ground Truth cũ bị sai**: File README cũ đề cập đến OpenStreetMap (OSM) cho 19 tuyến và ngưỡng tốc độ thô $v \le 5\text{ km/h}$ - hoàn toàn sai lệch so với chuẩn Master TimBus hiện tại.

### 1.2. Cấu Trúc Root Sau Khi Chuẩn Hóa 100%
```
Z:\Desktop\Bus_tracking\
├── .agents/                                     # Hiến pháp, Agent Rules & Skills
├── .github/                                     # CI/CD Workflows (crawl_bus.yml 24/7)
├── .vscode/                                     # Cấu hình IDE
├── archive/                                     # Nơi lưu trữ duy nhất cho mã nguồn & tài liệu cũ
│   ├── deprecated_scripts/                      # Các script chạy OSM / prototype cũ
│   ├── legacy_core/                             # Mã nguồn facade giai đoạn 1
│   ├── legacy_dumps/                            # Dữ liệu OSM và metadata outdate
│   ├── legacy_ground_truth/                     # Báo cáo OSM cũ (Đã gắn biển [DEPRECATED])
│   └── legacy_modules/                          # 5 thư mục module cũ (module_1 đến module_5)
├── config/                                      # File cấu hình tập trung (config.py)
├── data/                                        # Kho dữ liệu chuẩn mực (Đã dọn sạch)
│   ├── ground_truth/                            # Master Ground Truth TimBus (48 tuyến, 3.646 trạm)
│   ├── lakehouse/                               # Medallion Silver Parquet (101 partitions)
│   ├── metadata/                                # Sổ cái cấu hình và quota
│   ├── visualizations/                          # Bản đồ trực quan hóa HTML nghiệm thu
│   └── telemetry_audit_2026_10_17_18.db         # SQLite DB vận hành & phân tích đã VACUUM
├── docs/                                        # Hệ thống 48 tài liệu kỹ thuật liên tục (00 -> 47)
├── experiments/                                 # Khu vực duy nhất cho notebook / probe thử nghiệm
├── models/                                      # Trọng số mô hình ML ETA (XGBoost)
├── module_1_data_ingestion_and_preprocessing/   # MODULE 1: Thu thập, Tiền xử lý, Ground Truth & Frenet
├── module_2_big_data_storage_and_lakehouse/     # MODULE 2: Lakehouse, Parquet Medallion & DuckDB
├── module_3_bus_eta_prediction/                 # MODULE 3: Trích xuất đặc trưng & Huấn luyện ETA
└── scripts/                                     # Các CLI entrypoint chính thức & tinh gọn
```

---

## 2. GIẢI QUYẾT TÀI LIỆU GROUND TRUTH SAI LỆCH

Người dùng đã phản ánh chính xác: `ground_truth_route_station/README.md` (được lưu trữ tại `archive/legacy_ground_truth/README.md`) bị viết sai hoàn toàn về mặt bản chất kỹ thuật:
1. **Sai lệch nguồn dữ liệu**: Sử dụng OpenStreetMap (OSM) - nơi thiếu hụt trạm dừng nghiêm trọng, tim đường bị đứt gãy và out-of-date.
2. **Sai lệch quy mô**: Chỉ hỗ trợ 19 tuyến chắp vá thay vì 48 tuyến chính thức.
3. **Vi phạm quy tắc Kinematic**: Sử dụng ngưỡng vận tốc tức thời thô GPS ($v \le 5\text{ km/h}$) để phán đoán dừng đỗ, gây sai số nghiêm trọng do hiện tượng GPS drift.

### Hành Động Khắc Phục Đã Triển Khai:
- **Gắn nhãn cảnh báo đỏ (Deprecation Banner)** tại [`archive/legacy_ground_truth/README.md`](file:///z:/Desktop/Bus_tracking/archive/legacy_ground_truth/README.md): Giải thích rõ nguyên nhân phương pháp OSM bị bãi bỏ.
- **Biên soạn mới toàn bộ tài liệu chuẩn mực**:
  - [`data/ground_truth/README.md`](file:///z:/Desktop/Bus_tracking/data/ground_truth/README.md): Tài liệu hướng dẫn sử dụng và lược đồ chuẩn cho Master Ground Truth.
  - [`module_1_data_ingestion_and_preprocessing/step_1_2_timbus_master_ground_truth/README.md`](file:///z:/Desktop/Bus_tracking/module_1_data_ingestion_and_preprocessing/step_1_2_timbus_master_ground_truth/README.md): Hướng dẫn mã nguồn Ingestion TimBus.
  - [`module_1_data_ingestion_and_preprocessing/step_1_4_frenet_spatial_projection/README.md`](file:///z:/Desktop/Bus_tracking/module_1_data_ingestion_and_preprocessing/step_1_4_frenet_spatial_projection/README.md): Hướng dẫn thuật toán chiếu 1D Frenet và tính vận tốc dẫn xuất $\bar{v} = \Delta s / \Delta t$ cùng ngưỡng dừng trạm $\Delta s < 15\text{m}, \Delta t \ge 20\text{s}$.

---

## 3. NỘI LỰC HÓA MODULE 1 (SELF-CONTAINED INGESTION)

Toàn bộ các logic thu thập mạng BusMap, điều tiết TomTom quota và đẩy dữ liệu lên Hugging Face đã được chuyển vào bên trong `module_1_data_ingestion_and_preprocessing`:
- `step_1_1_busmap_crawler_and_relay/`:
  - `device_pool.py`: Quản lý 5.000 virtual device IDs chống chặn 429.
  - `socket_client.py`: Giao thức SSL raw socket siêu tốc với DNS cache trong RAM.
  - `catalog_manager.py`: Quản lý cấu hình đoàn xe 48 tuyến.
  - `incident_client.py`: TomTom API governor và circuit breaker (80 req/ngày).
  - `hotspot_evaluator.py`: Đánh giá mật độ xung quanh 19 điểm nghẽn.
  - `hf_lake_sync.py`: Tự động đồng bộ commit lên Hugging Face Dataset.
  - `local_partition_writer.py`: Ghi nối đuôi JSONL phân vùng an toàn.
  - `cloud_crawler_runner.py`: Runner chạy 24/7 trên GitHub Actions.
  - `local_production_crawler.py`: Runner chạy daemon trên máy tính cá nhân.
- `step_1_2_timbus_master_ground_truth/`: Trích xuất 48 tuyến từ TimBus TRAMOC.
- `step_1_3_telemetry_kinematic_sanitizer/`: Lọc nhiễu tọa độ, hoán vị Lat/Lon, tính EMA.
- `step_1_4_frenet_spatial_projection/`: Chiếu 1D Frenet và phát hiện dừng trạm.

---

## 4. BẢO ĐẢM KHÔNG SUY THOÁI HỆ THỐNG (REGRESSION TESTING)

Sau khi hoàn tất di dời mã nguồn cũ vào `archive/legacy_modules/`:
1. **Kiểm tra Cloud Crawler Step**:
   ```bash
   python scripts/cloud_crawler_step.py --test
   ```
   *Kết quả*: Chạy thành công 100%, tự động nhận diện khung giờ vận hành, tương thích hoàn toàn với workflow `.github/workflows/crawl_bus.yml`.
2. **Kiểm tra toàn bộ kiến trúc 3 Module**:
   ```bash
   python scripts/verify_canonical_architecture.py
   ```
   *Kết quả*: Đạt **100% Success**:
   - Master Routes: 48/48 routes.
   - Master Stations: 3.646 trạm WGS84.
   - Centerline Polyline: 17.631 điểm.
   - Projected Pings: 285.621 bản ghi.
   - View trạm kế tiếp `v_bus_to_next_station`: Hoạt động chuẩn xác.
   - Parquet Lakehouse: 101 partitions Silver.
   - Model Artifact: `models/xgboost_eta_route_02.json` toàn vẹn.

