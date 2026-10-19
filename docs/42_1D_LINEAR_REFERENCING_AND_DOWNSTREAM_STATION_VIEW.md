# 42. VỊ TRÍ 1D CỦA TRẠM, VỊ TRÍ ÁNH XẠ CỦA XE VÀ VIEW TÍNH TOÁN ETA
> **Dự án**: Hanoi Bus Big Data & Real-time ETA Prediction System  
> **Cơ sở dữ liệu**: [`data/telemetry_audit_2026_10_17_18.db`](file:///z:/Desktop/Bus_tracking/data/telemetry_audit_2026_10_17_18.db)  
> **Ngày cập nhật**: 19/10/2026  

---

## 1. KHẲNG ĐỊNH HIỆN TRẠNG DỮ LIỆU: CẢ HAI ĐỀU ĐÃ HOÀN TẤT VÀ NẰM TRONG DATABASE

### 1.1. Vị trí 1D của các trạm dừng ($s_k$)
* **Bảng lưu trữ**: `dim_station_crosswalk` và `timbus_station_master`.
* **Cột định vị**: `cum_distance_m` (khoảng cách mét lũy kế dọc theo tim đường chính thức từ đầu bến).
* **Mẫu trích xuất Chiều đi Tuyến 02 (Bác Cổ $\to$ BX Yên Nghĩa)**:
  * Trạm 01 `[1667]` (A) Bác Cổ: $s = \mathbf{0,00\text{ m}}$
  * Trạm 02 `[759]` Trần Khánh Dư: $s = \mathbf{111,97\text{ m}}$
  * Trạm 03 `[754]` ĐD Viện 108: $s = \mathbf{667,38\text{ m}}$
  * Trạm 04 `[347]` ĐH Khoa học Tự nhiên: $s = \mathbf{1.039,10\text{ m}}$
  * ...
  * Trạm 38 `[650]` Nissan Hà Đông: $s = \mathbf{16.606,94\text{ m}}$
  * Trạm 39 `[1470]` ĐD TH Kinh tế Hà Tây: $s = \mathbf{16.937,53\text{ m}}$
  * Trạm 40 `[1750]` (B) BX Yên Nghĩa: $s = \mathbf{17.415,84\text{ m}}$

### 1.2. Vị trí 1D ánh xạ của xe buýt lên tim đường ($s_{bus}$)
* **Bảng lưu trữ**: `route_02_projected_telemetry` (**23.258 bản tin GPS**).
* **Các trường định lượng**:
  * `s_bus_m`: Mét thứ mấy xe đang chạy trên tim đường.
  * `cross_track_m` ($d_\perp$): Vi sai độ lệch ngang tới tim đường (trung vị $5,6\text{m}$, dùng để lọc nhiễu $\le 30\text{m}$).
  * `derived_speed_kmh` ($\bar{v}$): Vận tốc dẫn xuất không gian - thời gian $\frac{\Delta s}{\Delta t}$ (tuân thủ nguyên tắc không dùng `speed` GPS thô).
  * `direction`: Hướng chạy (`go` hoặc `re`).

---

## 2. GHÉP NỐI THÔNG SUỐT: VIEW TÍNH TOÁN KHOẢNG CÁCH TỚI TRẠM TIẾP THEO

Để mô hình ETA truy vấn tức thời trong thời gian thực, hệ thống đã tạo sẵn View:
**`v_route_02_bus_to_next_station`**

```sql
SELECT 
    t.ping_id,
    t.fleet_code,
    t.timestamp,
    t.direction,
    t.s_bus_m,
    t.derived_speed_kmh,
    s.station_order AS next_station_order,
    s.station_id AS next_station_id,
    s.station_name AS next_station_name,
    s.cum_distance_m AS next_station_s,
    ROUND(s.cum_distance_m - t.s_bus_m, 2) AS distance_remaining_m
FROM route_02_projected_telemetry t
JOIN dim_station_crosswalk s
  ON t.direction = s.direction 
 AND s.cum_distance_m = (
     SELECT MIN(s2.cum_distance_m)
     FROM dim_station_crosswalk s2
     WHERE s2.direction = t.direction 
       AND s2.cum_distance_m >= t.s_bus_m
 );
```

### Mẫu dữ liệu truy vấn thực tế:
| Xe buýt | Thời điểm | Vị trí xe ($s_{bus}$) | Vận tốc $\bar{v}$ | Trạm tiếp theo sắp tới | Khoảng cách còn lại |
| :---: | :---: | :---: | :---: | :--- | :---: |
| `231968` | 13:33:55 | $270,0\text{ m}$ | $15,2\text{ km/h}$ | ĐD Bệnh viện Quân đội 108 | **$397,4\text{ m}$** |
| `1408401` | 05:45:11 | $318,2\text{ m}$ | $18,1\text{ km/h}$ | ĐD Bệnh viện Quân đội 108 | **$349,1\text{ m}$** |
| `231967` | 20:25:00 | $349,1\text{ m}$ | $16,0\text{ km/h}$ | ĐD Bệnh viện Quân đội 108 | **$318,2\text{ m}$** |
| `231971` | 09:04:18 | $355,3\text{ m}$ | $26,7\text{ km/h}$ | ĐD Bệnh viện Quân đội 108 | **$312,0\text{ m}$** |
| `231972` | 17:06:10 | $362,1\text{ m}$ | $15,2\text{ km/h}$ | ĐD Bệnh viện Quân đội 108 | **$305,3\text{ m}$** |

---

## 3. CÔNG THỨC DỰ BÁO ETA BASELINE SẴN SÀNG

Khoảng thời gian dự báo xe đến trạm tiếp theo:
$$\widehat{T}_{ETA} = \frac{\text{distance\_remaining\_m}}{\bar{v}_{historical}(hour, segment)} + \text{DwellTime}_{traffic\_lights}$$
Mọi thành phần toán học và dữ liệu đầu vào hiện đã hoàn tất 100% trong `.db`.

