# 31. LỘ TRÌNH KỸ THUẬT & 5 TRỞ NGẠI CỐT LÕI TÍCH HỢP BẢN ĐỒ - TÍNH TOÁN ETA

> [!NOTE] TÀI LIỆU LỊCH SỬ TRỞ NGẠI KỸ THUẬT (HISTORICAL R&D LOG)
> - **Trạng thái**: GHI NHẬN TIẾN TRÌNH KHẢO SÁT BAN ĐẦU (Có giá trị tham khảo học thuật, không phải đặc tả kỹ thuật cuối cùng).
> - **Bối cảnh lịch sử**: Nhật ký ghi nhận các trở ngại kỹ thuật thời kỳ OSM.
> - **Tài liệu chuẩn mực kế thừa**: Xem [48_COMPREHENSIVE_REMAINING_TASKS_AND_SYSTEM_ROADMAP.md](48_COMPREHENSIVE_REMAINING_TASKS_AND_SYSTEM_ROADMAP.md).

---

> **Dự án**: Hanoi Bus Big Data & Real-time ETA Prediction System  
> **Tài liệu tham chiếu**: Đúc kết từ phiên thảo luận định hướng kiến trúc ngày 19/10/2026.  
> **Nguyên tắc triển khai**: Thay thế cụm Apache nặng nề bằng cơ sở dữ liệu nhúng chuẩn `.db` (SQLite/DuckDB), xử lý tuần tự từng nút thắt kỹ thuật từ nhỏ đến lớn (Vertical Slice trên Tuyến 02).

---

## I. TỔNG QUAN KIẾN TRÚC HỆ THỐNG TRÊN NỀN TẢNG `.DB`

Thay vì triển khai cụm Hadoop/Spark cồng kềnh dễ gây bế tắc hạ tầng, toàn bộ dữ liệu telemetry và bản đồ được quản lý tập trung trong file cơ sở dữ liệu quan hệ/columnar chuẩn hóa:
* **Tệp cơ sở dữ liệu**: `data/telemetry_audit_2026_10_17_18.db` (và các view chuyên dụng cho ETA).
* **Đặc tính**: Zero-dependency, ANSI SQL tiêu chuẩn, sẵn sàng xuất sang Apache Parquet khi cần nghiệm thu đồ án Dữ liệu lớn.
* **Luồng dữ liệu tích hợp**:
  $$\text{Raw Telemetry (GPS)} \xrightarrow{\text{Map Matching}} \text{OSM Road Graph} \xrightarrow{\text{Station Unification}} \text{Trips} \xrightarrow{\text{Kinematics + Dwell}} \text{ETA Prediction}$$

---

## II. CHI TIẾT 5 TRỞ NGẠI KỸ THUẬT CỐT LÕI

```
[Raw GPS Ping (lat, lon, v, t)]
        │
        ▼  [Trở ngại 1: Lệch pha trạm]
┌────────────────────────────────────────────────────────┐
│ 1. STATION ID DISCREPANCY & SEMANTIC MISMATCH          │
│ Mã trạm BusMap (nội bộ) ≠ Mã trạm OSM (node_id toàn cầu)│
└────────────────────────────────────────────────────────┘
        │
        ▼  [Trở ngại 2: Nhiễu GPS & Khớp đường]
┌────────────────────────────────────────────────────────┐
│ 2. MAP MATCHING & ROAD PROJECTION DRIFT                │
│ GPS trôi dạt 15-30m, văng sang làn ngược chiều / cầu vượt│
└────────────────────────────────────────────────────────┘
        │
        ▼  [Trở ngại 3: Bóc tách chuyến xe]
┌────────────────────────────────────────────────────────┐
│ 3. TRIP SEGMENTATION & DEPOT FILTER                    │
│ 850 pings/ngày là chuỗi liên tục, không phân biệt nghỉ │
│ bến cuối vs xe đang chạy trên tuyến                    │
└────────────────────────────────────────────────────────┘
        │
        ▼  [Trở ngại 4: Bất định thời gian dừng]
┌────────────────────────────────────────────────────────┐
│ 4. DWELL TIME & JUNCTION DELAY STOCHASTICITY           │
│ Dừng đón khách + đèn đỏ chiếm 35-45% thời gian hành trình│
└────────────────────────────────────────────────────────┘
        │
        ▼  [Trở ngại 5: Độ trễ hệ thống]
┌────────────────────────────────────────────────────────┐
│ 5. COMMUNICATION LAG & DEAD RECKONING                  │
│ Dữ liệu nhận được trễ 54s - 120s so với thực tế ngoài đời│
└────────────────────────────────────────────────────────┘
        │
        ▼
   [DỰ BÁO ETA CHÍNH XÁC (MAE < 60s)]
```

---

### TRỞ NGẠI 1: Lệch pha định danh trạm (Station ID Discrepancy & Semantic Mismatch)
* **Bản chất vấn đề**:
  - Bản tin Telemetry chứa: `current_station_id = 1470`, `next_station_id = 1750` (mã quản lý của BusMap / Trung tâm điều hành xe buýt Hà Nội).
  - Bản đồ OSM chứa: `osm_id = 738815334`, `name = "Đối diện Bệnh viện 108"`, tọa độ `(lat, lon)`.
  - Hai hệ thống sử dụng không gian khóa ngoại hoàn toàn độc lập, không có foreign key liên kết tự nhiên.
* **Hậu quả**: Không biết xe buýt đang ở đoạn nào trên tuyến đường OSM và cách trạm dừng mục tiêu bao nhiêu mét.
* **Giải pháp kỹ thuật (Spatial Crosswalk)**:
  - Thực hiện thuật toán ghép nối không gian (Spatial Join / Nearest Neighbor Lookup) dựa trên tọa độ trung bình của các cụm ping và tọa độ node OSM trạm dừng trong bán kính $R < 50$m.
  - Xây dựng bảng tra cứu hợp nhất `station_crosswalk` trong file `.db`:
    `(route_id, busmap_station_id, osm_stop_id, sequence_no, distance_from_origin_m)`.
* **Tiêu chuẩn hoàn thành (DoD)**:
  - Tỉ lệ ghép nối đạt $100\%$ trạm dừng trên tuyến khảo sát (ví dụ Tuyến 02 có 72 trạm).
  - Sai số khoảng cách trung bình $< 25$m.

---

### TRỞ NGẠI 2: Nhiễu GPS & Bài toán Khớp đường (Map Matching & Projection Drift)
* **Bản chất vấn đề**:
  - Độ trôi dạt GPS đô thị ($\pm 15 - 30$m) tại các hẻm vực đô thị (Urban Canyons) như phố Cầu Giấy, Kim Mã, Nguyễn Trãi hoặc gầm cầu đường sắt Cát Linh - Hà Đông.
  - Chu kỳ phát tín hiệu $30\text{s} - 75\text{s}$ tạo ra các bước nhảy không gian từ $170\text{m} - 400\text{m}$.
  - Phép chiếu điểm đơn thuần (Nearest Edge) dễ làm xe bị chiếu nhầm sang đường một chiều đối diện hoặc đường nhánh song song.
* **Giải pháp kỹ thuật (Direction & Heading Constrained Projection)**:
  - Sử dụng góc la bàn (`heading_deg`) và chiều chạy (`direction`) của bản tin telemetry làm ràng buộc lọc.
  - Chỉ chiếu điểm GPS vào đoạn đường OSM có góc phương vị lệch không quá $45^\circ$ ($\Delta \theta \le 45^\circ$).
* **Tiêu chuẩn hoàn thành (DoD)**:
  - $100\%$ điểm GPS sau khi khớp nằm chính xác trên tim đường tuyến buýt OSM.
  - Loại bỏ hoàn toàn hiện tượng xe bị nhảy sang làn đối diện.

---

### TRỞ NGẠI 3: Bóc tách Chuyến xe (Trip Segmentation & Idle Depot Filter)
* **Bản chất vấn đề**:
  - Dữ liệu 1 xe buýt gồm ~850 pings trải dài liên tục suốt 17 tiếng.
  - Một xe chạy 6 – 8 lượt (Trips) giữa 2 đầu bến. Khi đến bến cuối (Bác Cổ hoặc Bến xe Yên Nghĩa), xe đỗ nghỉ 15 – 45 phút, vận tốc $v = 0$.
  - Nếu không cắt chuyến, mô hình sẽ nhầm tưởng xe đang bị tắc đường nghiêm trọng tại bến cuối.
* **Giải pháp kỹ thuật (Trip Slicer Algorithm)**:
  - Thuật toán tự động phát hiện ranh giới chuyến (Trip Boundary Detector):
    1. Trạng thái xe nằm trong bán kính bến cuối ($R < 150$m) VÀ thời gian dừng liên tục $> 5$ phút.
    2. Hoặc giá trị `direction` bị đảo trạng thái ($0 \leftrightarrow 1$).
  - Gán định danh chuyến: `trip_id = {vehicle_id}_{date}_{trip_seq}`.
* **Tiêu chuẩn hoàn thành (DoD)**:
  - Mỗi xe buýt được chia chính xác thành $N$ chuyến độc lập (thông thường 6 – 10 chuyến/ngày).
  - Không còn hiện tượng các chuyến xe bị nối đuôi vô tận.

---

### TRỞ NGẠI 4: Sự bất định của Thời gian dừng đỗ (Dwell Time Stochasticity)
* **Bản chất vấn đề**:
  - Công thức cơ học $\text{ETA} = \frac{\text{Khoảng cách}}{\text{Vận tốc}}$ luôn thất bại vì thời gian xe buýt dừng đón trả khách và chờ đèn đỏ chiếm từ **30% đến 45% tổng thời gian hành trình**.
  - Trạm vắng dừng $10\text{s}$, trạm đông sinh viên/bến xe dừng $60\text{s} - 90\text{s}$.
* **Giải pháp kỹ thuật (Decoupled ETA Formulation)**:
  - Tách ETA thành 2 thành phần độc lập:
    $$\text{ETA}(v \to S_k) = T_{\text{motion}}(v \to S_k) + \sum_{j=\text{current}}^{k-1} T_{\text{dwell}}(S_j, \text{hour})$$
  - Xây dựng bảng thống kê lịch sử `station_dwell_profiles` trong `.db` ghi nhận thời gian dừng trung bình của từng trạm theo khung giờ 15 phút.
* **Tiêu chuẩn hoàn thành (DoD)**:
  - Bảng thống kê Dwell Time cho toàn bộ các trạm dừng trên tuyến.
  - Giảm sai số MAE của ETA ít nhất 30% so với công thức vận tốc thuần túy.

---

### TRỞ NGẠI 5: Độ trễ truyền thông & Vùng mù (Communication Lag & Dead Reckoning)
* **Bản chất vấn đề**:
  - Bản tin GPS có độ trễ mạng thực tế $\sim 54$ giây, cộng với chu kỳ quét bot $\sim 75$ giây.
  - Vị trí xe trong DB trễ so với thực tế ngoài đời từ **50s đến 120s**. Trong khoảng thời gian đó, xe thực tế đã chạy trước từ **300m đến 600m**.
* **Giải pháp kỹ thuật (Kinematic Dead Reckoning)**:
  - Trước khi tính ETA, hệ thống tự động đẩy vị trí xe tiến lên phía trước một đoạn:
    $$\Delta s_{\text{bù}} = v_{\text{instant}} \times (t_{\text{now}} - t_{\text{device}})$$
  - Chiếu điểm tiên lượng này dọc theo tim đường OSM.
* **Tiêu chuẩn hoàn thành (DoD)**:
  - Vị trí tính toán ETA được đồng bộ hóa về đúng mốc thời gian truy vấn ($t_{\text{query}}$).

---

## III. MA TRẬN KẾ HOẠCH HÀNH ĐỘNG TUẦN TỰ

| Giai đoạn | Trọng tâm xử lý | Đối tượng mục tiêu | Sản phẩm đầu ra |
| :--- | :--- | :--- | :--- |
| **Giai đoạn 1** | **Trở ngại 1: Thống nhất trạm** | Tuyến 02 (Bác Cổ - BX Yên Nghĩa) | Bảng `station_crosswalk` trong file `.db` khớp 100% 72 trạm. |
| **Giai đoạn 2** | **Trở ngại 2 & 3: Khớp đường & Bóc tách Trip** | 16 xe Tuyến 02 ngày 18/10 | Bảng `bus_trips` với trajectory sạch, gán nhãn từng chuyến. |
| **Giai đoạn 3** | **Trở ngại 4 & 5: Dwell Time & Bù trễ Lag** | Mạng lưới Tuyến 02 | Bảng `dwell_time_matrix` và mô hình ETA Baseline đầu tiên. |
| **Giai đoạn 4** | **Đánh giá & Mở rộng** | Toàn bộ 49 tuyến | Báo cáo sai số MAE/RMSE/MAPE và nhân rộng pipeline. |

