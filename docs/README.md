# THƯ MỤC TÀI LIỆU DỰ ÁN HANOI BUS (DOCS)

> **Nguyên tắc Quản trị Tài liệu**:
> 1. **Single Responsibility (Mỗi tài liệu chịu đúng 1 trách nhiệm duy nhất)**: Không chồng chéo nội dung, không duy trì tài liệu nháp tạm thời hoặc kế hoạch cũ đã lỗi thời.
> 2. **Nguồn chân lý thực nghiệm duy nhất**: Mọi số liệu trong tài liệu đều được bảo chứng bằng mã nguồn thực thi và kiểm thử tự động.
>
> **Freeze (effective 2026-11-10):** Modules 1, 2, and 3.1–3.3 are frozen. Only module 3.4/3.5 integration, independently authored tests, and documentation/status updates may change until a new decision; see [SPEC-19](specs/19_PHASE_3_4_3_5_FREEZE_AND_CONTINUATION_PLAN.md).

---

## A. Danh Mục Tài Liệu Quy Chuẩn Hiện Hành

| STT | Tệp Tài Liệu | Trách Nhiệm Duy Nhất (Single Responsibility) | Trạng Thái |
| :---: | :--- | :--- | :---: |
| **01** | [`01_MASTER_WORK_BREAKDOWN_STRUCTURE_ROADMAP.md`](01_MASTER_WORK_BREAKDOWN_STRUCTURE_ROADMAP.md) | **Lộ trình Tổng thể Dự án**: Phân rã công việc (WBS) từ Phase 1 đến Phase 7. | Sống (Living) |
| **02** | [`02_CANONICAL_DATA_DIRECTORY_SPECIFICATION.md`](02_CANONICAL_DATA_DIRECTORY_SPECIFICATION.md) | **Cấu trúc Thư mục Dữ liệu**: Hợp đồng phân tầng Medallion Lakehouse (Raw $\to$ Bronze $\to$ Silver $\to$ Gold). | Chuẩn hóa |
| **03** | [`03_SILVER_TRAJECTORY_CONTINUITY_AND_ETA_CHECKLIST.md`](03_SILVER_TRAJECTORY_CONTINUITY_AND_ETA_CHECKLIST.md) | **Chất lượng Dữ liệu Silver**: Kiểm toán tính liên tục quỹ đạo GPS & 5 quy tắc bất biến. | Chuẩn hóa |
| **04** | [`04_TECHNICAL_DEBT_AND_OPEN_ISSUES_LEDGER.md`](04_TECHNICAL_DEBT_AND_OPEN_ISSUES_LEDGER.md) | **Sổ cái Nợ Kỹ thuật Toàn diện**: Quản trị và theo dõi các nợ kỹ thuật (TD-01 trở đi). | Sống (Living) |
| **07** | [`07_SESSION_HANDOVER_PHASE_7_WEB_DEMO_AND_HARDWARE_GPS_AUDIT.md`](07_SESSION_HANDOVER_PHASE_7_WEB_DEMO_AND_HARDWARE_GPS_AUDIT.md) | **Báo cáo Nghiệm thu Web Demo & GPS Phần cứng**: Handover historical / reconciliation pending. | Historical |
| **08** | [`08_GROUND_TRUTH_TEST_SPEC_AND_ANTI_PATCHING_STANDARD.md`](08_GROUND_TRUTH_TEST_SPEC_AND_ANTI_PATCHING_STANDARD.md) | **Chuẩn mực Kiểm thử Chân lý & Bài trừ Vá lỗi**: 4 Ground Truth Oracles & Tiêu chuẩn FSM hướng thuộc tính. | Chuẩn hóa |
| **—** | [`README.md`](README.md) | **Mục lục & Quản trị Tài liệu**: Danh mục tài liệu và bộ đặc tả kỹ thuật. | Sống (Living) |

---

## B. Bộ Đặc Tả Kỹ Thuật (docs/specs/)

| SPEC | Tệp Đặc Tả | Mục Đích | Trạng Thái |
| :---: | :--- | :--- | :---: |
| **04** | [`04_BUSMAP_ONLY_DISCRETE_TRACKING_SPEC.md`](specs/04_BUSMAP_ONLY_DISCRETE_TRACKING_SPEC.md) | Kiến trúc theo dõi xe buýt giật cục rời rạc chỉ dùng dữ liệu BusMap. | Quy chuẩn |
| **05** | [`05_ROUTE_SHAPE_AND_STATION_INTERACTIONS_SPEC.md`](specs/05_ROUTE_SHAPE_AND_STATION_INTERACTIONS_SPEC.md) | Vẽ tim tuyến, trạm dừng đánh số & tương tác trạm trên nền vệ tinh Esri. | Quy chuẩn |
| **06** | [`06_CLEANUP_SCRIPTS_AND_EXPERIMENTS_AUDIT.md`](specs/06_CLEANUP_SCRIPTS_AND_EXPERIMENTS_AUDIT.md) | Kiểm toán & điều phối tinh giản scripts và experiments. | Historical cleanup record |
| **07** | [`07_TECHNICAL_DEBT_LEDGER_PARITY_AUDIT.md`](specs/07_TECHNICAL_DEBT_LEDGER_PARITY_AUDIT.md) | Đối soát & kiểm toán sự sai lệch của Sổ cái Nợ kỹ thuật. | Historical audit |
| **08** | [`08_STATION_ETA_MAP_INTEGRATION_SPEC.md`](specs/08_STATION_ETA_MAP_INTEGRATION_SPEC.md) | Tích hợp dự báo ETA đến trạm dừng lên bản đồ vệ tinh Esri. | Verification pending |
| **09** | [`09_REALTIME_FEATURE_EXTRACTION_AND_COLD_START_SPEC.md`](specs/09_REALTIME_FEATURE_EXTRACTION_AND_COLD_START_SPEC.md) | Trích xuất 54 đặc trưng ML thời gian thực & xử lý cold-start. | Verification pending |
| **10** | [`10_DISTRIBUTED_HDFS_LAMBDA_STORAGE_AND_QUERY_SPEC.md`](specs/10_DISTRIBUTED_HDFS_LAMBDA_STORAGE_AND_QUERY_SPEC.md) | Kiến trúc Lambda Lakehouse phân tán HDFS & bộ máy truy vấn phân tích. | Deferred / proposed |
| **11** | [`11_CONSERVATIVE_ASYMMETRIC_ETA_AND_UI_HYSTERESIS_SPEC.md`](specs/11_CONSERVATIVE_ASYMMETRIC_ETA_AND_UI_HYSTERESIS_SPEC.md) | Dự báo ETA bảo vệ bất đối xứng, lượng tử hóa phút nguyên & UI hysteresis. | Historical / superseded |
| **12** | [`12_INDEPENDENT_CODE_AND_MATH_DEFECT_AUDIT.md`](specs/12_INDEPENDENT_CODE_AND_MATH_DEFECT_AUDIT.md) | Báo cáo kiểm toán độc lập mã nguồn, mô hình toán học & ML. | Historical / superseded |
| **13** | [`13_INDEPENDENT_RUNTIME_TELEMETRY_AUDIT.md`](specs/13_INDEPENDENT_RUNTIME_TELEMETRY_AUDIT.md) | Báo cáo kiểm toán thực nghiệm runtime telemetry & frontend pipeline. | Historical / superseded |
| **14** | [`14_PEER_REVIEW_CODER_MINDSET_AND_INVARIANTS_AUDIT.md`](specs/14_PEER_REVIEW_CODER_MINDSET_AND_INVARIANTS_AUDIT.md) | Báo cáo phản biện độc lập về tư duy lập trình & bất biến vật lý. | Historical / superseded |
| **15** | [`15_PHYSICAL_KINEMATICS_AND_SERVING_SPEC.md`](specs/15_PHYSICAL_KINEMATICS_AND_SERVING_SPEC.md) | Đặc tả toán học động học vật lý, bù trễ viễn trắc & chuẩn hóa phục vụ thời gian thực. | Current mathematical authority |
| **16** | [`16_REFACTOR_SPEC_STEP_3_4_SERVING_AND_3_5_WEB_DEMO.md`](specs/16_REFACTOR_SPEC_STEP_3_4_SERVING_AND_3_5_WEB_DEMO.md) | Đặc tả refactor Bước 3.4 Serving & Bước 3.5 Web Demo. | Partially implemented / verification pending |
| **17** | [`17_REPOSITORY_DIRECTORY_RECONCILIATION_SPEC.md`](specs/17_REPOSITORY_DIRECTORY_RECONCILIATION_SPEC.md) | Directory reconciliation and test gap. | Governance record |
| **18** | [`18_DOCUMENTATION_CODEBASE_RECONCILIATION_SPEC.md`](specs/18_DOCUMENTATION_CODEBASE_RECONCILIATION_SPEC.md) | Documentation-to-codebase reconciliation. | Governance record |
