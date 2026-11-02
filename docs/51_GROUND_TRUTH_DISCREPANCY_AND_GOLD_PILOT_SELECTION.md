# BÁO CÁO NGHIỆP VỤ: XUNG ĐỘT NGUỒN CHÂN LÝ, PHÂN HẠNG TUYẾN VÀ CHIẾN LƯỢC PILOT CHUẨN VÀNG (GOLD STANDARD)
> **Tài liệu đặc tả nghiệp vụ**: Số 51 trong chuỗi tài liệu `docs/`  
> **Căn cứ**: Hiến pháp AI ([AGENTS.md](file:///z:/Desktop/Bus_tracking/AGENTS.md) - Điều 1, Điều 4, Điều 6)  
> **Mục tiêu**: Làm rõ bản chất xung đột giữa các nguồn dữ liệu trắc địa, phương pháp bóc tách dị thường bãi đỗ và tiêu chuẩn xác lập 15 tuyến Pilot Chuẩn Vàng phục vụ Báo cáo Tiến độ Lần 2.

---

## I. BỐI CẢNH & PHÁT HIỆN THỰC ĐỊA: NGUY CƠ TỪ VIỆC ĐÓNG BĂNG MÙ QUÁNG

### 1. Hiện Tượng Thực Địa Tuyến E04 (Case Study Hà Đông)
Qua quá trình kiểm toán trực quan trên bản đồ trắc địa vệ tinh và hình ảnh thực địa, hệ thống phát hiện một sự sai lệch nghiêm trọng giữa dữ liệu hành chính và lộ trình vận hành thực tế:
- **Dữ liệu tim đường TimBus (TRAMOC / Sở GTVT)**: Vẫn lưu giữ tour tuyến cũ. Sau khi xe chạy hết đường Tố Hữu, tuyến rẽ về phía Tây Nam chạy một vòng cung rất xa qua khu vực đô thị Dương Nội - Khu đô thị An Hưng - Lê Trọng Tấn, sau đó mới quay lại đường Quang Trung. Danh bạ trạm dừng chính thức (Station Master) của TimBus cũng rải rác dọc theo vòng cung Dương Nội này.
- **Lộ trình vận hành thực tế (GPS Telemetry & BusMap)**: Toàn bộ dàn xe buýt điện E04 ngoài thực địa không hề đi vòng qua Dương Nội. Khi đến ngã tư Tố Hữu - Vạn Phúc, xe rẽ phải đi thẳng theo hành lang **Vạn Phúc $\to$ Chu Văn An $\to$ Quang Trung**.
- **Hậu quả nếu đóng băng sớm**: 
  - Khoảng cách sai lệch vuông góc giữa vệt xe chạy thực tế và tim đường TimBus lên tới **$2.536\text{ m}$ (2.54 km)**.
  - Toàn bộ các ping GPS thực tế trên trục Vạn Phúc khi bị ép chiếu (project) vuông góc vào nhánh vòng Dương Nội sẽ sinh ra các giá trị tiến độ tọa độ $s$ sai lệch hàng chục cây số, gây hiện tượng nhảy cóc tiến độ ($\Delta s$ âm lớn hoặc dương đột biến) và bóp méo hoàn toàn thời gian hành trình liên trạm.
  - Các trạm xe buýt trên nhánh Dương Nội không bao giờ có xe đi qua, tạo ra các "trạm chết" (zero-visit stations) trong mô hình.

```
       [TimBus Cũ - Đi Vòng]
       ┌───────────────────────────┐
       │ Dương Nội ──> Lê Trọng Tấn│
       ▼                           │  (Lệch thực địa ~ 2.5 km)
[Tố Hữu] ──────────────────────────┴─> [Quang Trung]
       │
       └──> [Vạn Phúc ──> Chu Văn An] ──┘
            [Xe Chạy Thực Tế & BusMap]
```

### 2. Nguyên Tắc Ứng Xử Với Nguồn Chân Lý Dữ Liệu
Mặc dù [AGENTS.md](file:///z:/Desktop/Bus_tracking/AGENTS.md) Điều 4 quy định TimBus là Master Ground Truth, nhưng thực tế quản trị công cộng cho thấy cơ sở dữ liệu nhà nước có độ trễ cập nhật nhất định đối với các tuyến mới điều chỉnh hành lang (đặc biệt là các tuyến xe buýt điện VinBus mới mở).  
Do đó, nguyên tắc tác chiến chính xác là:
> **Không đóng băng mù quáng trên toàn bộ 48 tuyến.** Thay vào đó, thiết lập cơ chế kiểm định chéo độc lập (Independent Cross-check) để sàng lọc ra tập các **Tuyến Chuẩn Vàng (Gold Standard Routes)** – nơi dữ liệu TimBus, dữ liệu OpenStreetMap và vết di chuyển GPS thực tế hoàn toàn trùng khớp 100%. Triển khai sản phẩm End-to-End thông suốt trên tập tuyến này trước.

---

## II. PHƯƠNG PHÁP BÓC TÁCH DỊ THƯỜNG BÃI ĐỖ & DỪNG NGHỈ ĐẦU CUỐI

Một nguyên nhân lớn làm biến dạng chỉ số chất lượng bám làn ($d_\perp$) là sự nhầm lẫn giữa **xe buýt đang chở khách trên tuyến (Operational In-Service)** và **xe buýt đang đỗ nghỉ/sửa chữa (Depot/Terminal Dwell)**:

### 1. Hiện Tượng Xe Chết Bãi Đỗ (Gara Workshop Anomaly)
- **Minh chứng Tuyến 39**: Có 2.336 trên tổng số 4.523 pings (chiếm **51.6%**) thuộc về 2 phương tiện mang biển số `29B19755` và `29B20953`. Hai xe này nằm bất động cả ngày tại xưởng kỹ thuật ở Thanh Trì (cách lộ trình đường gom Giải Phóng hàng trăm mét).
- **Thuật toán bóc tách xe chết**:
  Một xe được xác định là xe không vận hành nếu biên độ dịch chuyển không gian cả ngày của nó thỏa mãn:
  $$\text{Span}(s) = \max_{t}(s_{\text{bus}}) - \min_{t}(s_{\text{bus}}) < 1.000\text{ m} \quad \text{với } N_{\text{pings}} > 50$$
  Toàn bộ dữ liệu của xe này được phân loại là `depot_garage_parked` và loại khỏi tập phân tích vận tốc/hành trình.

### 2. Hiện Tượng Chờ Khởi Hành Tại Bến Đầu/Cuối (Terminal Dwell)
- Tại hai đầu bến (như Bến xe Yên Nghĩa, Bến xe Mỹ Đình, Công viên Cầu Giấy), xe buýt dừng đỗ xếp nốt, xoay đầu hoặc đỗ trong sân bãi rộng hàng trăm mét, khiến tọa độ GPS nằm lệch khỏi tim đường xuất phát.
- **Tiêu chí bóc tách dừng nghỉ bến**:
  $$s_{\text{bus}} < 300\text{ m} \quad \text{HOẶC} \quad s_{\text{bus}} > (S_{\max} - 300\text{ m})$$
  kết hợp điều kiện động học: $V_{\text{derived}} < 5.0\text{ km/h}$ hoặc cờ dừng đỗ `is_dwell == 1`.
- Dữ liệu này được tách riêng thành `terminal_dwell`, không tính vào sai số trượt làn khi xe đang chạy.

---

## III. BẢNG PHÂN HẠNG THỰC NGHIỆM 48 TUYẾN XE BUÝT HÀ NỘI

Dựa trên kết quả chạy script kiểm toán [`audit_clean_routes.py`](file:///z:/Desktop/Bus_tracking/experiments/route_cleanliness_audit/audit_clean_routes.py) đối chiếu trên toàn bộ **646.823 pings** (cả 2 chiều `go` và `re`) với kho dữ liệu OpenStreetMap transit relations:

### 1. Nhóm Tier 1: 15 Tuyến Chuẩn Vàng (Gold Standard Pilot Routes)
*Đặc điểm: Tỷ lệ pings bám làn $d_\perp \le 30\text{m}$ đạt $> 90\%$, trung vị sai lệch $d_\perp \le 6\text{m}$, độ lệch tim đường TimBus so với OpenStreetMap $\le 15\text{m}$. Hoàn toàn không có rủi ro đổi tour.*

| Tuyến | Tên Tuyến Chính Thức | Số Ping Vận Hành | Tỷ Lệ Bám Làn $\le 30\text{m}$ | Trung Vị $d_\perp$ | Độ Lệch Tim Đường OSM (Đi / Về) | Ghi Chú Vận Hành |
| :---: | :--- | :---: | :---: | :---: | :---: | :--- |
| **E05** | Long Biên - Cầu Giấy - KĐT Smart City | 6.960 | **97.3%** | 4.8 m | 7.0 m / 6.3 m | VinBus chất lượng cao, chuẩn tuyệt đối |
| **22A** | Bến xe Gia Lâm - KĐT Trung Văn | 18.707 | **96.9%** | 4.8 m | 8.2 m / 7.1 m | Trục huyết mạch Cầu Giấy - Phạm Hùng |
| **99** | Kim Mã - Bệnh viện Nội tiết TW | 6.261 | **96.8%** | 4.2 m | 4.9 m / 7.0 m | Tuyến nội đô cực sạch |
| **38** | Nam Thăng Long - Mai Động | 6.075 | **96.1%** | 5.1 m | 6.9 m / 5.1 m | Đã bóc tách 15.9% ping bãi đỗ |
| **26** | Mai Động - Sân vận động Quốc gia | 13.837 | **95.8%** | 4.3 m | 6.1 m / 4.7 m | Trục xuyên tâm hoàn hảo |
| **02** | Bác Cổ - Bến xe Yên Nghĩa | 19.778 | **95.6%** | 5.0 m | 7.7 m / 6.1 m | Tuyến xương sống Quang Trung - Trần Phú |
| **19** | Trần Khánh Dư - Bến xe Yên Nghĩa | 16.400 | **94.4%** | 6.0 m | 5.9 m / 10.3 m | Dọc trục Nguyễn Trãi - Hà Đông |
| **11** | CV Thống Nhất - HV Nông nghiệp | 9.311 | **94.3%** | 4.7 m | 5.8 m / 6.0 m | Qua cầu Chương Dương - Gia Lâm |
| **BRT01**| Bến xe Kim Mã - Bến xe Yên Nghĩa | 11.011 | **94.1%** | 8.8 m | 8.7 m / 12.6 m | Làn dành riêng, pings bám sát dải phân cách |
| **34** | Bến xe Mỹ Đình - Trung tâm Hành chính Gia Lâm | 17.598 | **91.7%** | 4.2 m | 7.3 m / 7.7 m | Trục Kim Mã - Cầu Giấy |
| **01** | Bến xe Gia Lâm - Bến xe Yên Nghĩa | 6.824 | **91.6%** | 5.2 m | 5.4 m / 7.7 m | Tuyến huyết mạch số 1 Hà Nội |
| **05** | Mai Động - Cầu Giấy | 9.360 | **91.1%** | 5.1 m | 6.3 m / 8.3 m | Vành đai 2 |
| **146** | Hào Nam - Khu liên cơ quan TP Hà Nội | 13.044 | **91.0%** | 5.8 m | 7.2 m / 6.8 m | Tuyến vành đai vòng tròn |
| **37** | Bến xe Giáp Bát - Chương Mỹ | 12.805 | **90.9%** | 5.1 m | 8.0 m / 8.2 m | Hướng Tây Nam |
| **92** | Nhổn - Tây Đằng (Ba Vì) | 7.740 | **90.3%** | 5.2 m | 17.4 m / 13.1 m | Tuyến ngoại thành đường thẳng |

### 2. Nhóm Tier 2: 12 Tuyến Tiềm Năng (Silver Routes)
Gồm các tuyến: **64, 17, 56B, 08A, 105, 21A, 48, 43, 13, 32, 27, 40**.  
Tỷ lệ bám làn đạt từ **80% đến 89%**. Độ lệch trung vị dưới $7.5\text{m}$. Nhóm này hoạt động tốt, chỉ bị lệch nhẹ ở các nút giao có cầu vượt phức tạp (như ngã tư Kim Mã - Daewoo, Ngã Tư Sở) hoặc điểm quay đầu dưới gầm cầu.

### 3. Nhóm Tier 3: 21 Tuyến Cách Ly Tạm Thời (Flagged / Red Routes)
Gồm các tuyến: **E04** (lệch 2.5km ở Vạn Phúc), **61** (lệch 5.2km qua cầu Thăng Long/Nam Hồng), **E11** (xe không chạy thực tế, lệch 4.6km), **39** (nhiễm nặng bãi đỗ Thanh Trì), **107, 28, 101A, E06, E03, 122, 42**...  
Các tuyến này **tuyệt đối không đưa vào xây dựng ma trận ETA ban đầu** để bảo toàn tính toàn vẹn của mô hình.

---

## IV. LỘ TRÌNH THỰC HIỆN 10 NGÀY CHO BÁO CÁO TIẾN ĐỘ LẦN 2

Để đạt kết quả cao nhất trong đợt Báo cáo Tiến độ Lần 2, toàn bộ nhóm thống nhất triển khai theo hướng **Vertical Slice** (luồng thông suốt từ Ingestion $\to$ Lakehouse $\to$ Travel Time Matrix $\to$ Serving Dashboard) trên tập **15 Tuyến Chuẩn Vàng**:

```
[Day 1] (XONG) Kiểm toán & Chốt 15 Tuyến Vàng
   │
[Day 2 - 3] Module 2: Medallion Lakehouse (Parquet + DuckDB Analytics)
   │
[Day 4 - 6] Module 3: Ma Trận Thời Gian Di Chuyển P50 & Hàm Suy Luận ETA
   │
[Day 7 - 8] Module 4: Kiểm Định Sai Số vs BusMap & Web Dashboard Leaflet
   │
[Day 9 - 10] Hoàn Thiện Slide Deck, Báo Cáo Kỹ Thuật & Diễn Tập Báo Cáo
```

1. **Ngày 2 – 3 (Lakehouse Columnar)**: Chuyển đổi toàn bộ pings của 15 Tuyến Vàng sang Parquet chuẩn Medallion (Silver layer: Clean Telemetry, Gold layer: Segment Transitions). Thiết lập truy vấn phân tích DuckDB siêu tốc.
2. **Ngày 4 – 6 (ETA Engine Core)**: Xây dựng thuật toán nội suy thời điểm qua trạm $t_{\text{cross}}$, lập bảng ma trận thời gian di chuyển theo khung giờ ($P_{10}, P_{50}, P_{90}$) và hàm dự báo ETA trực tiếp theo vị trí $s_{\text{bus}}$.
3. **Ngày 7 – 8 (Kiểm định & Demo)**: Đo lường sai số MAE, đối chứng với ETA của BusMap, dựng Dashboard trực quan để demo tương tác trực tiếp trước hội đồng.
4. **Ngày 9 – 10 (Đóng gói sản phẩm)**: Soạn thảo Slide thuyết trình, hoàn thiện văn bản báo cáo và chuẩn bị các kịch bản phản biện kỹ thuật.

