# Spec các phần cần hoàn thiện & kiểm thử

## 1. HDFS

- **1.1 Đã hoàn thành Silver toàn lịch sử:** Đã chạy toàn bộ `6.076` batch; bằng chứng trong `docs/evidence/hdfs_full_silver/`.
- **1.2 Đã đo hiệu năng & dedup:** Số liệu RAM, thời gian, nhận/loại/trùng và phạm vi partition trong cùng thư mục bằng chứng ở mục 1.1.
- **1.3 Dữ liệu Gold toàn mạng:** Chưa tạo Gold ETA (baseline, incidents, feature store) cho toàn bộ lịch sử trên HDFS; hiện mới có dữ liệu mẫu tuyến `02`/`27` trong `2` ngày.
- **1.4 Vận hành tự động:** Chưa có cơ chế tự theo dõi batch mới trên Hugging Face, compaction và dọn dẹp các lần chạy lỗi/dở dang.
- **1.5 Đã kiểm chứng khởi tạo cụm trắng:** Provision namespace history và phục hồi dữ liệu đã được kiểm tra; xem `docs/HDFS_RUNBOOK.md` và bằng chứng mục 1.1.
- **1.6 Kết nối phục vụ live:** Chưa kiểm chứng và nối luồng web serving hiện tại sang nguồn Gold release từ HDFS.

## 2. Pipeline dữ liệu

- **2.1 Điều phối đầu-cuối rời rạc:** Các bước ingest, chiếu Frenet, xuất Silver, dựng Baseline/Incidents, trích xuất Feature Store và train/eval đang tách rời ở nhiều script trong `scripts/`, chưa có luồng chạy thống nhất.
- **2.2 Thành phần truy vấn cột còn trống:** `module_2_big_data_storage_and_lakehouse/step_2_3_columnar_query_engine/__init__.py` hiện không có mã thực thi.
- **2.3 Lệch phạm vi dữ liệu batch và live:** Pipeline batch đang xử lý trên `48` tuyến cụm HUST cũ, trong khi lớp serving live phục vụ `176` tuyến BusMap và `96` tuyến TimBus.
- **2.4 Thiếu checkpoint toàn tuyến:** Chưa có trạng thái theo dõi và chạy lại an toàn cho toàn bộ pipeline dữ liệu từ thô đến mô hình/artifact.

## 3. Frontend Web Demo (`step_3_5_web_demo`)

- **3.1 Mã JS tập trung một file:** Toàn bộ logic UI nằm trong `static/app.js` (`1.057` dòng), trộn lẫn state, gọi API, bản đồ, popup, tab và bộ đếm thời gian.
- **3.2 Trùng lặp logic hiển thị ETA:** Thẻ trạm ghim (`renderStationFocusCard`) và popup trạm (`renderStationPopupEta`) đang dựng lặp thông tin hiển thị ETA.
- **3.3 Đã sửa xung đột bất đồng bộ:** Loại phản hồi cũ khi đổi tuyến/chiều, đổi trạm ghim hoặc popup; test hồi quy trong `tests/test_web_demo_async.cjs`.
- **3.4 Nhãn giao diện lỗi thời:** `static/index.html` còn hiển thị mô tả cũ (`BusMap Discrete Engine`, `100% Thuần rời rạc`), chưa phản ánh chế độ hybrid TimBus `5s`.
- **3.5 CSS cồng kềnh:** `static/style.css` (`1.075` dòng) viết dồn một file, chưa tách gọn theo từng vùng giao diện.

## 4. Tài liệu (`README.md`, `docs/`)

- **4.1 Liên kết hỏng ở `README.md`:** `README.md` đang trỏ tới `6` tài liệu trong `docs/` (`01_...` đến `PROJECT_REPORT_DRAFT.md`, `REPORT_OUTLINE.md`) không còn tồn tại.
- **4.2 Cây thư mục chưa cập nhật:** `README.md` thiếu `step_2_4_hdfs_history`, `experiments/timbus` và các thay đổi của luồng hybrid TimBus `5s`.
- **4.3 Thiếu tài liệu kiến trúc hiện hành:** Chưa có tài liệu tổng hợp luồng tích hợp mới nhất (Module 1–3, TimBus `5s`, `MacroSpeedTracker`, ETA `P50` và `Lạc quan -Δ đệm`).
- **4.4 Thiếu hướng dẫn chạy Web Demo & API:** Chưa có tài liệu cài đặt, khởi chạy nhanh `step_3_5_web_demo` và mô tả các endpoint của `app.py`.

## 5. Kiểm thử (Testing)

- **5.1 Kiểm thử FE đã bổ sung một phần:** Có test Node cho đổi tuyến/chiều, ghim/bỏ ghim, chuyển popup và phản hồi đảo thứ tự; chưa có kiểm tra trực quan đầy đủ hai dòng ETA `P50` / `Lạc quan`.
- **5.2 Đã sửa xung đột cổng ở `test_spec21`:** Test dùng cổng riêng và profile Chrome riêng; launcher hỗ trợ `-Port` và `-NoBrowser`.
- **5.3 Đã sửa đường dẫn artifact ở `test_spec32`:** Generator và test cùng dùng `data/evaluation/ml_error_distribution/`; 22 test đạt.
- **5.4 Thiếu kiểm thử pipeline dữ liệu đầu-cuối:** Chưa có bộ test tích hợp kiểm chứng toàn bộ luồng từ dữ liệu thô đến Gold/feature store.
- **5.5 Kiểm chứng quy mô lớn đã có một phần:** Silver toàn lịch sử đã được chạy và đối soát (mục 1.1); Gold toàn mạng và thử tải nhiều client vẫn chưa được kiểm chứng.
