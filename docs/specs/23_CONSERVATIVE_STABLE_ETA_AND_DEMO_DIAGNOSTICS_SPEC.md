# SPEC-23: ETA bảo thủ, ổn định hiển thị và chẩn đoán demo

**Trạng thái:** CẦN quyết định sản phẩm trước khi thay đổi code.  
**Phạm vi:** Module 3.4/3.5; không thay đổi các module frozen theo SPEC-19.

## 1. Sự thật runtime hiện tại

ETA serving **có dùng ML khi artifact runtime sẵn sàng**, không chỉ dùng baseline matrix. Kiểm tra trực tiếp ngày 2026-11-10: `ModelRuntime.load()` báo `available=True`, 54 feature và 384 ô calibrator; các artifact `r3_big` hiện có trong `data/models/`.

Luồng hiện tại là:

```
online features (54) -> XGBoost residual -> calibrated P50
                              | lỗi/không có model
                              v
                       baseline P50 matrix
```

`serving_service` gọi `predict_p50`; `eta_policy` dùng kết quả ML làm P50 khi khác `None`, còn baseline là fallback và nguồn P10/P90. Vì vậy một response live không tự chứng minh được ML đã thắng fallback; giao diện chẩn đoán cần công khai nguồn dự báo cho người test.

## 2. Mô hình sản phẩm cần giữ tách biệt

Gọi `T50` là P50 ước lượng kỹ thuật (ML hoặc fallback), `sigma` là bất định tích luỹ và `B >= 0` là phần đệm do rủi ro bất đối xứng. ETA bảo thủ là `Tc = T50 + B`; còn giá trị hiển thị là `M = ceil(Tc / 60)` phút. `T50`, `Tc` và `M` là ba đại lượng khác nhau, không được thay thế lẫn nhau.

- `B` làm giảm rủi ro hành khách đến muộn; nó không được dùng để che lỗi dữ liệu hay biến response rỗng thành ETA.
- Chỉ làm tròn **lên** ở tầng hiển thị. API/debug vẫn phải giữ giây và nguồn dự báo để kiểm tra.
- Cập nhật dữ liệu mới có thể làm `M` giảm hoặc tăng; không được hứa “đếm ngược mỗi giây”. Mọi ổn định/hysteresis là chính sách hiển thị riêng, không sửa ML.
- `ARRIVING_NOW` là trạng thái vật lý riêng, không phải kết quả `ceil`.

Các nguyên tắc đầu đã tồn tại một phần trong SPEC-15 và implementation hiện tại: buffer bất đối xứng, `ceil` phút và `display_text`. SPEC này không tự cho phép thay đổi hệ số buffer, policy ETA hay model.

## 3. Các lựa chọn cần người dùng quyết định

1. **Bảo thủ hiện tại, minh bạch:** giữ `Tc` và `ceil` phút hiện có; UI demo cho biết “ML” hoặc “baseline fallback”, P50, buffer và tuổi ping. Ít rủi ro nhất.

2. **Ổn định theo bucket phút:** chỉ đổi số phút khi ETA mới qua ranh giới phút; giữa hai lần poll không đếm ngược. Dễ hiểu nhưng số phút vẫn có thể giảm mạnh khi dữ liệu live mới tốt hơn.

3. **Hysteresis một chiều có điều kiện:** tăng ETA ngay khi cần; chỉ cho giảm sau khi cùng một bucket được quan sát liên tiếp. Ổn định hơn nhưng phải chọn số lần xác nhận và có thể giữ ETA cao hơn thực tế.

4. **Hai chế độ hiển thị:** hành khách chỉ thấy `M` phút/“đang cập bến”; chế độ debug của bạn thấy P10/P50/P90, `Tc`, buffer, nguồn model, ping age, tốc độ, trạng thái lọc xe và lý do không có ETA. Nên chọn cho demo hiện tại.

## 4. Contract chẩn đoán cho demo (đề xuất, chưa triển khai)

Khi chọn một trạm, panel debug phải hiển thị cho từng xe approaching:

| Nhóm | Trường quan sát |
| --- | --- |
| Nguồn | `prediction_source` = `ml_calibrated` hoặc `baseline_fallback`; model artifact availability |
| Ước lượng | P10, P50 (`T50`), buffer (`B`), conservative ETA (`Tc`), phút hiển thị (`M`) |
| Telemetry | ping timestamp, ping age, vị trí/tốc độ, khoảng cách và số trạm còn lại |
| Quyết định | trạng thái approaching/arriving/passed, traffic, delayed, lý do một xe bị loại |
| Empty state | phân biệt: upstream không có xe, không có xe đi tới trạm, geometry chưa sẵn sàng, input không hợp lệ |

Các trường debug phải là quan sát từ serving contract; không suy diễn nguyên nhân hoặc lộ token/credential. Chế độ này dành cho local demo, không phải UI hành khách cuối cùng.

## 5. Điều không làm trong milestone này

- Không đổi model, training data, matrix baseline hoặc các hệ số buffer khi chưa chọn một trong các lựa chọn ở mục 3.
- Không giả ETA/replay khi BusMap live rỗng (SPEC-22).
- Không redesign UI bây giờ. Giai đoạn UI/UX sau sẽ dùng `design-taste-frontend` với page type/site-kind `software`, app-frame chứa dữ liệu thật, layout kiểm tra tại các breakpoint và browser gate; không được để thẩm mỹ che diagnostic hoặc thay đổi contract ETA.

## 6. Thứ tự sau khi có quyết định

1. Ghi quyết định lựa chọn mục 3 và danh sách trường debug tối thiểu.
2. Architect bổ sung contract DTO/API cụ thể, gồm trạng thái backward-compatible.
3. Leaf coder triển khai phạm vi được chọn; white-box audit kiểm tra công thức, đơn vị, nguồn hằng số và ranh giới dữ liệu/UI.
4. Blind tester kiểm tra ML/fallback observable, `ceil`, empty state và stability policy đã chọn.
