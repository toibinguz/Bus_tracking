# Spec các phần cần hoàn thiện & kiểm thử

## 1. HDFS

- **1.1 Xử lý Silver toàn lịch sử:** Spark Silver chưa chạy được trên toàn bộ `6.076` batch (`5,43 GB`) ở tầng Bronze do giới hạn gom dữ liệu theo route vào RAM.
- **1.2 Đo lường hiệu năng & dedup:** Chưa có số liệu đo RAM, thời gian chạy và tỷ lệ nhận/loại trùng trên nhiều partition thực tế.
- **1.3 Dữ liệu Gold toàn mạng:** Chưa tạo Gold ETA (baseline, incidents, feature store) cho toàn bộ lịch sử trên HDFS; hiện mới có dữ liệu mẫu tuyến `02`/`27` trong `2` ngày.
- **1.4 Vận hành tự động:** Chưa có cơ chế tự theo dõi batch mới trên Hugging Face, compaction và dọn dẹp các lần chạy lỗi/dở dang.
- **1.5 Khởi tạo cụm trắng:** Script provision cụm cũ chưa tạo đầy đủ namespace history hiện hành.
- **1.6 Kết nối phục vụ live:** Chưa kiểm chứng và nối luồng web serving hiện tại sang nguồn Gold release từ HDFS.

## 2. Pipeline dữ liệu

- **2.1 Điều phối đầu-cuối rời rạc:** Các bước ingest, chiếu Frenet, xuất Silver, dựng Baseline/Incidents, trích xuất Feature Store và train/eval đang tách rời ở nhiều script trong `scripts/`, chưa có luồng chạy thống nhất.
- **2.2 Thành phần truy vấn cột còn trống:** `module_2_big_data_storage_and_lakehouse/step_2_3_columnar_query_engine/__init__.py` hiện không có mã thực thi.
- **2.3 Lệch phạm vi dữ liệu batch và live:** Pipeline batch đang xử lý trên `48` tuyến cụm HUST cũ, trong khi lớp serving live phục vụ `176` tuyến BusMap và `96` tuyến TimBus.
- **2.4 Thiếu checkpoint toàn tuyến:** Chưa có trạng thái theo dõi và chạy lại an toàn cho toàn bộ pipeline dữ liệu từ thô đến mô hình/artifact.

## 3. Frontend Web Demo (`step_3_5_web_demo`)

- **3.1 Mã JS tập trung một file:** Toàn bộ logic UI nằm trong `static/app.js` (`1.057` dòng), trộn lẫn state, gọi API, bản đồ, popup, tab và bộ đếm thời gian.
- **3.2 Trùng lặp logic hiển thị ETA:** Thẻ trạm ghim (`renderStationFocusCard`) và popup trạm (`renderStationPopupEta`) đang dựng lặp thông tin hiển thị ETA.
- **3.3 Xung đột bất đồng bộ khi đổi tuyến/chiều:** Chưa loại bỏ phản hồi của request cũ trả về muộn khi người dùng đổi tuyến hoặc đổi chiều liên tiếp.
- **3.4 Nhãn giao diện lỗi thời:** `static/index.html` còn hiển thị mô tả cũ (`BusMap Discrete Engine`, `100% Thuần rời rạc`), chưa phản ánh chế độ hybrid TimBus `5s`.
- **3.5 CSS cồng kềnh:** `static/style.css` (`1.075` dòng) viết dồn một file, chưa tách gọn theo từng vùng giao diện.

## 4. Tài liệu (`README.md`, `docs/`)

- **4.1 Liên kết hỏng ở `README.md`:** `README.md` đang trỏ tới `6` tài liệu trong `docs/` (`01_...` đến `PROJECT_REPORT_DRAFT.md`, `REPORT_OUTLINE.md`) không còn tồn tại.
- **4.2 Cây thư mục chưa cập nhật:** `README.md` thiếu `step_2_4_hdfs_history`, `experiments/timbus` và các thay đổi của luồng hybrid TimBus `5s`.
- **4.3 Thiếu tài liệu kiến trúc hiện hành:** Chưa có tài liệu tổng hợp luồng tích hợp mới nhất (Module 1–3, TimBus `5s`, `MacroSpeedTracker`, ETA `P50` và `Lạc quan -Δ đệm`).
- **4.4 Thiếu hướng dẫn chạy Web Demo & API:** Chưa có tài liệu cài đặt, khởi chạy nhanh `step_3_5_web_demo` và mô tả các endpoint của `app.py`.

## 5. Kiểm thử (Testing)

- **5.1 Thiếu kiểm thử tự động cho FE:** Chưa có test kiểm tra logic JS sau refactor, xử lý đổi tuyến/chiều nhanh và hiển thị 2 dòng ETA `P50` / `Lạc quan`.
- **5.2 Lỗi xung đột cổng ở `test_spec21`:** `tests/test_spec21_r3_browser_cors_blackbox.py` lỗi setup khi cổng `8000` đang có server chạy sẵn.
- **5.3 Thiếu artifact đầu vào ở `test_spec32`:** `tests/test_spec32_ml_error_distribution_blackbox.py` bị fail/error do thiếu thư mục báo cáo `reports/evaluation/ml_error_distribution/`.
- **5.4 Thiếu kiểm thử pipeline dữ liệu đầu-cuối:** Chưa có bộ test tích hợp kiểm chứng toàn bộ luồng từ dữ liệu thô đến Gold/feature store.
- **5.5 Thiếu kiểm thử HDFS quy mô lớn:** Chưa có kiểm thử xác nhận tính đúng và độ ổn định khi mở rộng Spark Silver/Gold vượt tập mẫu `02`/`27`.
