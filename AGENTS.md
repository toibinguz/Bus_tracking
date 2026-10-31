# BỘ QUY TẮC HOẠT ĐỘNG VÀ QUẢN TRỊ AI (AGENTS CONSTITUTION)
> **Dự án**: Hanoi Bus Big Data & Real-time ETA Prediction System  
> **Áp dụng cho**: Toàn bộ các Agent / AI Assistant (Antigravity, Gemini CLI, Cursor, Copilot)  
> **Cấp bậc văn bản**: **VĂN BẢN QUY PHẠM TỐI CAO** (Supreme Law). Mọi chỉ thị, kế hoạch, mã nguồn và tài liệu kỹ thuật đều phải tuân thủ vô điều kiện. Các chi tiết thiết kế, mô hình toán học và cấu trúc bảng cụ thể được lưu trữ độc lập trong thư mục `docs/`.

---

## I. CÁC NGUYÊN TẮC HOẠT ĐỘNG TỐI CAO (SUPREME CANONS)

### Điều 1: Kỷ Luật Thực Nghiệm (Empirical Verification Over Speculation)
1. **Nghiêm cấm suy đoán vô căn cứ**: Mọi kết luận kỹ thuật, số liệu đo lường, phân tích độ trễ hay đánh giá sai số bắt buộc phải được chứng minh bằng: mã nguồn thực thi, dữ liệu thực nghiệm, log chạy thực tế hoặc kiểm thử tự động.
2. **Tuyệt đối cấm**:
   - Tự tiện suy diễn cảm tính về lưu lượng xe, thời gian chờ hoặc hành vi giao thông khi chưa có số liệu chứng minh.
   - Tự ý phán đoán hoặc "bịa" kết quả benchmark, độ chính xác mô hình.
   - Áp đặt các giả định lý thuyết mà không đối chiếu với dữ liệu thực địa.

### Điều 2: Thiết Kế Trước, Phê Duyệt Rồi Mới Triển Khai (Design First, Approve, Then Implement)
1. **Không hành động tự phát**: Mọi đề xuất thay đổi kiến trúc, thuật toán hay bổ sung tính năng phải được tổng hợp thành tài liệu đặc tả Markdown (`.md`) cụ thể trong thư mục `docs/`.
2. **Nguyên tắc phê duyệt**: AI chỉ tiến hành viết code, chỉnh sửa hệ thống hoặc can thiệp dữ liệu khi người dùng đã xem xét văn bản đặc tả và đồng ý cho phép triển khai.

### Điều 3: Đóng Băng Hợp Đồng & Phân Định Ranh Giới (Contract Freeze & Boundary Separation)
1. **Đóng băng tầng thu thập (Crawler Contract Freeze)**: Hạ tầng crawler 24/7 trên môi trường điện toán đám mây là Black-box Service đã chạy ổn định. CẤM tự ý thay đổi logic socket, giao thức mạng trừ khi có sự cố chí mạng làm dừng hệ thống. Mã nguồn tầng này bắt buộc chỉ dùng Standard Library thuần túy.
2. **Phân định Production vs. Experiment**:
   - **Hệ thống 3 module chính tắc (`module_1`, `module_2`, `module_3`)**: Là môi trường Production, chỉ chứa mã nguồn đã hoàn thiện, có type hints, docstring và kiểm thử sạch sẽ.
   - **Thư mục `experiments/`**: Là nơi duy nhất được phép đặt các script thử nghiệm, phân tích ad-hoc, kiểm toán tạm thời. Khi thử nghiệm thành công và được duyệt mới refactor đưa vào module chính.
   - Toàn bộ module cũ đã được lưu trữ vĩnh viễn trong `archive/legacy_modules/`.

### Điều 4: Nguồn Chân Lý Dữ Liệu Tối Thượng (Single Source of Truth)
1. **Master Ground Truth duy nhất**: Danh bạ trạm dừng, tọa độ địa lý WGS84 và hình học tim đường chính thức của mạng lưới xe buýt bắt buộc căn cứ trên cơ sở dữ liệu có thẩm quyền của cơ quan quản lý nhà nước (TimBus / TRAMOC / Sở GTVT). Nghiêm cấm tự gom cụm tọa độ thủ công khi đã có dữ liệu chính thức.
2. **Tập trung hóa điểm truy cập**: Mọi cấu hình hệ thống, ngưỡng vật lý, hằng số và đường dẫn lưu trữ CSDL vận hành phải được quản lý tập trung trong `config/system_config.py`. Nghiêm cấm hardcode đường dẫn file rải rác.

### Điều 5: Động Học Dẫn Xuất (Derived Kinematics Over Raw Instantaneous Sensors)
1. **Không phụ thuộc vận tốc tức thời thô**: Trường vận tốc tức thời từ GPS cực kỳ không ổn định (nhiễu Doppler, nhảy ảo khi dừng đỗ, làm tròn về 0 khi bò chậm).
2. **Nguyên lý không gian - thời gian**: Mọi tính toán động học, vận tốc di chuyển, bóc tách thời gian dừng đỗ (Dwell Time) và dự báo ETA bắt buộc phải dựa trên **vận tốc dẫn xuất không gian - thời gian** ($\bar{v} = \Delta s / \Delta t$) và **ngưỡng dịch chuyển không gian**. Nghiêm cấm dùng điều kiện vận tốc cảm biến tức thời bằng 0 để phán đoán dừng đỗ.

### Điều 6: Phân Tầng Trọng Tâm (Layered Priority - Vertical Slice)
1. **Ưu tiên End-to-End Vertical Slice**: Tập trung xây dựng luồng thông suốt từ Ingestion $\to$ Lakehouse $\to$ Baseline Thống kê $\to$ Serving. Chấm dứt tình trạng sa đà tối ưu quá mức ở một khâu cục bộ (rabbit-holing).
2. **Nền tảng trước, phức tạp sau**: Xây dựng hoàn chỉnh tầng dữ liệu lớn và Ma trận thời gian di chuyển thống kê trước; không nhảy cóc sang các mô hình Machine Learning / Deep Learning phức tạp khi dữ liệu cơ sở chưa được kiểm chứng đầy đủ.

---

## II. RANH GIỚI BỊ CẤM (STRICT GUARDRAILS)

| Phạm Vi Hoạt Động | Quyền Hạn Của AI | Ranh Giới Bị Cấm Tuyệt Đối |
| :--- | :--- | :--- |
| **Hạ tầng Crawl 24/7 (Cloud / Actions)** | Đọc dữ liệu, kiểm tra health check, bảo đảm watchdog tự phục hồi | **CẤM** can thiệp làm gián đoạn chuỗi tiếp sức hoặc tự ý thay đổi giao thức crawler đang chạy ổn định. |
| **3 Module Chính Tắc (`module_1` - `module_3`)** | Tái cấu trúc, tối ưu thuật toán, viết test, bổ sung tài liệu kỹ thuật | **CẤM** nhồi nhét script cào tạm thời, code nháp hoặc triển khai ML tự phát khi chưa được duyệt. |
| **Lưu Trữ Dữ Liệu Lớn (Big Data & Lakehouse)** | Tối ưu hóa truy vấn columnar (Parquet, DuckDB), chuẩn hóa schema | **CẤM** tạo các tệp cơ sở dữ liệu phình to vô tội vạ mà không có indexing hay partitioning rõ ràng. |
| **Ma Trận Thời Gian & Dự Báo ETA** | Xây dựng thuật toán thống kê phân vị, bóc tách dwell time, tính toán baseline | **CẤM** suy đoán siêu tham số ML, không đưa mô hình hộp đen vào khi chưa hoàn tất phân tích thống kê thực tế. |

---

## III. TIÊU CHUẨN HOÀN THÀNH TÁC VỤ (DEFINITION OF DONE - DoD)

Một công việc chỉ được coi là hoàn thành khi đáp ứng đủ 4 tiêu chí khắt khe:
1. **Executable Code**: Mã nguồn chạy được trực tiếp trên hệ thống (exit code 0), không có lỗi cú pháp, import ảo hay phụ thuộc môi trường chưa kiểm chứng.
2. **No Regression**: Không phá vỡ các chức năng, pipeline hay file cấu hình đang chạy trước đó.
3. **Traceability**: Có log hoặc output hiển thị rõ ràng kết quả định lượng, dựa trên dữ liệu thực tế, không có số liệu suy đoán.
4. **Documentation**: Có tài liệu ngắn gọn, súc tích chỉ rõ vị trí file, mô hình toán, cách chạy và ý nghĩa kết quả.

---

## IV. QUY ƯỚC QUẢN TRỊ TÀI LIỆU (DOCUMENTATION GOVERNANCE)

1. **Vị trí lưu trữ chi tiết kỹ thuật**: Toàn bộ các phân tích dữ liệu, mô hình toán học, cấu trúc schema bảng và lộ trình chi tiết KHÔNG ĐƯỢC nhồi nhét vào Hiến pháp này, mà PHẢI được lưu trữ thành các văn bản độc lập trong thư mục `docs/`.
2. **Quy tắc đánh số liên tục**: Các tài liệu trong `docs/` bắt buộc đánh số thứ tự tăng dần liên tục, không ngắt quãng (từ `docs/00_...md` đến tài liệu mới nhất).
3. **Bảo tồn tri thức**: Mọi phát hiện quan trọng từ quá trình thực nghiệm phải được văn bản hóa để chuyển giao cho các thành viên trong nhóm, không để thất lạc trong lịch sử hội thoại.
