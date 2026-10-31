# BỘ QUY TẮC HOẠT ĐỘNG VÀ QUẢN TRỊ AI (GEMINI / ANTIGRAVITY RULES)
> Xem tài liệu gốc đầy đủ tại [AGENTS.md](file:///z:/Desktop/Bus_tracking/AGENTS.md)

## TÓM TẮT NGUYÊN TẮC HOẠT ĐỘNG TỐI CAO
1. **Thực nghiệm là chân lý (Empirical Verification Only)**: Nghiêm cấm mọi suy đoán vô căn cứ hoặc "chém gió". Mọi kết luận, chỉ số hay phân tích phải có mã nguồn, dữ liệu thực tế hoặc kiểm thử chứng minh.
2. **Thiết kế trước, duyệt rồi mới code (Design First, Approve, Then Implement)**: Mọi kế hoạch hoặc thay đổi phải được tài liệu hóa thành file đặc tả trong `docs/` để người dùng phê duyệt trước khi viết mã nguồn can thiệp hệ thống.
3. **Tách biệt ranh giới Production vs. Experiment**:
   - `module_1`, `module_2`, `module_3`: Chỉ chứa mã nguồn Production sạch sẽ, hoàn thiện, có type hints và kiểm thử.
   - `experiments/`: Nơi duy nhất chứa code nháp, script ad-hoc và phân tích tạm thời.
4. **Đóng băng crawler contract**: Tầng cào dữ liệu đám mây 24/7 đã ổn định và có watchdog tự phục hồi. Coi đây là Black-box Service, không tự ý sửa đổi logic mạng.
5. **Nguồn chân lý dữ liệu tối thượng**: TimBus (TRAMOC / Sở GTVT Hà Nội) là Master Ground Truth duy nhất cho mạng lưới tuyến, trạm dừng và tim đường.
6. **Động học dẫn xuất**: Mọi tính toán vận tốc, dừng đỗ và ETA phải dựa trên vận tốc dẫn xuất không gian - thời gian ($\bar{v} = \Delta s / \Delta t$) và ngưỡng dịch chuyển không gian, tuyệt đối không dùng trường `speed == 0` thô từ GPS.
7. **Phân tầng trọng tâm**: Hoàn thiện vững chắc tầng dữ liệu lớn và Ma trận thời gian thống kê trước khi xem xét các mô hình Machine Learning phức tạp.
8. **Tách bạch Hiến pháp vs. Chi tiết thiết kế**: Toàn bộ chi tiết toán học, thuật toán và schema bảng thuộc về thư mục `docs/`, không đưa tiểu tiết vào Hiến pháp.
