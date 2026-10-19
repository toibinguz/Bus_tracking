# BỘ QUY TẮC HOẠT ĐỘNG VÀ QUẢN TRỊ AI (GEMINI / ANTIGRAVITY RULES)
> Xem tài liệu gốc đầy đủ tại [AGENTS.md](file:///z:/Desktop/Bus_tracking/AGENTS.md)

## TÓM TẮT NGUYÊN TẮC HOẠT ĐỘNG BẮT BUỘC
1. **End-to-End Vertical Slice First**: Ưu tiên xây dựng luồng thông suốt từ Ingestion -> Big Data Lakehouse -> Feature Engineering -> ETA Model. Tuyệt đối không sa đà tối ưu quá mức (rabbit-holing) ở tầng crawl.
2. **Data Contract Freeze**: Tầng crawler GitHub Actions đã ổn định 24/7. Coi nó là Black-box Service, không tự ý sửa đổi code socket/network.
3. **Phân định ranh giới**:
   - `module_1` đến `module_5`: Chỉ chứa code production hoàn chỉnh, sạch, có kiểm thử.
   - `experiments/`: Chứa các script phân tích ad-hoc, nháp, audit tạm thời.
4. **Trọng tâm hiện tại**:
   - Tầng 1 (Thu thập dữ liệu): ĐÃ ĐẠT TIÊU CHUẨN HOÀN THÀNH (DONE). Chuyển sang chế độ chạy ngầm.
   - Tầng 2 (Lưu trữ & Xử lý Dữ liệu Lớn - Trọng tâm môn học): Xây dựng Lakehouse Bronze -> Silver (Parquet) -> Gold (Feature Store) bằng DuckDB / PySpark.
   - Tầng 3 (Dự báo ETA): Baseline Historical Average -> LightGBM/XGBoost -> Đánh giá MAE/MAPE theo corridor.
5. **Nghiêm cấm võ đoán ("Không chém gió")**: Mọi kết luận phải có code thực thi và dữ liệu định lượng chứng minh.
6. **Tài liệu hóa bắt buộc (.md)**: Sau mỗi thảo luận/chốt kỹ thuật, AI phải ghi lại kết luận vào tệp `.md` trong thư mục `docs/`. Tuyệt đối không để trôi mất kiến thức trong lịch sử chat.
7. **Không dùng `speed` GPS thô**: Bắt buộc tính vận tốc dẫn xuất $\bar{v} = \Delta s / \Delta t$ và dùng ngưỡng dịch chuyển $\Delta s < 15\text{m}$ ($\Delta t \ge 20\text{s}$) để nhận diện dừng trạm.
8. **TimBus là Master Ground Truth**: Cổng TimBus (`timbus.vn` - Sở GTVT Hà Nội) là nguồn căn cứ tối thượng cho vị trí trạm dừng và tim đường. Mọi module phải ánh xạ qua bảng crosswalk chuẩn từ TimBus.

