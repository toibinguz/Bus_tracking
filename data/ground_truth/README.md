# BỘ DỮ LIỆU CHUẨN ĐỊA LÝ & DANH BẠ TRẠM DỪNG (MASTER GROUND TRUTH)
> **Cơ quan thẩm quyền**: Trung tâm Quản lý Giao thông công cộng TP Hà Nội (TRAMOC) / Sở Giao thông Vận tải Hà Nội  
> **Cổng thông tin gốc**: [TimBus.vn](http://timbus.vn)  
> **Tuân thủ quy tắc**: [AGENTS.md](../../AGENTS.md) (Điều 6: Derived Speed & Điều 7: TimBus Master Ground Truth)

---

## 1. TỔNG QUAN HỆ THỐNG GROUND TRUTH

Dữ liệu mạng lưới trạm xe buýt và tim đường (Centerline Polyline) được trích xuất trực tiếp từ cổng nghiệp vụ **TimBus (TRAMOC)**, đại diện cho hiện trạng vận hành chính thức, chuẩn xác nhất và mới nhất của mạng lưới vận tải hành khách công cộng Thủ đô Hà Nội.

### Thống Kê Định Lượng:
| Chỉ Tiêu | Số Lượng Đã Thu Thập | Mô Tả Kỹ Thuật |
| :--- | :--- | :--- |
| **Tổng số tuyến hoạt động** | **48 tuyến** | Toàn bộ các tuyến trục đô thị, tuyến nhánh và xe buýt điện (VinBus E-series, BRT01) |
| **Danh mục trạm dừng WGS84** | **3.646 trạm** | Tọa độ địa lý chuẩn WGS84, tên biển vẫy thực tế, thứ tự ghé trạm theo cả 2 chiều |
| **Điểm tim đường (Shape Polyline)** | **17.631 điểm** | Hình học tim đường chính thức, đã tính sẵn khoảng cách tích lũy $s$ dọc tuyến (mét) |
| **Bản ghi đối soát ánh xạ (Crosswalk)** | **3.646 liên kết** | Bảng ánh xạ giữa BusMap Telemetry ID và TimBus Official Station ID |

---

## 2. QUY CHUẨN CƠ SỞ DỮ LIỆU & BẢNG ÁNH XẠ (SCHEMA SPECIFICATION)

Dữ liệu được tổ chức thống nhất trong tệp cơ sở dữ liệu phân tích `data/telemetry_audit_2026_10_17_18.db`:

### 2.1. Bảng Tuyến Chuẩn (`timbus_route_master`)
```sql
CREATE TABLE timbus_route_master (
    fleet_id TEXT PRIMARY KEY,       -- Mã quản lý hạm đội của TRAMOC (VD: "2", "32")
    route_code TEXT NOT NULL,        -- Mã số tuyến hiển thị (VD: "02", "32", "BRT01", "E01")
    route_name TEXT NOT NULL,        -- Tên hành trình đầy đủ (VD: "Bác Cổ - Bến xe Yên Nghĩa")
    bus_count INTEGER DEFAULT 0      -- Số phương tiện đăng ký vận hành
);
```

### 2.2. Bảng Danh Bạ Trạm Dừng Chính Thức (`timbus_station_master`)
```sql
CREATE TABLE timbus_station_master (
    station_id INTEGER NOT NULL,     -- ObjectID chính thức của TRAMOC
    route_code TEXT NOT NULL,        -- Mã tuyến
    direction TEXT NOT NULL,         -- Chiều đi: 'go' (Lượt đi) hoặc 're' (Lượt về)
    station_order INTEGER NOT NULL,  -- Thứ tự dừng từ 1 đến N
    station_name TEXT NOT NULL,      -- Tên biển trạm dừng thực tế
    street TEXT,                     -- Tên đường / tuyến phố cắm trạm
    lat REAL NOT NULL,               -- Vĩ độ WGS84
    lon REAL NOT NULL,               -- Kinh độ WGS84
    PRIMARY KEY (station_id, route_code, direction)
);
```

### 2.3. Bảng Tim Đường Hình Học Dọc Tuyến (`timbus_shape_master`)
```sql
CREATE TABLE timbus_shape_master (
    route_code TEXT NOT NULL,        -- Mã tuyến
    direction TEXT NOT NULL,         -- Chiều: 'go' hoặc 're'
    point_order INTEGER NOT NULL,    -- Thứ tự đỉnh hình học trên polyline (0, 1, 2, ...)
    lat REAL NOT NULL,               -- Vĩ độ đỉnh
    lon REAL NOT NULL,               -- Kinh độ đỉnh
    cum_distance_m REAL NOT NULL,    -- Khoảng cách tích lũy s dọc tuyến từ điểm xuất phát (mét)
    PRIMARY KEY (route_code, direction, point_order)
);
```

### 2.4. Bảng Chiếu Tuyến & Đối Soát Trạm (`dim_station_crosswalk`)
```sql
CREATE TABLE dim_station_crosswalk (
    station_id INTEGER NOT NULL,
    route_code TEXT NOT NULL,
    direction TEXT NOT NULL,
    station_order INTEGER NOT NULL,
    station_name TEXT NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    s_station_m REAL NOT NULL,       -- Tọa độ 1D dọc tim đường (Along-track distance)
    PRIMARY KEY (station_id, route_code, direction)
);
```

---

## 3. NGUYÊN TẮC KINEMATIC & NHẬN DIỆN DỪNG ĐỖ (DWELL TIME)

Căn cứ theo **Điều 6 trong AGENTS.md**, hệ thống tuyệt đối không dùng trường `speed` GPS thô:
1. **Vận tốc dẫn xuất không gian - thời gian**:
   $$\bar{v} = \frac{\Delta s}{\Delta t} \times 3.6 \quad (\text{km/h})$$
   Trong đó $\Delta s$ là độ dịch chuyển dọc tim đường Frenet và $\Delta t$ là chênh lệch thời gian giữa 2 pings liên tiếp.
2. **Nhận diện dừng đón trả khách (Dwell Event)**:
   Xe được xác nhận là đang dừng tại trạm khi thỏa mãn đồng thời:
   $$\Delta s < 15\text{ m} \quad \text{và} \quad \Delta t \ge 20\text{ s}$$

---

## 4. HƯỚNG DẪN THỰC THI & TÁI TẠO DỮ LIỆU

### Thu thập dữ liệu trạm và tim đường toàn bộ 48 tuyến:
```bash
python module_1_data_ingestion_and_preprocessing/step_1_2_timbus_master_ground_truth/ingest_all_active_routes.py
```

### Thực hiện chiếu 1D Frenet cho telemetry lên tim đường TimBus:
```bash
python module_1_data_ingestion_and_preprocessing/step_1_4_frenet_spatial_projection/multi_route_projector.py
```

### Truy vấn trạm kế tiếp theo thời gian thực:
```sql
SELECT * FROM v_bus_to_next_station WHERE route_code = '02';
```

