# THƯ MỤC TÀI LIỆU DỰ ÁN HANOI BUS (DOCS)

> **Trạng thái**: Toàn bộ tài liệu lịch sử giai đoạn trước (Docs 00 đến 65) đã được lưu trữ vĩnh viễn trong `archive/historical_docs/` nhằm triệt tiêu hoàn toàn quán tính nhận thức và các giả định lỗi thời.
>
> **Nguồn chân lý thực nghiệm duy nhất**: Dữ liệu và trạng thái hệ thống được xác thực trực tiếp thông qua bộ kiểm toán `scripts/verify_canonical_architecture.py` và `scripts/audit_silver_lakehouse_purity.py`.

## Danh Mục Tài Liệu Quy Chuẩn Hiện Hành

1. [`docs/01_MASTER_WORK_BREAKDOWN_STRUCTURE_ROADMAP.md`](file:///z:/Desktop/Bus_tracking/docs/01_MASTER_WORK_BREAKDOWN_STRUCTURE_ROADMAP.md): Đặc tả phân rã công việc tổng thể (WBS) 7 giai đoạn.
2. [`docs/02_CANONICAL_DATA_DIRECTORY_SPECIFICATION.md`](file:///z:/Desktop/Bus_tracking/docs/02_CANONICAL_DATA_DIRECTORY_SPECIFICATION.md): Đặc tả kiến trúc thư mục dữ liệu chuẩn Medallion (Raw $\to$ Bronze $\to$ Silver $\to$ Gold).
3. [`docs/03_SILVER_TRAJECTORY_CONTINUITY_AND_ETA_CHECKLIST.md`](file:///z:/Desktop/Bus_tracking/docs/03_SILVER_TRAJECTORY_CONTINUITY_AND_ETA_CHECKLIST.md): Đặc tả kiểm toán dòng GPS tầng Silver & 5 quy tắc bắt buộc khi xây dựng pipeline ETA.
4. [`docs/04_TECHNICAL_DEBT_AND_OPEN_ISSUES_LEDGER.md`](file:///z:/Desktop/Bus_tracking/docs/04_TECHNICAL_DEBT_AND_OPEN_ISSUES_LEDGER.md): Sổ cái nợ kỹ thuật & Checklist quản trị rủi ro toàn hệ thống (Tuân thủ Điều 8 Hiến pháp).
5. [`docs/05_SESSION_HANDOVER_STEP_3_4_AND_CRAWLER_AUDIT.md`](file:///z:/Desktop/Bus_tracking/docs/05_SESSION_HANDOVER_STEP_3_4_AND_CRAWLER_AUDIT.md): Văn bản bàn giao công việc: Kiểm toán Crawler Tuyến 40 & Huấn luyện mô hình ML ETA Đa tuyến (Bước 3.3 – 3.4).
6. [`docs/06_ETA_INFERENCE_ENGINE_SPEC.md`](file:///z:/Desktop/Bus_tracking/docs/06_ETA_INFERENCE_ENGINE_SPEC.md): Đặc tả luồng suy luận thời gian thực và mô hình phục vụ ETA.
7. [`docs/07_ONLINE_FEATURE_EXTRACTOR_AND_SERVING_SPEC.md`](file:///z:/Desktop/Bus_tracking/docs/07_ONLINE_FEATURE_EXTRACTOR_AND_SERVING_SPEC.md): Đặc tả trích xuất đặc trưng trực tuyến thời gian thực (Online Feature Extractor) và Serving Service (Bước 3.5).
8. [`docs/08_WEB_APP_DEMO_SPECIFICATION_AND_PLAN.md`](file:///z:/Desktop/Bus_tracking/docs/08_WEB_APP_DEMO_SPECIFICATION_AND_PLAN.md): Đặc tả kiến trúc & kế hoạch triển khai Web App Demo (Bước 3.5 / Giai đoạn 7) theo Contract-First.
9. [`docs/09_SESSION_HANDOVER_PHASE_7_WEB_DEMO_AND_HARDWARE_GPS_AUDIT.md`](file:///z:/Desktop/Bus_tracking/docs/09_SESSION_HANDOVER_PHASE_7_WEB_DEMO_AND_HARDWARE_GPS_AUDIT.md): Văn bản bàn giao công việc: Hoàn thành Web App Demo (Giai đoạn 7), Tối ưu bản đồ Offline & Kiểm toán thực nghiệm tần suất GPS phần cứng.


