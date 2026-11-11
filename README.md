# Hanoi Bus Big Data & Real-Time ETA Prediction System

## 1. Giới thiệu dự án

Dự án xây dựng pipeline tích hợp cho bài toán theo dõi và ước lượng thời gian đến trạm (ETA) của mạng lưới xe buýt Hà Nội dựa trên dữ liệu viễn trắc (telemetry):

- **Thu thập và tiền xử lý**: Tiếp nhận luồng tọa độ GPS từ BusMap, chuẩn hóa dị thường động học và chiếu không gian Frenet theo hình học tuyến thực tế.
- **Lưu trữ và Lakehouse**: Tổ chức dữ liệu theo kiến trúc Medallion (Raw, Bronze, Silver, Gold) trên nền tảng SQLite vận hành, hồ dữ liệu cột Snappy Parquet, và nhánh nghiên cứu mở rộng lưu trữ lịch sử phân tán HDFS/Spark có thể tái lập.
- **Học máy và Dự báo ETA**: Trích xuất họ đặc trưng không gian - thời gian, xây dựng ma trận thời gian di chuyển phân đoạn lịch sử và huấn luyện các mô hình Gradient Boosting (XGBoost) đa tuyến.
- **Phục vụ và Thí nghiệm**: Cung cấp giao diện phục vụ truy vấn dự báo thời gian thực và mô phỏng phục vụ hành khách dựa trên rủi ro bất đối xứng.

Hệ thống được phát triển như một công trình nghiên cứu và mô phỏng kỹ thuật có thể tái lập. Các chỉ số hiệu năng và kết quả dự báo được xác thực độc lập trên các bộ dữ liệu quan sát thực nghiệm và tuân thủ quy chế quản trị tại [AGENTS.md](AGENTS.md).

## 2. Cây thư mục

```
Bus_tracking/
├── config/                                           # Cấu hình tập trung toàn hệ thống
│   └── system_config.py
├── data/                                             # Dữ liệu cục bộ và tạo tác mô hình
│   ├── ground_truth/                                 # Danh mục trạm dừng và hình học tim tuyến chuẩn tắc
│   ├── lakehouse/                                    # Hồ dữ liệu cột Medallion (Bronze, Silver, Gold)
│   ├── metadata/                                     # Danh mục đoàn xe và siêu dữ liệu vận hành
│   ├── models/                                       # Trọng số mô hình học máy và calibrator
│   ├── splits/                                       # Phân chia dữ liệu huấn luyện và kiểm thử theo thời gian
│   └── hanoi_bus_system.db                           # Cơ sở dữ liệu SQLite vận hành
├── docs/                                             # Tài liệu kỹ thuật, báo cáo và bộ đặc tả
│   ├── evidence/                                     # Sổ cái bằng chứng số liệu thực nghiệm
│   ├── specs/                                        # Bộ đặc tả kỹ thuật chi tiết (SPEC-04 đến SPEC-31)
│   ├── 01_MASTER_WORK_BREAKDOWN_STRUCTURE_ROADMAP.md # Phân rã công việc tổng thể
│   ├── 02_CANONICAL_DATA_DIRECTORY_SPECIFICATION.md  # Quy chuẩn thư mục dữ liệu
│   ├── 03_SILVER_TRAJECTORY_CONTINUITY_AND_ETA_CHECKLIST.md # Quy tắc chất lượng dữ liệu Silver
│   ├── 04_TECHNICAL_DEBT_AND_OPEN_ISSUES_LEDGER.md   # Sổ cái nợ kỹ thuật
│   ├── PROJECT_REPORT_DRAFT.md                       # Bản nháp báo cáo dự án dựa trên bằng chứng
│   └── REPORT_OUTLINE.md                             # Đề cương chi tiết báo cáo
├── module_1_data_ingestion_and_preprocessing/        # Thu thập viễn trắc và tiền xử lý không gian
│   ├── step_1_1_busmap_crawler_and_relay/            # Thu thập dữ liệu GPS BusMap
│   ├── step_1_3_telemetry_kinematic_sanitizer/       # Chuẩn hóa tọa độ và lọc nhiễu động học
│   ├── step_1_4_frenet_spatial_projection/           # Chiếu tọa độ 1D Frenet theo tim tuyến
│   └── step_1_5_busmap_canonical_migration/          # Đồng bộ dữ liệu hình học tuyến và trạm
├── module_2_big_data_storage_and_lakehouse/          # Lưu trữ dữ liệu lớn và hồ phân tích
│   ├── step_2_1_sqlite_operational_store/            # Quản trị cơ sở dữ liệu SQLite
│   ├── step_2_2_parquet_medallion_lakehouse/         # Xuất và kiểm toán Parquet Medallion
│   └── step_2_3_columnar_query_engine/               # Truy vấn phân tích dạng cột
├── module_3_bus_eta_prediction/                      # Mô hình hóa và phục vụ dự báo ETA
│   ├── step_3_1_historical_baseline_model/           # Ma trận thời gian di chuyển lịch sử
│   ├── step_3_2_feature_store_extractor/             # Trích xuất đặc trưng không gian - thời gian
│   ├── step_3_3_machine_learning_models/             # Huấn luyện mô hình Gradient Boosting (XGBoost)
│   ├── step_3_4_eta_serving_and_evaluation/          # Dịch vụ suy luận ETA thời gian thực
│   └── step_3_5_web_demo/                            # Giao diện web mô phỏng phục vụ hành khách
├── experiments/                                      # Thí nghiệm nghiên cứu ad-hoc và khảo sát viễn trắc
├── scripts/                                          # Công cụ thực thi và script kiểm định độc lập
└── tests/                                            # Bộ kiểm thử tự động
```
