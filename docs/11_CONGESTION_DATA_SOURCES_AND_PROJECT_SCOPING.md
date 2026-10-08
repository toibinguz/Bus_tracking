# Báo Cáo Đánh Giá Toàn Diện Các Nguồn Dữ Liệu Tắc Nghẽn & Chiến Lược Quy Mô Dự Án (Project Scoping)

## 1. Kết Luận Khảo Sát Các Nhà Cung Cấp Bản Đồ & Traffic Ngoại Vi

Trong quá trình tìm kiếm giải pháp lấy dữ liệu tắc nghẽn (mức độ xanh/vàng/đỏ, tốc độ thực tế $v_{\text{current}}$) quy mô thành phố, hệ thống đã tiến hành khảo sát và đo kiểm chi tiết 4 nhà cung cấp hàng đầu:

| Nguồn dữ liệu | Loại API & Khả năng trích xuất JSON | Mức độ phù hợp kỹ thuật | Rào cản cốt lõi | Kết luận |
| :--- | :--- | :--- | :--- | :--- |
| **VietMap** | **Route v4/v3** (`annotations=congestion`) trả enum: `low`, `moderate`, `heavy`, `severe`. Vector tile PBF (`/tf/{z}/{x}/{y}.pbf`). | Trung bình | **1.** Doc quy định rõ: *Không chính xác khi truyền > 2 waypoints*.<br>**2.** Dịch vụ thương mại nội địa, không có Free Tier mở 24/7. | **LOẠI BỎ** (Theo quyết định của người dùng) |
| **HERE Technologies** | Traffic Flow API v7 (`vector/flow`). | Thấp | Không cung cấp trường $v_{\text{current}}$ và $v_{\text{freeFlow}}$ chi tiết theo từng phân đoạn OpenLR nếu không dùng gói Enterprise đắt đỏ; độ trễ cập nhật tại VN cao. | **LOẠI BỎ** |
| **Google Maps** | Distance Matrix / Routes API. | Rất thấp cho Big Data | Chỉ trả về `duration_in_traffic`, không bóc tách được vận tốc thực trên từng phân đoạn đường nhỏ; chi phí cực kỳ đắt đỏ ($5 - $10 / 1.000 req), không có gói free tier lớn. | **LOẠI BỎ** |
| **TomTom** | **FlowSegmentData API** trả chính xác $v_{\text{current}}$, $v_{\text{freeFlow}}$, $t_{\text{travel}}$, $t_{\text{freeFlow}}$, confidence score. | **Rất cao** | Giới hạn hạn ngạch Free Tier: **2.500 requests/ngày** (không đủ quét toàn bộ 230 tuyến bus với ~3.000 đường phân đoạn). | **GIỮ LẠI (Làm Ground-Truth & Hiệu chuẩn)** |

---

## 2. Vì Sao Không Nên Phụ Thuộc Vào API Traffic Ngoại Vi?

1. **Nghịch lý chi phí và quy mô**:
   - Toàn mạng lưới Hà Nội có **230 tuyến xe buýt**, bao phủ hơn **3.000 phân đoạn đường trọng điểm**.
   - Nếu thăm dò mỗi phân đoạn 5 phút/lần trong 16 giờ hoạt động/ngày:
     $$\text{Số request cần thiết} = 3.000 \times \left(\frac{16 \times 60}{5}\right) = 3.000 \times 192 = 576.000 \text{ req/ngày}$$
   - Bất kỳ API thương mại nào (kể cả TomTom, Google hay VietMap) ở quy mô 576.000 req/ngày đều tiêu tốn hàng nghìn USD/tháng, hoàn toàn bất khả thi cho đề tài nghiên cứu hoặc hệ thống Big Data phi lợi nhuận.

2. **Hạn chế cấu trúc dữ liệu của Route API (VietMap/OSRM)**:
   - Các API Routing chỉ trả `annotations` khi giải bài toán tìm đường từ A đến B (chỉ 2 điểm). Khi cố gắng ép cả tuyến xe buýt (30-50 điểm dừng) vào 1 request, thuật toán định tuyến sẽ nảy sinh lỗi ghép đường (Map-matching mismatch) và doc cảnh báo dữ liệu mất tính chính xác.

---

## 3. Lời Giải Tối Thượng: Tự Nội Sinh Dữ Liệu Giao Thông ("Bus-as-a-Probe")

Thay vì phải đi mua dữ liệu giao thông bên ngoài, **chúng ta đang nắm giữ nguồn tài nguyên quý giá nhất: 935 xe buýt công cộng đang di chuyển liên tục trên mọi nẻo đường Hà Nội!**

```
 [935 Xe Buýt Hà Nội] (Crawl mỗi 60s)
         │
         ▼
 [Tọa độ GPS + Timestamp] (lat, lon, t)
         │
         ▼
 [Map-Matching vào OpenStreetMap (OSM)] (Valhalla / OSRM Engine)
         │
         ├──> Tính vận tốc thực tế trên từng Road Segment:
         │    v_segment = Δs / Δt
         │
         └──> Phân lớp tắc nghẽn (Congestion Classification):
              • Thông thoáng (Xanh): v >= 30 km/h (hoặc v >= 0.8 v_freeFlow)
              • Chậm vừa (Vàng):      18 <= v < 30 km/h
              • Tắc nghẽn (Đỏ):       8 <= v < 18 km/h
              • Tắc nghẽn nghiêm trọng (Đỏ đậm): v < 8 km/h
```

### Ưu điểm vượt trội:
1. **Hoàn toàn miễn phí 100%**: Sử dụng dữ liệu telemetry crawl trực tiếp từ hệ thống BusMap HN (đã xác thực thành công 935 xe hoạt động).
2. **Không bị giới hạn trần API**: Dữ liệu do chính cụm xử lý Big Data nội bộ tính toán.
3. **Phản ánh đúng thực tế làn xe buýt**: Vận tốc của xe buýt đo được chính là vận tốc tham chiếu sát nhất cho mô hình dự báo ETA của chính xe buýt (thay vì vận tốc xe máy hay ô tô con vốn có làn di chuyển khác).

---

## 4. Vai Trò Của TomTom: Hiệu Chuẩn & Bù Đắp "Điểm Mù" (Zero-Blindspot Calibration)

TomTom (với hạn ngạch 2.500 req/ngày) không bị lãng phí, mà được định vị ở cấp độ cao hơn:
1. **Hiệu chuẩn (Ground-Truth Calibration)**: Lấy mẫu tại các nút giao huyết học (Cầu Giấy, Kim Mã, Ngã Tư Sở) để kiểm định độ tin cậy của thuật toán tính tốc độ từ Bus GPS.
2. **Bù đắp khoảng trống (Gap-Filling)**: Khi một đoạn đường chưa có xe buýt nào chạy qua trong vòng 10-15 phút (ví dụ đầu giờ sáng hoặc sau giờ cao điểm), hệ thống kích hoạt 1 request TomTom FlowSegmentData để cập nhật trạng thái đường.

---

## 5. Chiến Lược Thu Hẹp Quy Mô Thử Nghiệm (Project Scoping)

Để đảm bảo dự án triển khai thành công, hệ thống Big Data (Kafka + Spark Streaming + Redis) cần tập trung chứng minh tính hiệu quả trên **3 tuyến hành lang trọng điểm (Pilot Routes)** trước khi mở rộng:

| Tuyến | Lộ trình | Đặc tính giao thông | Số xe hoạt động | Số điểm dừng |
| :---: | :--- | :--- | :---: | :---: |
| **Tuyến 01** | **Bến xe Gia Lâm ⇄ Bến xe Yên Nghĩa** | Trục xuyên tâm dài nhất Hà Nội, đi qua các điểm nóng: Nguyễn Trãi, Tây Sơn, Hai Bà Trưng, Cầu Chương Dương. Rất hay ùn tắc. | 22 xe | 54 điểm dừng |
| **Tuyến 32** | **Bến xe Giáp Bát ⇄ Nhổn** | Trục kết nối Đông Nam - Tây Bắc, đi qua Giải Phóng, Lê Duẩn, Cầu Giấy, Xuân Thủy, Hồ Tùng Mậu. Mật độ đèn đỏ và ngã tư cực cao. | 24 xe | 58 điểm dừng |
| **Tuyến 02** | **Bác Cổ ⇄ Bến xe Yên Nghĩa** | Trục huyết mạch song song Nguyễn Trãi - Trần Phú, có sự cạnh tranh trực tiếp với đường sắt đô thị Cát Linh - Hà Đông. | 18 xe | 48 điểm dừng |

### Bài toán số lượng phân đoạn:
- 3 tuyến này chia sẻ nhiều đoạn đường chung. Tổng cộng có khoảng **60 phân đoạn đường trọng điểm (hotspot segments)**.
- Với 60 phân đoạn này:
  - Dữ liệu Bus-as-a-Probe bao phủ **85% - 90%** thời gian trong ngày.
  - 10% - 15% thời gian còn lại (điểm mù) chỉ tiêu tốn khoảng **400 - 600 request TomTom/ngày**, hoàn toàn nằm gọn trong trần an toàn 2.500 req/ngày!

