# BỘ DỮ LIỆU CHUẨN ĐỊA LÝ & DANH BẠ TRẠM DỪNG (CANONICAL MASTER GROUND TRUTH)
> **Snapshot note (2026-11-10):** Numerical counts are dataset snapshots. The ingestion script is the schema authority.
> **Nguồn dữ liệu**: BusMap Canonical Ground Truth (`hanoi_bus_data`)  
> **Tuân thủ quy tắc**: [AGENTS.md](../../AGENTS.md) (Điều 4: Master Ground Truth Duy Nhất)

---

## 1. TỔNG QUAN HỆ THỐNG GROUND TRUTH

Dữ liệu mạng lưới trạm xe buýt và hình học tim đường (Centerline Polyline) được chuẩn hóa từ danh bạ gốc BusMap Canonical, đồng bộ 1:1 với mã trạm (`current_station_id`, `next_station_id`) và mã tuyến của luồng Telemetry GPS thời gian thực.

### Thống Kê Định Lượng Mạng Lưới:
| Chỉ Tiêu | Số Lượng Đã Thu Thập | Mô Tả Kỹ Thuật |
| :--- | :--- | :--- |
| **Tổng số tuyến hoạt động** | **176 tuyến** | Toàn bộ mạng lưới xe buýt Thủ đô (bao gồm 48 tuyến hành lang trọng điểm và các tuyến kết nối) |
| **Danh mục trạm dừng WGS84** | **13.301 trạm** | Tọa độ địa lý chuẩn WGS84, tên trạm, thứ tự ghé trạm đồng bộ 1:1 với telemetry GPS |
| **Điểm tim đường (Shape Polyline)** | **118.563 điểm** | Hình học tim đường chính xác cao, tính sẵn cự ly tích lũy $s$ dọc tuyến (mét) |

---

## 2. QUY CHUẨN CƠ SỞ DỮ LIỆU CHÍNH THỨC (CANONICAL SCHEMA)

Dữ liệu được tổ chức thống nhất trong cơ sở dữ liệu `data/hanoi_bus_system.db`:

### 2.1. Bảng Tuyến Chuẩn (`canonical_route_master`)
```sql
CREATE TABLE canonical_route_master (
    route_id INTEGER PRIMARY KEY,
    route_code TEXT NOT NULL,
    route_name TEXT NOT NULL,
    company_name TEXT,
    operation_time TEXT,
    headway TEXT,
    total_trips INTEGER,
    point_count_go INTEGER,
    point_count_re INTEGER,
    station_count_go INTEGER,
    station_count_re INTEGER
);
```

### 2.2. Bảng Danh Bạ Trạm Dừng Chính Thức (`canonical_station_master`)
```sql
CREATE TABLE canonical_station_master (
    station_id INTEGER NOT NULL,
    route_id INTEGER NOT NULL,
    route_code TEXT NOT NULL,
    direction TEXT NOT NULL,
    station_order INTEGER NOT NULL,
    station_name TEXT NOT NULL,
    address TEXT,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    cum_distance_m REAL NOT NULL,
    snap_dist_m REAL NOT NULL,
    PRIMARY KEY (route_id, direction, station_order)
);
```

### 2.3. Bảng Tim Đường Hình Học Dọc Tuyến (`canonical_shape_master`)
```sql
CREATE TABLE canonical_shape_master (
    route_id INTEGER NOT NULL,
    direction TEXT NOT NULL,
    point_order INTEGER NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    cum_distance_m REAL NOT NULL,
    PRIMARY KEY (route_id, direction, point_order)
);
```
