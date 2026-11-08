# THƯ MỤC TÀI LIỆU DỰ ÁN HANOI BUS (DOCS)

> **Nguyên tắc Quản trị Tài liệu (Điều IV Hiến pháp AGENTS.md)**:
> 1. **Single Responsibility (Mỗi tài liệu chịu đúng 1 trách nhiệm duy nhất)**: Không chồng chéo nội dung, không duy trì tài liệu nháp tạm thời hoặc kế hoạch cũ đã lỗi thời.
> 2. **Đánh số liên tục không ngắt quãng**: Toàn bộ tài liệu chính thức được sắp xếp thứ tự từ `01` đến `10`.
> 3. **Nguồn chân lý thực nghiệm duy nhất**: Mọi số liệu trong tài liệu đều được bảo chứng bằng mã nguồn thực thi và kiểm thử tự động.

---

## Danh Mục Tài Liệu Quy Chuẩn Hiện Hành

| STT | Tệp Tài Liệu | Trách Nhiệm Duy Nhất (Single Responsibility) | Trạng Thái |
| :---: | :--- | :--- | :---: |
| **01** | [`01_MASTER_WORK_BREAKDOWN_STRUCTURE_ROADMAP.md`](file:///z:/Desktop/Bus_tracking/docs/01_MASTER_WORK_BREAKDOWN_STRUCTURE_ROADMAP.md) | **Lộ trình Tổng thể Dự án**: Phân rã công việc (WBS) từ Phase 1 đến Phase 7. | Sống (Living) |
| **02** | [`02_CANONICAL_DATA_DIRECTORY_SPECIFICATION.md`](file:///z:/Desktop/Bus_tracking/docs/02_CANONICAL_DATA_DIRECTORY_SPECIFICATION.md) | **Cấu trúc Thư mục Dữ liệu**: Hợp đồng phân tầng Medallion Lakehouse (Raw $\to$ Bronze $\to$ Silver $\to$ Gold). | Chuẩn hóa |
| **03** | [`03_SILVER_TRAJECTORY_CONTINUITY_AND_ETA_CHECKLIST.md`](file:///z:/Desktop/Bus_tracking/docs/03_SILVER_TRAJECTORY_CONTINUITY_AND_ETA_CHECKLIST.md) | **Chất lượng Dữ liệu Silver**: Kiểm toán tính liên tục quỹ đạo GPS & 5 quy tắc bất biến. | Chuẩn hóa |
| **04** | [`04_TECHNICAL_DEBT_AND_OPEN_ISSUES_LEDGER.md`](file:///z:/Desktop/Bus_tracking/docs/04_TECHNICAL_DEBT_AND_OPEN_ISSUES_LEDGER.md) | **Sổ cái Nợ Kỹ thuật Toàn diện**: Quản trị và theo dõi mọi nợ kỹ thuật từ TD-01 đến TD-52 (Điều 8). | Sống (Living) |
| **05** | [`05_ONLINE_FEATURE_EXTRACTOR_AND_SERVING_SPEC.md`](file:///z:/Desktop/Bus_tracking/docs/05_ONLINE_FEATURE_EXTRACTOR_AND_SERVING_SPEC.md) | **Đặc tả Serving & Trích xuất Đặc trưng**: Chi tiết 54 features và giải thuật trực tuyến $O(1)$. | Chuẩn hóa |
| **06** | [`06_TIMBUS_BUSMAP_REALTIME_PARITY_AND_FRENET_BRIDGE_REPORT.md`](file:///z:/Desktop/Bus_tracking/docs/06_TIMBUS_BUSMAP_REALTIME_PARITY_AND_FRENET_BRIDGE_REPORT.md) | **Báo cáo Thực nghiệm Đối soát Viễn trắc**: Thẩm định độ lệch TimBus vs BusMap & Cầu nối Frenet. | Nghiệm thu |
| **07** | [`07_SESSION_HANDOVER_PHASE_7_WEB_DEMO_AND_HARDWARE_GPS_AUDIT.md`](file:///z:/Desktop/Bus_tracking/docs/07_SESSION_HANDOVER_PHASE_7_WEB_DEMO_AND_HARDWARE_GPS_AUDIT.md) | **Báo cáo Nghiệm thu Web Demo & GPS Phần cứng**: Nghiệm thu Phase 7 và tần suất phát sóng 30s. | Nghiệm thu |
| **08** | [`08_GROUND_TRUTH_TEST_SPEC_AND_ANTI_PATCHING_STANDARD.md`](file:///z:/Desktop/Bus_tracking/docs/08_GROUND_TRUTH_TEST_SPEC_AND_ANTI_PATCHING_STANDARD.md) | **Chuẩn mực Kiểm thử Chân lý & Bài trừ Vá lỗi**: 4 Ground Truth Oracles & Tiêu chuẩn FSM hướng thuộc tính. | Chuẩn hóa |
| **09** | [`09_SPEC_REALTIME_TIMBUS_SERVING_INTEGRATION_AND_SMOOTH_TWEENING.md`](file:///z:/Desktop/Bus_tracking/docs/09_SPEC_REALTIME_TIMBUS_SERVING_INTEGRATION_AND_SMOOTH_TWEENING.md) | **Đặc tả Tích hợp TimBus & Làm mượt Động học**: Luồng phục vụ 5s & Easing tuyến tính xóa bỏ hiện tượng xe bay nhanh. | Nghiệm thu |
| **10** | [`10_SPEC_DISTRIBUTED_BIG_DATA_LAKEHOUSE_HDFS_STORAGE_PLAN.md`](file:///z:/Desktop/Bus_tracking/docs/10_SPEC_DISTRIBUTED_BIG_DATA_LAKEHOUSE_HDFS_STORAGE_PLAN.md) | **Đặc tả Lưu trữ Dữ liệu Lớn Phân tán HDFS**: Cụm HDFS Portable, Compaction 1.191 Parquet Silver, Dual-path Client & Benchmark. | Trình duyệt |
