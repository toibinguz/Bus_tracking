# BỘ QUY TẮC HOẠT ĐỘNG VÀ QUẢN TRỊ AI (GEMINI / ANTIGRAVITY RULES)
> Xem tài liệu gốc đầy đủ tại [AGENTS.md](file:///z:/Desktop/Bus_tracking/AGENTS.md)

## TÓM TẮT NGUYÊN TẮC HOẠT ĐỘNG BẮT BUỘC
1. **End-to-End Vertical Slice First**: Ưu tiên xây dựng luồng thông suốt từ Ingestion -> Big Data Lakehouse -> Ma Trận Thời Gian Di Chuyển (Travel Time Matrix) -> Serving/Evaluation. Tuyệt đối không sa đà tối ưu quá mức ở tầng crawl.
2. **Data Contract Freeze**: Tầng crawler GitHub Actions đã ổn định 24/7. Coi nó là Black-box Service, không tự ý sửa đổi code socket/network.
3. **Phân định ranh giới 3 Module chính tắc**:
   - `module_1_data_ingestion_and_preprocessing`, `module_2_big_data_storage_and_lakehouse`, `module_3_bus_eta_prediction`: Chỉ chứa code production hoàn chỉnh, sạch, có kiểm thử.
   - `experiments/`: Chứa các script phân tích ad-hoc, nháp, audit tạm thời.
4. **Trọng tâm hiện tại (Không vội chốt ML)**:
   - Tầng 1 (Thu thập & Tiền xử lý dữ liệu): ĐÃ ĐẠT TIÊU CHUẨN HOÀN THÀNH (DONE) cho cả 48 tuyến. Chuyển sang chế độ chạy ngầm.
   - Tầng 2 (Lưu trữ & Xử lý Dữ liệu Lớn - Trọng tâm môn học): Chuẩn hóa CSDL `hanoi_bus_system.db`, hồ dữ liệu Medallion Parquet (Bronze -> Silver -> Gold).
   - Tầng 3 (Dự báo ETA): **ƯU TIÊN HÀNG ĐẦU LÀ XÂY DỰNG MA TRẬN THỜI GIAN DI CHUYỂN PHÂN ĐOẠN (TRAVEL TIME MATRIX)** cho 48 tuyến theo khung giờ và loại ngày (Bảng `agg_segment_travel_times`). Tạm hoãn Machine Learning phức tạp cho đến khi ma trận hoàn tất 100%.
5. **Nghiêm cấm suy đoán vô căn cứ ("Không chém gió")**: Mọi kết luận kỹ thuật, số liệu, độ trễ hay sai số phải có code thực thi và dữ liệu định lượng chứng minh. Tuyệt đối không bịa số liệu, không tự ý suy đoán siêu tham số ML.
6. **Tài liệu hóa bắt buộc & Trình duyệt trước khi code**: Lập tài liệu đặc tả (.md) trong `docs/` để người dùng phê duyệt phương án trước; chỉ triển khai mã nguồn khi có lệnh cho phép.
7. **Không dùng `speed` GPS thô**: Bắt buộc tính vận tốc dẫn xuất $\bar{v} = \Delta s / \Delta t$ và dùng ngưỡng dịch chuyển $\Delta s < 15\text{m}$ ($\Delta t \ge 20\text{s}$) để nhận diện dừng trạm.
8. **TimBus là Master Ground Truth**: Cổng TimBus (`timbus.vn` - Sở GTVT Hà Nội) là nguồn căn cứ tối thượng cho vị trí trạm dừng và tim đường của 48 tuyến.
