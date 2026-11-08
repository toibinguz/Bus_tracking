# THẨM ĐỊNH KIẾN TRÚC & ĐÁNH GIÁ CÁC VẤN ĐỀ NGOÀI MODULE 3.4 & 3.5

**Tác giả**: @architect  
**Mục tiêu**: Thẩm định thực tế mã nguồn, dữ liệu vận hành trên 7.33 triệu bản ghi và kiểm chứng các nghi vấn ngoài Module 3.4 và 3.5 nhằm phân định rạch ròi giữa **LỖI LOGIC/VẬN HÀNH (True Bug)** và **NỢ KỸ THUẬT/ĐỊNH DANH (Harmless Naming / Cosmetic Debt)**.

---

## TỔNG HỢP KẾT LUẬN THẨM ĐỊNH (EXECUTIVE SUMMARY)

| STT | Vấn đề / Đối tượng khảo sát | Phân loại | Tác động thực tế | Hướng xử lý |
| :--- | :--- | :--- | :--- | :--- |
| **1** | `telemetry_sanitizer.py`: `if dist < BUS_STOPPED_SPEED_KMPH: calc_speed = 0.0` | **HARMLESS / NAMING DEBT** (Không phải True Bug) | Không làm sai lệch logic vật lý lọc nhiễu đứng yên ($< 5.0\text{ m}$). Dữ liệu xe bò ($2-4\text{ km/h}$) vẫn được bảo lưu trọn vẹn, không bị triệt tiêu sai. | Chuẩn hóa định danh hằng số thành `GPS_STATIONARY_DRIFT_THRESHOLD_M = 5.0` trong sổ nợ kỹ thuật. |
| **2** | `db_manager.py`: SQL View `v_bus_to_next_station` (Correlated Subquery) | **HARMLESS / ANALYTICAL UTILITY** (Không phải True Bug) | Có covering index `idx_cstat_route_dir_s`, truy vấn 100 dòng mất $17\text{ ms}$, quét toàn bộ $5.5\text{M}$ dòng mất $7.2\text{ s}$ ($> 760,000\text{ rows/s}$). Không nằm trên luồng phục vụ trực tuyến. | Giữ nguyên cho mục đích audit offline. Không cần can thiệp code. |
| **3** | Hoán vị tọa độ `module_1` (`vehicle_hn/get` vs `route_bus_gps`) | **FALSE ALARM / NON-ISSUE** (Không có lỗi) | Toàn bộ $7.33\text{M}$ pings trong DB đều chuẩn WGS84 ($\text{lat}\approx 20.95, \text{lon}\approx 105.75$). `route_bus_gps` trong `module_1` chỉ đọc `Id, RouteId, Plate`, hoàn toàn không đọc tọa độ. | Giữ nguyên, không có sai lệch thực tế. |
| **Phát hiện bổ sung (P0)** | `config/system_config.py:335`: Thiếu `from typing import Any` | **TRUE BUG (CRITICAL RUNTIME ERROR)** | Gây lỗi ngay lập tức `NameError: name 'Any' is not defined` khi bất kỳ tiến trình nào chạy `import config`. | Giao @leaf_coder sửa gấp theo Spec bên dưới. |

---

## 1. THẨM ĐỊNH CHI TIẾT VẤN ĐỀ 1: LOGIC LỌC ĐIỂM DỪNG VÀ ĐẠO HÀM VẬN TỐC

### 1.1. Hiện trạng mã nguồn
Tại file [`module_1_data_ingestion_and_preprocessing/step_1_3_telemetry_kinematic_sanitizer/telemetry_sanitizer.py`](file:///z:/Desktop/Bus_tracking/module_1_data_ingestion_and_preprocessing/step_1_3_telemetry_kinematic_sanitizer/telemetry_sanitizer.py#L73-L86):
```python
if STALE_DELTA_T_MIN_SEC <= delta_t <= STALE_DELTA_T_MAX_SEC:
    dist = haversine_distance(prev_lat, prev_lon, std_lat, std_lon)
    if dist < BUS_STOPPED_SPEED_KMPH:
        calc_speed = 0.0
        smoothed_speed = 0.0
    else:
        v_derived = (dist / delta_t) * 3.6
        if v_derived > GPS_DRIFT_MAX_SPEED_KMPH:  # Vượt quá giới hạn vật lý nội đô
            is_drift_jump = True
            calc_speed = prev_smoothed
            smoothed_speed = prev_smoothed
        else:
            calc_speed = round(v_derived, 1)
            smoothed_speed = round(EMA_ALPHA * calc_speed + (1.0 - EMA_ALPHA) * prev_smoothed, 1)
```

Hằng số tại [`config/system_config.py:179`](file:///z:/Desktop/Bus_tracking/config/system_config.py#L179):
```python
BUS_STOPPED_SPEED_KMPH = 5.0  # Vận tốc xe bò/dừng đón trả khách
```

### 1.2. Phân tích thứ nguyên và Vật lý chuyển động (Dimensional & Kinematic Analysis)
- Hàm `haversine_distance(...)` trả về khoảng cách $dist$ tính bằng **mét ($m$)**.
- Hằng số `BUS_STOPPED_SPEED_KMPH` có giá trị số là `5.0`.
- Biểu thức so sánh trong mã: `dist < 5.0` (ngưỡng 5.0 mét).

#### Xét kịch bản A: Nếu code thực sự so sánh khoảng cách ($dist < 5.0\text{ m}$)
- Thiết bị GPS dân dụng trên xe buýt có sai số bán kính CEP (Circular Error Probable) ngẫu nhiên từ $2.5 - 5.0\text{ m}$.
- Khi xe dừng hẳn tại điểm đón trả khách hoặc chờ đèn đỏ trong chu kỳ cào $\Delta t = 15 - 30\text{ s}$, tọa độ GPS vẫn nhảy nhẹ ngẫu nhiên quanh vị trí đứng yên $1 - 4\text{ m}$.
- Nếu không có vùng chết không gian (Spatial Deadband) $< 5\text{ m}$, thuật toán vi phân sẽ tính ra một vận tốc ảo:
  $$v_{ao} = \frac{3\text{ m}}{15\text{ s}} \times 3.6 = 0.72\text{ km/h}$$
  Khiến xe dừng đỗ không bao giờ đạt trạng thái dừng tĩnh $v = 0.0\text{ km/h}$.
- Do đó, việc gán `calc_speed = 0.0` khi $dist < 5.0\text{ m}$ là **hoàn toàn chính xác về mặt vật lý lọc nhiễu tĩnh GPS**.

#### Xét kịch bản B: Nếu sửa thành so sánh vận tốc ($v_{derived} < 5.0\text{ km/h}$)
- Trong điều kiện giao thông tắc nghẽn đặc trưng tại Hà Nội (Chùa Bộc, Tây Sơn, Giải Phóng), xe buýt thường bò chậm nhích từng bước với vận tốc thực $2 - 4\text{ km/h}$.
- Với chu kỳ cào $\Delta t = 30\text{ s}$, một chiếc xe bò với vận tốc $3.0\text{ km/h}$ sẽ dịch chuyển được:
  $$d = \frac{3.0}{3.6} \times 30 = 25.0\text{ mét}$$
- Nếu áp dụng nhầm ngưỡng vận tốc `v_derived < 5.0 km/h` để ép `calc_speed = 0.0`:
  1. Toàn bộ xe đang bò nhích $2 - 4\text{ km/h}$ ($25\text{ m} / 30\text{ s}$) sẽ bị triệt tiêu thành $0.0\text{ km/h}$ (xe đỗ chết).
  2. Tại [`module_1/step_1_1_busmap_crawler_and_relay/hotspot_evaluator.py`](file:///z:/Desktop/Bus_tracking/module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/hotspot_evaluator.py#L52-L59), chỉ số `avg_speed` sẽ bị kéo về 0 một cách giả tạo, làm hỏng việc phân biệt giữa "ùn tắc giao thông" và "xe dừng đỗ tại bến/bãi tập kết".
  3. Tại Feature Store của Module 3, các mẫu vận tốc lịch sử sẽ bị phân cực nhị phân (chỉ có 0 hoặc $\ge 5$), phá vỡ hàm phân phối liên tục của mô hình LightGBM/CatBoost.

### 1.3. Kết luận Vấn đề 1
- **Bản chất**: Đây là **Nợ định danh / Nợ ngữ nghĩa (Semantic Naming Debt)** do tác giả cũ tái sử dụng hằng số có giá trị `5.0` mà không đặt tên riêng cho ngưỡng khoảng cách GPS Deadband.
- **Tác động vận hành**: **Hoàn toàn vô hại (Harmless)**. Xe đi chậm thật sự ($> 5\text{ m}$) trong chu kỳ cào vẫn được tính $v_{derived}$ chính xác; chỉ có dao động vi mô dưới $5\text{ m}$ bị coi là nhiễu và đưa về 0.
- **Kiến nghị**: Không cần sửa vội vã trong hotfix. Sẽ chuyển định danh thành `GPS_STATIONARY_DRIFT_THRESHOLD_M = 5.0` trong sổ nợ kỹ thuật.

---

## 2. THẨM ĐỊNH CHI TIẾT VẤN ĐỀ 2: SQL VIEW `v_bus_to_next_station`

### 2.1. Hiện trạng View và Chỉ mục CSDL
Định nghĩa tại [`module_2_big_data_storage_and_lakehouse/step_2_1_sqlite_operational_store/db_manager.py:45-76`](file:///z:/Desktop/Bus_tracking/module_2_big_data_storage_and_lakehouse/step_2_1_sqlite_operational_store/db_manager.py#L45-L76):
```sql
CREATE VIEW IF NOT EXISTS v_bus_to_next_station AS
SELECT 
    t.ping_id,
    t.route_code,
    t.route_id,
    t.vehicle_id,
    t.plate,
    t.device_update_time,
    t.device_epoch,
    t.direction,
    t.lat AS bus_lat,
    t.lon AS bus_lon,
    t.s_bus_m,
    t.cross_track_m,
    t.derived_speed_kmh,
    s.station_order AS next_station_order,
    s.station_id AS next_station_id,
    s.station_name AS next_station_name,
    s.cum_distance_m AS next_station_s,
    ROUND(s.cum_distance_m - t.s_bus_m, 2) AS distance_remaining_m
FROM route_projected_telemetry t
JOIN canonical_station_master s
  ON t.route_code = s.route_code
 AND t.direction = s.direction 
 AND s.cum_distance_m = (
     SELECT MIN(s2.cum_distance_m)
     FROM canonical_station_master s2
     WHERE s2.route_code = t.route_code
       AND s2.direction = t.direction 
       AND s2.cum_distance_m >= t.s_bus_m
 );
```

### 2.2. Kiểm chứng thực tế trên Database Production `data/hanoi_bus_system.db`
Đã tiến hành benchmark trực tiếp trên CSDL chứa **5,565,232 dòng** `route_projected_telemetry` và **13,301 trạm dừng**:

1. **Query Plan (EXPLAIN QUERY PLAN)**:
   ```text
   SCAN t
   SEARCH s USING INDEX idx_cstat_route_dir_s (route_code=? AND direction=? AND cum_distance_m=?)
   CORRELATED SCALAR SUBQUERY 3
   SEARCH s2 USING COVERING INDEX idx_cstat_route_dir_s (route_code=? AND direction=? AND cum_distance_m>?)
   ```
   *Nhận xét*: SQLite sử dụng triệt để Covering Index 3 trường `idx_cstat_route_dir_s(route_code, direction, cum_distance_m)` trên bảng trạm dừng. Phép tìm kiếm $s_2 \ge s_{bus}$ là tìm kiếm trên cây B-Tree cực nhanh ($O(\log N)$).

2. **Benchmark tốc độ**:
   - `SELECT * FROM v_bus_to_next_station LIMIT 10`: **$0.00\text{ ms}$**.
   - `SELECT * FROM v_bus_to_next_station WHERE route_code = '01' LIMIT 100`: **$17.35\text{ ms}$**.
   - `SELECT COUNT(1) FROM v_bus_to_next_station` (quét toàn bộ $5.5\text{M}$ bản ghi): **$7.208\text{ s}$** (đạt thông lượng $> 760,000$ dòng/giây).

3. **Kiểm tra tính nhất quán logic**:
   - Số lượng trạm trùng tọa độ/khoảng cách trên cùng 1 tuyến và hướng: **0** (tất cả giá trị `cum_distance_m` là đơn điệu tăng nghiêm ngặt). Không xảy ra hiện tượng nhân đôi số dòng (cartesian product).
   - Số dòng trả về: $5,483,348$ dòng. Có $81,884$ dòng ($1.47\%$) bị loại bỏ tự nhiên do xe đã vượt qua trạm cuối cùng của chuyến ($s_{bus} > s_{cuoi}$), việc INNER JOIN loại bỏ pings không còn trạm kế tiếp là hợp lý về mặt nghiệp vụ "Bus to Next Station".

4. **Vị trí gọi trong hệ thống**:
   - View này **KHÔNG BAO GIỜ** được gọi trong luồng online serving (Module 3.4 và 3.5). Module 3 tìm trạm kế tiếp hoàn toàn in-memory bằng thuật toán `bisect` trên mảng numpy đã nạp sẵn vào RAM khi khởi động.
   - View chỉ phục vụ kiểm tra kiến trúc trong script offline `scripts/verify_canonical_architecture.py`.

### 2.3. Kết luận Vấn đề 2
- **Bản chất**: **HARMLESS / ANALYTICAL UTILITY**.
- Không gây nghẽn hiệu năng, không gây lock database, không có lỗi logic. Giữ nguyên.

---

## 3. THẨM ĐỊNH CHI TIẾT VẤN ĐỀ 3: HOÁN VỊ TỌA ĐỘ TẠI `MODULE_1`

### 3.1. Đặc tính 2 API của BusMap
- **API `vehicle_hn/get?id={v_id}`**: Backend BusMap bị hoán vị trường dữ liệu:
  $$\text{raw["Lat"]} = 105.xxxx \text{ (Kinh độ / Lon)}, \quad \text{raw["Lng"]} = 20.xxxx \text{ (Vĩ độ / Lat)}$$
- **API `route_bus_gps?regionCode=hn&routeId=...`**: Backend BusMap trả về chuẩn quốc tế:
  $$\text{raw["Lat"]} = 20.xxxx \text{ (Vĩ độ / Lat)}, \quad \text{raw["Lng"]} = 105.xxxx \text{ (Kinh độ / Lon)}$$

### 3.2. Rà soát toàn bộ `module_1`
1. Điểm gọi `route_bus_gps`:
   - Chỉ xuất hiện duy nhất tại [`catalog_refresher.py:187-204`](file:///z:/Desktop/Bus_tracking/module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/catalog_refresher.py#L187-L204).
   - Tại đây, code chỉ trích xuất: `f_vid = b.get("Id")`, `f_route = b.get("RouteId")`, `f_plate = b.get("VehicleNumber")` nhằm mục đích phát hiện xe mới bổ sung vào catalog.
   - **Hoàn toàn KHÔNG trích xuất hay xử lý tọa độ `Lat/Lng` từ API `route_bus_gps`**.
2. Điểm gọi `vehicle_hn/get`:
   - Được gọi qua socket client tại [`socket_client.py:43`](file:///z:/Desktop/Bus_tracking/module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/socket_client.py#L43).
   - Được chuẩn hóa tại [`telemetry_sanitizer.py:36-37`](file:///z:/Desktop/Bus_tracking/module_1_data_ingestion_and_preprocessing/step_1_3_telemetry_kinematic_sanitizer/telemetry_sanitizer.py#L36-L37):
     ```python
     std_lon = float(raw.get("Lat", 0.0))  # 105.x -> Lon
     std_lat = float(raw.get("Lng", 0.0))  # 20.x -> Lat
     ```
   - Đoạn hoán vị này đảo ngược đúng dữ liệu trả về của BusMap, đưa về chuẩn WGS84.
3. Kiểm tra dữ liệu thực tế trong SQLite:
   - `canonical_station_master`: $\text{lat} = 20.949979, \text{lon} = 105.747619$ (Bến xe Yên Nghĩa, Hà Nội).
   - `vehicle_unique_pings`: $\text{lat} = 20.950193, \text{lon} = 105.747849$.
   - `route_projected_telemetry`: $\text{lat} = 20.950193, \text{lon} = 105.747849$.

### 3.3. Kết luận Vấn đề 3
- **Bản chất**: **FALSE ALARM / NON-ISSUE**.
- Không có bất kỳ vị trí nào trong `module_1` bị gọi sai khiến tọa độ bị đảo ngược ngoài thực tế.

---

## 4. PHÁT HIỆN LỖI THỰC TẾ (CRITICAL TRUE BUG - P0)

Trong quá trình import kiểm thử các module, phát hiện lỗi Runtime nghiêm trọng làm gián đoạn toàn bộ hệ thống:

### 4.1. Vị trí lỗi
- File: [`config/system_config.py:335`](file:///z:/Desktop/Bus_tracking/config/system_config.py#L335)
- Dòng code:
  ```python
  def normalize_direction(direction: Any) -> str:
  ```
- Lỗi xuất hiện:
  ```text
  NameError: name 'Any' is not defined. Did you mean: 'any'?
  ```
- Nguyên nhân: Thiếu lệnh `from typing import Any` ở phần đầu file [`config/system_config.py`](file:///z:/Desktop/Bus_tracking/config/system_config.py). Mọi script thực hiện `import config` hoặc `from config import ...` đều bị sập ngay lập tức.

### 4.2. Đặc tả sửa đổi chuẩn (Spec for @leaf_coder)
- **Tập tin can thiệp**: [`config/system_config.py`](file:///z:/Desktop/Bus_tracking/config/system_config.py)
- **Hành động**: Bổ sung `from typing import Any` vào khối import ở đầu file:
  ```python
  import os
  import sys
  import hashlib
  import random
  from typing import Any
  from datetime import datetime, timezone, timedelta, time as dtime
  ```
- **Tiêu chuẩn nghiệm thu (Acceptance Criteria)**:
  Lệnh `python -c "import config; print('Config OK')"` phải thực thi thành công và in ra `Config OK` với exit code 0.
