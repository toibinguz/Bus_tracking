# BỘ QUY TẮC HOẠT ĐỘNG VÀ QUẢN TRỊ AI (AGENTS CONSTITUTION)
> **Dự án**: Hanoi Bus Big Data & Real-time ETA Prediction System  
> **Áp dụng cho**: Toàn bộ các Agent / AI Assistant (Antigravity, Gemini CLI, Cursor, Copilot)  
> **Mục tiêu tối thượng**: Đưa dự án về đích thành công theo đúng chuẩn kỹ thuật môn học Dữ liệu lớn & Ứng dụng thực tế, chấm dứt tình trạng sa đà tiểu tiết (rabbit-holing).

---

## I. NGUYÊN TẮC CỐT LÕI (CORE PRINCIPLES)

1. **End-to-End Delivery First (Tia đạn vạch đường - Vertical Slice)**:
   - Ưu tiên cao nhất là xây dựng luồng thông suốt từ đầu đến cuối: `Ingestion -> Big Data Lakehouse -> Feature Engineering -> ETA Model -> Evaluation`.
   - Tuyệt đối không dừng lại ở tầng Ingestion để tối ưu hóa quá mức (over-engineering). Khi tầng Ingestion đạt mức "Đủ tốt để dùng" (Good-enough), phải chuyển ngay sang tầng Lưu trữ Dữ liệu Lớn và Mô hình ETA.

2. **Dứt Khoát Phân Chia: Production vs. Experiment**:
   - **Các module chính (`module_1` đến `module_5`)**: Chỉ chứa mã nguồn ĐÃ HOÀN THIỆN, chạy ổn định, có docstring, có type hints và kiểm thử sạch sẽ.
   - **Thư mục `experiments/`**: Là nơi duy nhất được phép đặt các script thử nghiệm, phân tích ad-hoc, notebook tạm thời. Khi thử nghiệm thành công mới được refactor đưa vào module chính.

3. **Data Contract Freeze (Đóng băng hợp đồng dữ liệu)**:
   - Tầng Crawl Bot trên GitHub Actions hiện tại đã chạy ổn định 24/7 và đẩy dữ liệu lên Hugging Face. **CẤM** tự ý thay đổi logic socket, network protocol của crawler trừ khi có lỗi chí mạng làm dừng hệ thống.
   - Mọi module tầng sau (`module_2`, `module_3`, `module_4`, `module_5`) giao tiếp qua Schema chuẩn (Data Contract), không phụ thuộc vào các hack chắp vá.

4. **Nghiêm Cấm "Chém Gió" (Empirical Verification Only)**:
   - Mọi tuyên bố kỹ thuật, kết luận về chu kỳ, độ trễ, hay sai số ETA đều phải được chứng minh bằng: Code thực thi, dữ liệu thực nghiệm, log chạy thực tế hoặc kiểm thử tự động. Không võ đoán.

5. **Tài Liệu Hóa Bắt Buộc (Mandatory Markdown Documentation)**:
   - Sau mỗi đợt thảo luận, phân tích kỹ thuật hoặc chốt giải pháp với người dùng, AI **BẮT BUỘC** phải tổng hợp và ghi lại toàn bộ kết luận, mô hình toán, kiến trúc và lộ trình hành động vào một tệp Markdown (`.md`) cụ thể trong thư mục `docs/`.
   - Tuyệt đối không để kiến thức bị trôi mất trong ngữ cảnh chat. Mọi quyết định thiết kế phải có văn bản lưu vết lâu dài.

6. **Tuyệt Đối Không Phụ Thuộc Vận Tốc Tức Thời GPS (No Raw Speed Reliance)**:
   - Trường `speed` trong telemetry cực kỳ không ổn định (nhiễu Doppler, nhảy ảo 2-7 km/h khi xe đỗ, làm tròn về 0 km/h khi bò chậm).
   - **Bắt buộc**: Mọi tính toán động học, nhận diện dừng đỗ (dwell time) và ETA phải dựa trên **vận tốc dẫn xuất không gian - thời gian** ($\bar{v} = \Delta s / \Delta t$) và **ngưỡng dịch chuyển không gian** ($\Delta s < 15\text{m}$ trong $\Delta t \ge 20\text{s}$). Nghiêm cấm dùng điều kiện `speed == 0` thô để phán đoán dừng trạm.

7. **TimBus (TRAMOC / Sở GTVT Hà Nội) Là Master Ground Truth Duy Nhất**:
   - Cổng TimBus (`timbus.vn`) thuộc TRAMOC / Transerco là cơ sở dữ liệu gốc có thẩm quyền cao nhất về danh bạ trạm dừng (`ObjectID`), tọa độ địa lý WGS84 và hình học tim đường.
   - Mọi module phân tích, Map-Matching và mô hình ETA bắt buộc liên kết qua bảng ánh xạ chuẩn (`dim_route_crosswalk`, `dim_station_crosswalk`) từ TimBus. Nghiêm cấm suy đoán hay gom cụm tọa độ thủ công khi đã có dữ liệu nhà nước.

---

## II. PHÂN ĐỊNH QUYỀN HẠN VÀ TRÁCH NHIỆM CỦA AI

| Phạm Vi | Quyền Hạn Của AI | Ranh Giới Bị Cấm (Guardrails) |
| :--- | :--- | :--- |
| **Hạ tầng Crawl (GitHub Actions / Cloud)** | Đọc dữ liệu, kiểm tra health check, tải batch đồng bộ | **CẤM** can thiệp làm gián đoạn workflow 24/7 hoặc sửa đổi cấu trúc cron đang chạy ổn định. |
| **Cấu trúc Module (`module_1` - `module_5`)** | Tái cấu trúc, tối ưu thuật toán, viết test, bổ sung docstring | **CẤM** nhồi nhét script cào dữ liệu tạm thời, code nháp vào các module này. |
| **Lưu trữ Dữ liệu Lớn (Big Data)** | Thiết kế Parquet partition, DuckDB/Spark pipeline, Data Lakehouse | Không tạo các file database phình to vô tội vạ mà không có indexing hay partition rõ ràng. |
| **Mô hình ETA (Machine Learning)** | Xây dựng baseline, trích xuất đặc trưng, huấn luyện mô hình, tính MAE/RMSE | Không nhảy cóc vào mô hình Deep Learning phức tạp khi chưa có Baseline đơn giản để đối chuẩn. |

---

## III. TIÊU CHUẨN HOÀN THÀNH TÁC VỤ (DEFINITION OF DONE - DoD)

Một công việc do AI thực hiện chỉ được coi là hoàn thành khi đáp ứng đủ 4 tiêu chí:
1. **Executable Code**: Mã nguồn chạy được trực tiếp trên hệ thống (exit code 0), không còn lỗi cú pháp hay import ảo.
2. **No Regression**: Không phá vỡ các chức năng, pipeline hay file cấu hình đang chạy trước đó.
3. **Traceability**: Có log hoặc output hiển thị rõ ràng kết quả định lượng.
4. **Documentation**: Có tài liệu ngắn gọn, súc tích chỉ rõ vị trí file, cách chạy và ý nghĩa kết quả.

---

## IV. ĐỊNH HƯỚNG 3 BÀI TOÁN CHIẾN LƯỢC

Mọi câu trả lời và đề xuất giải pháp của AI phải luôn bám sát vào 3 bài toán lớn:
* **Phần 1 - Thu thập & Tiền xử lý (Data Ingestion)**: ĐÃ XONG nền tảng. Duy trì chế độ tự động hóa, chuyển dữ liệu định kỳ về local/cloud, dừng việc đào bới tiểu tiết.
* **Phần 2 - Lưu trữ & Xử lý Dữ liệu Lớn (Big Data Storage & Processing - BẮT BUỘC MÔN HỌC)**: Tập trung toàn lực: Chuyển đổi JSONL thô sang Parquet (Medallion: Bronze -> Silver -> Gold), phân vùng theo ngày/tuyến, tối ưu truy vấn thời gian thực bằng DuckDB / PySpark.
* **Phần 3 - Giải quyết bài toán nghiệp vụ (Dự báo ETA Xe Buýt)**: Xây dựng Feature Store $\to$ Huấn luyện Baseline (Historical Average) $\to$ Huấn luyện ML (LightGBM/XGBoost) $\to$ Đánh giá sai số MAE/MAPE theo trạm dừng.

