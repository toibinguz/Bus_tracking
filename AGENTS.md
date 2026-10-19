# BỘ QUY TẮC HOẠT ĐỘNG VÀ QUẢN TRỊ AI (AGENTS CONSTITUTION)
> **Dự án**: Hanoi Bus Big Data & Real-time ETA Prediction System  
> **Áp dụng cho**: Toàn bộ các Agent / AI Assistant (Antigravity, Gemini CLI, Cursor, Copilot)  
> **Mục tiêu tối thượng**: Đưa dự án về đích thành công theo đúng chuẩn kỹ thuật môn học Dữ liệu lớn & Ứng dụng thực tế, chấm dứt tình trạng sa đà tiểu tiết (rabbit-holing) và nghiêm cấm các suy đoán vô căn cứ.

---

## I. NGUYÊN TẮC CỐT LÕI (CORE PRINCIPLES)

1. **End-to-End Delivery First (Tia đạn vạch đường - Vertical Slice)**:
   - Ưu tiên cao nhất là xây dựng luồng thông suốt từ đầu đến cuối: `Ingestion -> Big Data Lakehouse -> Ma Trận Thời Gian Di Chuyển (Travel Time Matrix) -> Serving/Evaluation`.
   - Tuyệt đối không dừng lại ở tầng Ingestion để tối ưu hóa quá mức (over-engineering). Khi tầng Ingestion đạt mức "Đủ tốt để dùng" (Good-enough), phải chuyển ngay sang tầng Lưu trữ Dữ liệu Lớn và khai phá Ma trận thời gian.

2. **Dứt Khoát Phân Chia: Production vs. Experiment**:
   - **Hệ thống 3 module chính tắc (`module_1`, `module_2`, `module_3`)**: Chỉ chứa mã nguồn ĐÃ HOÀN THIỆN, chạy ổn định, có docstring, có type hints và kiểm thử sạch sẽ.
     - `module_1_data_ingestion_and_preprocessing`: Thu thập telemetry, sự cố TomTom, Master Ground Truth TimBus, chiếu không gian Frenet 1D.
     - `module_2_big_data_storage_and_lakehouse`: Hồ dữ liệu Medallion Parquet (Bronze -> Silver -> Gold), DuckDB và CSDL vận hành SQLite.
     - `module_3_bus_eta_prediction`: Ma trận thời gian di chuyển phân đoạn (Travel Time Matrix Core) và các công cụ đánh giá ETA.
   - **Thư mục `experiments/`**: Là nơi duy nhất được phép đặt các script thử nghiệm, phân tích ad-hoc, notebook tạm thời. Khi thử nghiệm thành công mới được refactor đưa vào module chính.
   - Toàn bộ 5 module rời rạc cũ đã được lưu trữ vĩnh viễn trong `archive/legacy_modules/`.

3. **Data Contract Freeze (Đóng băng hợp đồng dữ liệu)**:
   - Tầng Crawl Bot trên GitHub Actions hiện tại đã chạy ổn định 24/7 và đẩy dữ liệu lên Hugging Face. **CẤM** tự ý thay đổi logic socket, network protocol của crawler trừ khi có lỗi chí mạng làm dừng hệ thống.
   - Môi trường GitHub Actions runner chạy Ubuntu tiêu chuẩn và không có thư viện bên ngoài; mã nguồn tầng Ingestion bắt buộc dùng Standard Library thuần túy của Python.

4. **Nghiêm Cấm Suy Đoán Vô Căn Cứ & "Chém Gió" (Empirical Verification Only - No Speculation)**:
   - **Mọi tuyên bố kỹ thuật, kết luận về chu kỳ, độ trễ, sai số hay các đặc trưng ETA đều phải được chứng minh bằng**: Code thực thi, dữ liệu thực nghiệm, log chạy thực tế hoặc kiểm thử tự động.
   - **Tuyệt đối cấm**:
     - Tự tiện đưa ra các giả định vô căn cứ về lưu lượng xe, thời gian chờ hoặc hành vi giao thông khi chưa có số liệu chứng minh.
     - Tự ý phán đoán hoặc "bịa" kết quả benchmark, độ chính xác mô hình.
     - Đưa vào các mô hình phức tạp (XGBoost/LightGBM/Deep Learning) khi dữ liệu thống kê cơ sở chưa được kiểm chứng đầy đủ.

5. **Chiến Lược Trọng Tâm: Hoàn Thành Ma Trận Thời Gian Trước (Travel Time Matrix First)**:
   - **Tạm hoãn việc chốt và triển khai Machine Learning**: Không được vội vã triển khai các mô hình ML phức tạp khi chưa có nền tảng vững chắc.
   - **Ưu tiên số 1**: Xây dựng hoàn chỉnh **Ma trận thời gian di chuyển phân đoạn (Historical Travel Time Matrix)** cho toàn bộ 48 tuyến xe buýt theo từng khung giờ và loại ngày (Bảng `agg_segment_travel_times`).
   - Ma trận này là cốt lõi của tầng **Gold Batch Layer** theo đúng yêu cầu môn học Big Data, đồng thời đóng vai trò mỏ neo chuẩn (Empirical Baseline) để dự báo ETA an toàn khi mất sóng GPS.

6. **Tài Liệu Hóa Bắt Buộc & Trình Duyệt Trước Khi Triển Khai (Design First, Approve, Then Implement)**:
   - Sau mỗi đợt thảo luận, phân tích kỹ thuật hoặc chốt giải pháp với người dùng, AI **BẮT BUỘC** phải tổng hợp và ghi lại toàn bộ kết luận, mô hình toán, kiến trúc và lộ trình hành động vào một tệp Markdown (`.md`) cụ thể trong thư mục `docs/`.
   - Các tệp tài liệu trong `docs/` phải được đánh số thứ tự tăng dần liên tục, không ngắt quãng (hiện đã đến `docs/49_...md`).
   - **Nguyên tắc triển khai**: Lập tài liệu đặc tả (.md) trước để người dùng xem xét và phê duyệt; chỉ tiến hành viết code và can thiệp hệ thống khi người dùng đã đồng ý cho phép triển khai.

7. **Tuyệt Đối Không Phụ Thuộc Vận Tốc Tức Thời GPS (No Raw Speed Reliance)**:
   - Trường `speed` trong telemetry cực kỳ không ổn định (nhiễu Doppler, nhảy ảo 2-7 km/h khi xe đỗ, làm tròn về 0 km/h khi bò chậm).
   - **Bắt buộc**: Mọi tính toán động học, nhận diện dừng đỗ (dwell time) và ETA phải dựa trên **vận tốc dẫn xuất không gian - thời gian** ($\bar{v} = \Delta s / \Delta t$) và **ngưỡng dịch chuyển không gian** ($\Delta s < 15\text{m}$ trong $\Delta t \ge 20\text{s}$). Nghiêm cấm dùng điều kiện `speed == 0` thô để phán đoán dừng trạm.

8. **TimBus (TRAMOC / Sở GTVT Hà Nội) Là Master Ground Truth Duy Nhất**:
   - Cổng TimBus (`timbus.vn`) thuộc TRAMOC / Transerco là cơ sở dữ liệu gốc có thẩm quyền cao nhất về danh bạ trạm dừng (`ObjectID`), tọa độ địa lý WGS84 và hình học tim đường.
   - Mọi module phân tích, Map-Matching và tính toán ETA bắt buộc liên kết qua bảng ánh xạ chuẩn (`dim_route_crosswalk`, `dim_station_crosswalk`) từ TimBus (đã nạp 48 tuyến, 3.646 trạm, 17.631 điểm tim đường). Nghiêm cấm suy đoán hay gom cụm tọa độ thủ công khi đã có dữ liệu nhà nước.

9. **Tập Trung Hóa Điểm Truy Cập Dữ Liệu (Single Source of Truth for Paths)**:
   - Mọi truy cập vào CSDL SQLite vận hành phải thông qua hàm `get_database_path()` trong `config/system_config.py` (chuẩn hóa tên tệp về `data/hanoi_bus_system.db`). Nghiêm cấm hardcode các đường dẫn file tạm hay file legacy rải rác.

---

## II. PHÂN ĐỊNH QUYỀN HẠN VÀ TRÁCH NHIỆM CỦA AI

| Phạm Vi | Quyền Hạn Của AI | Ranh Giới Bị Cấm (Guardrails) |
| :--- | :--- | :--- |
| **Hạ tầng Crawl (GitHub Actions / Cloud)** | Đọc dữ liệu, kiểm tra health check, tải batch đồng bộ | **CẤM** can thiệp làm gián đoạn workflow 24/7 hoặc sửa đổi cấu trúc cron đang chạy ổn định. |
| **Cấu trúc 3 Module Chính (`module_1` - `module_3`)** | Tái cấu trúc, tối ưu thuật toán, viết test, bổ sung docstring chuẩn | **CẤM** nhồi nhét script cào tạm thời, code nháp hoặc triển khai ML tự phát khi chưa được duyệt. |
| **Lưu trữ Dữ liệu Lớn (Big Data & Lakehouse)** | Thiết kế Parquet partition, DuckDB/Spark pipeline, Gold Aggregate Tables | Không tạo các file database phình to vô tội vạ mà không có indexing hay partition rõ ràng. |
| **Ma Trận Thời Gian & Dự Báo ETA** | Xây dựng thuật toán trích xuất ma trận, bóc tách Dwell Time, tính toán baseline phân đoạn | **CẤM** suy đoán siêu tham số ML, không nhảy cóc sang mô hình Deep Learning khi chưa hoàn tất ma trận 48 tuyến. |

---

## III. TIÊU CHUẨN HOÀN THÀNH TÁC VỤ (DEFINITION OF DONE - DoD)

Một công việc do AI thực hiện chỉ được coi là hoàn thành khi đáp ứng đủ 4 tiêu chí:
1. **Executable Code**: Mã nguồn chạy được trực tiếp trên hệ thống (exit code 0), không còn lỗi cú pháp hay import ảo (chỉ khi có lệnh triển khai code).
2. **No Regression**: Không phá vỡ các chức năng, pipeline hay file cấu hình đang chạy trước đó.
3. **Traceability**: Có log hoặc output hiển thị rõ ràng kết quả định lượng, dựa trên dữ liệu thực tế, không có số liệu suy đoán.
4. **Documentation**: Có tài liệu ngắn gọn, súc tích chỉ rõ vị trí file, mô hình toán, cách chạy và ý nghĩa kết quả.

---

## IV. ĐỊNH HƯỚNG 3 BÀI TOÁN CHIẾN LƯỢC

Mọi câu trả lời và đề xuất giải pháp của AI phải luôn bám sát vào 3 bài toán lớn:
* **Phần 1 - Thu thập & Tiền xử lý (Data Ingestion & Preprocessing)**: ĐÃ XONG nền tảng (48 tuyến, 3.646 trạm TimBus, 285k pings đã chiếu 1D Frenet). Duy trì crawler tự động hóa 24/7, dừng việc đào bới tiểu tiết.
* **Phần 2 - Lưu trữ & Xử lý Dữ liệu Lớn (Big Data Storage & Processing - BẮT BUỘC MÔN HỌC)**: Chuẩn hóa CSDL vận hành (`hanoi_bus_system.db`), chuyển đổi JSONL sang Medallion Parquet (Bronze -> Silver -> Gold), tối ưu hóa truy vấn bằng DuckDB.
* **Phần 3 - Giải quyết bài toán nghiệp vụ (Ma Trận Thời Gian & Dự Báo ETA)**:
  - **Trọng tâm hiện tại (P0)**: Xây dựng Ma trận thời gian di chuyển lịch sử (Travel Time Matrix $\mathbf{T}$) giữa các trạm dừng liên tiếp $\to$ Trực quan hóa Heatmap & Báo cáo điểm nghẽn $\to$ Động cơ dự báo ETA mỏ neo (Anchor Baseline ETA).
  - **Tương lai (P1 - Sau khi Ma trận hoàn tất)**: Xem xét mô hình Machine Learning (LightGBM/XGBoost) như một hàm hiệu chỉnh độ lệch tức thời ($\Delta t_{\text{ML}}$).
