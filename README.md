# HUST Bus Tracker & Traffic Congestion Engine
### Hệ Thống Giám Sát, Dự Báo ETA & Tắc Nghẽn Xe Buýt Cụm Đại Học Bách Khoa Hà Nội

Dự án nghiên cứu và phát triển kiến trúc Big Data (Lambda Architecture) phục vụ theo dõi thời gian thực, đánh giá mức độ tắc nghẽn và dự báo thời gian xe buýt đến trạm (ETA) cho sinh viên và người dân Thủ đô Hà Nội.

---

## 🚌 1. Phạm Vi Trọng Điểm: Cụm Tuyến Bách Khoa (HUST Core Cluster)
Hệ thống tập trung giám sát mạng lưới 5 tuyến xe buýt huyết mạch tỏa ra 4 hướng từ khuôn viên Đại học Bách Khoa Hà Nội:
* **Tuyến 32 (13 xe):** BX Giáp Bát ⇄ Nhổn *(trục Giải Phóng - Lê Duẩn - Cầu Giấy - Nhổn)*
* **Tuyến 31 (5 xe):** Bách Khoa ⇄ Chèm / ĐH Mỏ *(xuất phát từ KTX Bách Khoa, qua Phố Huế - Bờ Hồ - Nghi Tàm)*
* **Tuyến 08A (11 xe):** Long Biên ⇄ Đông Mỹ *(chạy dọc mặt tiền Giải Phóng, kết nối Long Biên - Thanh Trì)*
* **Tuyến 26 (12 xe):** Mai Động ⇄ SVĐ Quốc Gia *(tuyến sinh viên qua Đại Cồ Việt - ĐH Y - Chùa Bộc - Cầu Giấy)*
* **Tuyến 21A (11 xe):** BX Giáp Bát ⇄ BX Yên Nghĩa *(trục Giải Phóng - Ngã Tư Vọng - Trường Chinh - Ngã Tư Sở - Nguyễn Trãi)*

**Quy mô:** **52 xe buýt telemetry hoạt động 24/7**, kiểm soát **~87.2 km** lộ trình và **19 nút giao thắt cổ chai** trọng yếu.

---

## 🏛️ 2. Cấu Trúc Thư Mục Chuẩn Hóa

```
Bus_tracking/
├── .github/
│   └── workflows/
│       └── crawl_bus.yml            # CI/CD Cloud Crawler chạy tự động trên GitHub Actions
├── data/
│   ├── metadata/
│   │   ├── hust_cluster_config.json # Cấu hình 52 xe buýt & 19 nút giao TomTom
│   │   ├── routes.json              # Danh mục 230 tuyến xe buýt Hà Nội
│   │   └── vehicles_catalog.json    # Catalog 935 xe buýt Hà Nội
│   └── raw/
│       ├── bus/                     # Dữ liệu GPS xe buýt (.jsonl theo ngày/giờ)
│       └── traffic/                 # Dữ liệu luồng giao thông TomTom (.jsonl)
├── docs/                            # 17 Tài liệu nghiên cứu kiến trúc, thuật toán & báo cáo
├── scripts/
│   ├── run_production_crawler.py    # Crawler sản xuất chính (chạy local/VPS/Android)
│   ├── cloud_crawler_step.py        # Crawler cấp độ phút tối ưu cho GitHub Actions
│   ├── sync_from_hf.py              # Script đồng bộ dữ liệu từ Hugging Face về laptop
│   ├── init_master_metadata.py      # Khởi tạo dữ liệu danh mục ban đầu
│   ├── benchmark_multilevel_*.py    # Benchmark kiểm định đa cấp độ tắc nghẽn
│   ├── start_crawler.bat            # Khởi chạy crawler 1-click trên Windows
│   └── start_crawler_background.vbs # Khởi chạy ngầm không hiện cửa sổ
├── archive/                         # Nơi lưu trữ tài liệu khảo sát & script cũ
│   ├── legacy_dumps/                # Dữ liệu dump ban đầu
│   └── research_apis/               # Mã nguồn nghiên cứu VietMap, HERE, HF Spaces
├── Test_tomtom/                     # Chứa TomTom API Key & kiểm thử bản đồ
├── .gitignore                       # Bảo vệ thông tin bí mật (API Keys, Tokens)
└── README.md                        # Hướng dẫn tổng quan dự án
```

---

## 🚀 3. Hướng Dẫn Vận Hành Hệ Thống

### Cách A: Chạy Thu Thập Trực Tiếp Trên Máy Tính (Local)
1. Nhấp đúp vào [`scripts/start_crawler.bat`](file:///z:/Desktop/Bus_tracking/scripts/start_crawler.bat) để xem màn hình dòng lệnh trực quan.
2. Hoặc nhấp đúp vào [`scripts/start_crawler_background.vbs`](file:///z:/Desktop/Bus_tracking/scripts/start_crawler_background.vbs) để chạy ẩn hoàn toàn dưới nền.
3. Script tự động hoạt động từ **05:00 đến 22:00** và tự động ngủ đêm.

### Cách B: Thu Thập Trên Mây (GitHub Actions ➔ Hugging Face Dataset)
1. Workflow [`.github/workflows/crawl_bus.yml`](file:///z:/Desktop/Bus_tracking/.github/workflows/crawl_bus.yml) tự động điều phối các phiên chạy cào cấp độ phút (60s/lần) liên tục.
2. Dữ liệu được lưu trữ an toàn tại Hugging Face Dataset: `Toibinguz/hust-bus-data`.
3. Khi cần đồng bộ dữ liệu về laptop để huấn luyện mô hình Spark:
   ```powershell
   python scripts/sync_from_hf.py
   ```

### Cách C: Thu Thập 24/7 Bền Bỉ Trên Điện Thoại Android (Termux)
1. Cài đặt Termux từ F-Droid / GitHub Releases và cấp quyền Không hạn chế pin (Unrestricted).
2. Chạy 1 dòng lệnh khởi tạo: `bash scripts/setup_termux.sh`
3. Chi tiết hướng dẫn xem tại: [`docs/19_TERMUX_ANDROID_24x7_INGESTION_GUIDE.md`](file:///z:/Desktop/Bus_tracking/docs/19_TERMUX_ANDROID_24x7_INGESTION_GUIDE.md)

---

## 📚 4. Hệ Thống Tài Liệu Kỹ Thuật (Docs Index)
Toàn bộ cơ sở lý thuyết, công thức toán học và tài liệu thiết kế hệ thống nằm trong thư mục [`docs/`](file:///z:/Desktop/Bus_tracking/docs/):
* **Lộ trình & Kiến trúc:** `00_OVERVIEW_ROADMAP.md`, `04_ETA_MODELING_AND_LAMBDA_ARCHITECTURE.md`
* **Bus-as-a-Probe & BusMap API:** `01_BUSMAP_INGESTION_STRATEGY.md`, `05_BUSMAP_API_FAILURE_ANALYSIS.md`, `06_EXTRACTED_APIS_AND_SYSTEM_DISCOVERY.md`
* **Lý thuyết Tắc nghẽn & TomTom:** `02_TOMTOM_TWO_TIER_TRAFFIC_OPTIMIZATION.md`, `09_TOMTOM_FLOW_INTERPOLATION_THEORY.md`, `10_TOMTOM_EMPIRICAL_VALIDATION_REPORT.md`
* **Quy mô Cụm Bách Khoa:** `13_CONGESTION_COVERAGE_CAPACITY_ANALYSIS.md`, `14_HUST_CLUSTER_ROUTES_SELECTION_AND_SPATIAL_FEASIBILITY.md`
* **Hướng dẫn Triển khai:** `15_24x7_CRAWLER_DEPLOYMENT_GUIDE.md`, `18_GITHUB_ACTIONS_CLOUD_CRAWLER_SETUP.md`, `19_TERMUX_ANDROID_24x7_INGESTION_GUIDE.md`

