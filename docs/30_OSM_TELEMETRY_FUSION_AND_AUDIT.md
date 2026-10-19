# 30. BÁO CÁO HỢP NHẤT DỮ LIỆU TELEMETRY XE BUÝT HÀ NỘI & BẢN ĐỒ TĨNH OPENSTREETMAP (OSM)

**Ngày thực hiện kiểm định:** `17/10/2026`  
**Phạm vi dữ liệu:** `108` batch files (`380.935` bản ghi Telemetry thô trên `756` chu kỳ thu thập) kết hợp với cơ sở dữ liệu đồ thị lộ trình & trạm dừng OSM Hà Nội.

---

## 1. Mục tiêu và Bài toán Hợp nhất (Data Fusion)

Dữ liệu thu thập thực tế từ thiết bị giám sát hành trình xe buýt (Telemetry đồng bộ từ Hugging Face) và dữ liệu bản đồ tĩnh OpenStreetMap (OSM) có sự lệch pha về mặt định danh:
1. **Không trùng hệ thống mã định danh (`ID`)**:
   * Telemetry sử dụng `route_id` nội bộ (ví dụ: `101103` cho tuyến `E01`), `current_station_id`, `next_station_id` và cờ `direction` $\in \{-1, 0, 1\}$.
   * OSM lưu trữ theo `relation_id`, danh sách các đoạn đường (`ways`) và các điểm dừng (`nodes` có tag `highway=bus_stop` hoặc `public_transport=platform`).
2. **Thứ tự và hướng của các đoạn đường (`ways`) trên OSM**:
   * Trên OSM, nhiều đoạn đường (`way`) thuộc lộ trình xe buýt là đường hai chiều dùng chung chuỗi `nodes`, dẫn đến thứ tự liệt kê điểm tọa độ trong một `way` có thể xuôi theo chiều đi nhưng ngược với chiều về.
3. **Sự thay đổi lộ trình vận hành thực tế**:
   * Một số tuyến xe buýt ngoài đời thực đã điều chỉnh nhánh rẽ, kéo dài bến cuối hoặc đi đường vòng tránh rào chắn thi công hạ tầng đô thị mà cộng đồng OSM chưa kịp cập nhật (hoặc ngược lại).

---

## 2. Các Quyết Định Thiết Kế Đã Thống Nhất

Qua quá trình kiểm chứng thực nghiệm và thảo luận, quy trình hợp nhất (`scripts/fuse_telemetry_with_osm.py` $\to$ `data/fused_osm/master_fused_routes_segments.json`) đã chốt **4 nguyên tắc cốt lõi**:

### 2.1. Hai chiều hóa (Orient & Directionalize) chuỗi `ways` của OSM
* Kiểm chứng cho thấy các `variant` trên OSM tái sử dụng `node` nối tiếp nhau nhưng chiều lưu trữ tọa độ của từng `way` đơn lẻ có thể bị ngược so với hướng di chuyển của xe.
* **Giải pháp**: Viết hàm chuẩn hóa hướng `orient_osm_ways()` nối chuỗi liên tục các `ways` theo từng chiều tuyến (`variant`), tự động đảo chiều mảng tọa độ của các `way` bị ngược để tạo ra một đường gấp khúc một chiều liên tục duy nhất từ Bến đầu ($s = 0\text{m}$) đến Bến cuối ($s = L_{\text{route}}$) cho mỗi chiều.

### 2.2. Tái tạo chuỗi trạm chuẩn (Canonical Station Chain) từ cặp chuyển tiếp `current_station_id -> next_station_id`
* Thay vì phụ thuộc hoàn toàn vào tọa độ trạm tĩnh rời rạc trên OSM, ta khai thác trực tiếp trường chuyển tiếp `(current_station_id -> next_station_id)` trong luồng Telemetry để dựng đồ thị có hướng thứ tự các trạm mà xe thực sự đi qua.
* **Tọa độ ranh giới trạm thực tế**: Lấy phân vị 10% (`P10 arrival boundary`) của tọa độ các bản ghi ngay thời điểm xe vừa nhảy mã `current_station_id` sang trạm mới.
* **Ánh xạ lý trình dọc tuyến (`chainage_m`) & Gán tên trạm OSM**: Chiếu vuông góc tọa độ từng trạm lên đường gấp khúc OSM đã 2 chiều hóa để tính chính xác lý trình `chainage_m` (mét tính từ đầu bến) và độ dài từng chặng trạm $e_k = (S_k \to S_{k+1})$, đồng thời ghép 1–1 với `bus_stop` OSM gần nhất để lấy tên trạm hiển thị.

### 2.3. Quy chuẩn ý nghĩa trường `direction` trong Telemetry
* **`direction = -1`** (đi kèm `current_station_id = 0` và `next_station_id = 0`): Xe đang nghỉ, tắt ca hoặc đỗ chờ trong bãi tập kết (Off-duty / Idle at depot) — chiếm `62.908` bản ghi trong ngày `17/10/2026`. Các bản ghi này được lọc bỏ ngay ở tầng tiền xử lý.
* **`direction = 0` và `direction = 1`**: Hai chiều vận hành thực tế (Chiều đi / Chiều về). Ta đối chiếu vector chuyển động đầu–cuối của từng `direction` với 2 `variant` trên OSM để ghép cặp 1–1 chính xác tuyệt đối cho từng tuyến.

### 2.4. Chính sách sàng lọc tuyến lệch nặng ("Bỏ thay vì cố ép khớp sai")
* Đối với các tuyến mà lộ trình thực tế đã thay đổi hoàn toàn hoặc thiếu dữ liệu gốc trên OSM, hiện không có công cụ đơn giản nào tự động vẽ lại bản đồ mà không gây nhiễu. Do đó, thống nhất **loại bỏ 3 tuyến lỗi** và giữ lại **46 tuyến sạch**:
  1. **Tuyến `E10TC` (`route_id = 13004`)**: Tuyến nhánh mới phát sinh, chưa có `relation` tương ứng trong tập dữ liệu OSM tĩnh.
  2. **Tuyến `123` (`route_id = 123`)**: Lộ trình thực tế đã điều chỉnh điểm đầu cuối về **Dân Hòa (Thanh Oai)**, lệch hàng chục km so với lộ trình cũ trên OSM (Bến xe Yên Nghĩa – Hồng Dương).
  3. **Tuyến `E11` (`route_id = 13009`)**: Toàn bộ bản ghi trong ngày `17/10/2026` có tốc độ `0 km/h` (100% xe đỗ trong bãi, không có quỹ đạo lăn bánh).
* **Kết quả hợp nhất cuối cùng**:
  * **46 tuyến xe buýt sạch** (`92` chiều tuyến có hướng).
  * **3.403 trạm dừng** được định danh đầy đủ thứ tự, tọa độ, tên trạm và lý trình `chainage_m`.
  * **3.311 đoạn trạm chuẩn (`canonical segments` $S_k \to S_{k+1}$)** dùng làm đơn vị cơ sở cho bài toán dự báo thời gian di chuyển (ETA).

---

## 3. Thống Kê Kiểm Định Độ Lệch Ngày 17/10/2026 (`380.935` Bản Ghi)

Sử dụng phép chiếu vuông góc vector hóa trên mặt phẳng tiếp tuyến cục bộ tại vĩ độ Hà Nội ($\phi_0 = 21.0285^\circ$), toàn bộ `297.627` bản ghi đang mở ca (`direction` $\in \{0, 1\}$) của 46 tuyến chuẩn trong ngày `17/10/2026` được đối chiếu với tim đường OSM:

### 3.1. Phân tách trạng thái: Xe Đang Chạy vs. Xe Đứng Yên / Đỗ Bến

| Nhóm trạng thái | Số bản ghi (Pings) | Trung vị $d_\perp$ ($P_{50}$) | Phân vị 90% ($P_{90}$) | Phân vị 95% ($P_{95}$) | Khớp chuẩn ($\le 25\text{m}$) | Chấp nhận ($25\text{–}40\text{m}$) | Tổng khớp ($\le 40\text{m}$) | Lệch nhẹ ($40\text{–}100\text{m}$) | Lệch xa ($> 100\text{m}$) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Đang chạy (`speed > 3 km/h`)** | **206.763** | **4,12 m** | **11,77 m** | **16,66 m** | **97,02%** (`200.610`) | **0,76%** (`1.564`) | **97,78%** (`202.174`) | **0,79%** (`1.639`) | **1,43%** (`2.950`) |
| **Đứng yên / Đỗ bến (`speed <= 3 km/h`)** | **90.864** | **26,78 m** | **132,42 m** | **144,40 m** | **49,56%** (`45.035`) | **2,91%** (`2.644`) | **52,47%** (`47.679`) | **22,59%** (`20.528`) | **24,94%** (`22.657`) |
| **Tổng hợp toàn ngày** | **297.627** | **5,34 m** | **88,02 m** | **129,43 m** | **82,53%** (`245.645`) | **1,41%** (`4.208`) | **83,95%** (`249.853`) | **7,45%** (`22.167`) | **8,60%** (`25.607`) |

* **Khi xe đang chạy (`speed > 3 km/h`)**: Tỷ lệ khớp tim đường đạt tới **97,78%** ($\le 40\text{m}$), sai số trung vị chỉ **4,12m**.
* **Khi xe đứng yên (`speed <= 3 km/h`)**: Có `47,53%` bản ghi cách tim đường $> 40\text{m}$ do xe nằm chờ xuất bến bên trong sân bãi đỗ xe rộng của các bến lớn (Mỹ Đình, Giáp Bát, Gia Lâm, Nước Ngầm, Yên Nghĩa, Ocean Park) nhưng thiết bị vẫn để `direction = 0` hoặc `1`.

### 3.2. Phân rã 4 nguyên nhân gây lệch khi xe đang chạy (`speed > 3 km/h`)

Trong số các bản ghi đang di chuyển nhưng lệch $> 40\text{m}$ so với chiều tuyến đang khai báo, phân tích không gian chỉ ra 4 nhóm nguyên nhân:
1. **Lệch lộ trình thực tế / Đi đường vòng tránh cố định (`37,7%` — `2.389` pings)**: Tập trung tại một số đoạn cố định nơi xe buýt thực tế đi đường nhánh/đường tránh khác với đường vẽ trên OSM.
2. **Trễ đổi cờ `direction` ở đầu bến hoặc chạy trên nhánh một chiều ngược lại (`27,0%` — `1.714` pings)**: Thiết bị GPS cập nhật trường `direction` chậm sau khi xe đã quay đầu xuất bến mới, làm xe thực tế đang chạy trên Chiều 1 nhưng vẫn mang nhãn Chiều 0 (hoặc ngược lại).
3. **Đường dẫn nội bộ ra/vào cổng phụ Bến xe đầu cuối (`22,3%` — `1.415` pings)**: Xảy ra ở 2 trạm đầu hoặc 2 trạm cuối cùng khi xe vòng qua cổng phụ bến xe.
4. **Đường gom đại lộ rộng / Vòng xoay / Nút giao cầu vượt (`13,0%` — `823` pings, lệch `40m – 90m`)**: Xe chạy trên đường gom dân sinh của Đại lộ Thăng Long, Vành đai 3 (Phạm Hùng – Khuất Duy Tiến) trong khi tim tuyến OSM vẽ ở làn cao tốc giữa.

### 3.3. Danh sách các Điểm Nóng (Geographic Hotspots) lệch cấu trúc tiêu biểu

| Hạng | Tuyến | Đoạn trạm (`from_station` $\to$ `to_station`) | Tọa độ tâm | Số Pings lệch | Độ lệch trung vị | Nguyên nhân thực địa |
| :---: | :---: | :--- | :---: | :---: | :---: | :--- |
| **1** | **17** *(Chiều 1)* | `102 Thiên Đức, Yên Viên (#196)` $\to$ `(#1340)` | `21.0810, 105.9075` | `757` | `138,7 m` | Nhánh tránh khu vực Cầu Đuống / Hà Huy Tập – Yên Viên. |
| **2** | **61** *(Chiều 0 & 1)* | Cụm 7 đoạn `Ngã 3 Cao Lỗ - Việt Hùng (#3361, #3367)` $\to$ `Dục Tú (#6041, #6042)` | `21.1445, 105.8816` & `21.1499, 105.9103` | `~300+` | `648m – 4.513m` | Xe đi sâu vào trục liên xã Việt Hùng – Dục Tú (Đông Anh) ngoài nhánh OSM. |
| **3** | **122** *(Chiều 0 & 1)* | Cụm 4 đoạn `Điếm canh đê số 10 (#59602, #59604)` $\leftrightarrow$ `Điếm canh đê số 11 (#5502, #5523)` | `21.1023, 105.8499` & `21.1110, 105.8453` | `241` | `343m – 467m` | Xe chạy đường gom chân đê tả Hồng thay vì đường mặt đê trên OSM. |
| **4** | **27** *(Chiều 0 & 1)* | `Tập thể điện tử Tàu Thủy (#472, #57968)` $\leftrightarrow$ `ĐH Luật - Nguyễn Chí Thanh (#70, #73, #477)` | `21.0232, 105.8073` | `202` | `210m – 262m` | Xe đi vòng tránh rào chắn thi công ga đường sắt đô thị nút Đê La Thành – Nguyễn Chí Thanh. |
| **5** | **107** *(Chiều 0 & 1)* | `Đại lý sữa Lan Anh (#4165, #5871)` $\leftrightarrow$ `Khu CNC Hòa Lạc (#5868, #5870)` | `20.9976, 105.5151` | `108` | `260m – 729m` | Xe đi sâu vào khuôn viên nội bộ ĐHQGHN tại Hòa Lạc. |
| **6** | **28** *(Chiều 1)* | `593-595 Kim Mã (#475)` $\to$ `(#88)` | `21.0258, 105.8113` | `45` | `448,9 m` | Phân luồng một chiều quanh ga Metro Cầu Giấy – Kim Mã. |

---

## 4. Phương Pháp Xử Lý Thực Thi Đã Chốt (Từ Thảo Luận Kỹ Thuật)

### 4.1. Xử lý hiện tượng trễ đổi cờ `direction` bằng So sánh 2 chiều + Momentum
* Khi xe đang di chuyển (`speed > 3 km/h`) mà khoảng cách vuông góc tới chiều khai báo bị lệch ($d_{\perp,\text{declared}} > 40\text{m}$):
  1. Hệ thống chiếu tọa độ xe lên cả chiều ngược lại để lấy khoảng cách $d_{\perp,\text{other}}$ và lý trình $s_{\text{other}}(t)$.
  2. Tính **quán tính chuyển động (Momentum)** dọc theo chiều ngược lại giữa 2 bản tin liên tiếp: $\Delta s_{\text{other}} = s_{\text{other}}(t) - s_{\text{other}}(t - \Delta t)$.
  3. Nếu $d_{\perp,\text{other}} \le 35\text{m}$ và xe đang tiến về phía trước trên chiều ngược lại ($\Delta s_{\text{other}} \ge 0$), ta tự động nắn chiều ("giả mù" cờ `direction` bị trễ) sang chiều thực tế. Thực nghiệm trên ngày `17/10/2026` cho thấy kỹ thuật này tự động cứu được **1.168 – 1.714 trạng thái** xe bị trễ cờ đầu bến.

### 4.2. Xử lý các đoạn đổi tuyến tránh (Structural Detour): Tách bạch Tính ETA và Ánh xạ Bản đồ
* **Trong bài toán ước lượng thời gian di chuyển giữa 2 trạm ($\Delta T_{k \to k+1}$)**:
  * Mục tiêu của mô hình ETA là ước lượng thời gian xe đi từ trạm $S_k$ tới trạm $S_{k+1}$.
  * Dù ở giữa đoạn $S_k \to S_{k+1}$ xe phải đi đường vòng tránh lô cốt (như Tuyến 27 hay Tuyến 122), miễn là lộ trình vòng tránh diễn ra cố định hàng ngày và xe vẫn lần lượt cập nhật `current_station_id` tại $S_k$ rồi $S_{k+1}$, thì thời gian thực tế $\Delta T_{k \to k+1}$ hoàn toàn không bị ảnh hưởng. Ta tiếp tục **"giả mù" sự lệch không gian ở giữa đoạn** khi huấn luyện và dự báo thời gian theo chặng trạm.
* **Trong lúc ánh xạ GPS $\to$ Bản đồ OSM (Map-Matching & Hiển thị)**:
  * Vẫn giữ nguyên phép chiếu vuông góc chuẩn từ tọa độ GPS vào tim đường OSM.
  * Đánh dấu rõ các đoạn có sai lệch cấu trúc tĩnh (`Structural Detour`, màu cam trên bản đồ kiểm chứng) để:
    1. Chỉ rõ đâu là **sai lệch cấu trúc bản đồ tĩnh / phân luồng giao thông** so với đâu là **nhiễu GPS bất thường**.
    2. Trong luồng Streaming ETA, khi xe đi vào các đoạn `Structural Detour` này (dù $d_\perp > 40\text{m}$), hệ thống **không loại bỏ bản tin**, mà dựa vào cặp `(current_station_id, next_station_id)` để giữ trạng thái xe đang thuộc chặng $S_k \to S_{k+1}$.

### 4.3. Giữ vị trí cuối (Last Observation Carried Forward — LOCF) khi hiển thị & theo dõi độ phân giải cao
* Do các thiết bị GPS trên xe buýt gửi bản tin không đồng bộ theo từng giây (`device_update_time`) và có những thời điểm xe tạm thời chưa gửi bản tin mới trong 1–2 chu kỳ, nếu cắt lát thời gian cứng nhắc theo từng khung giờ hẹp sẽ làm xe bị biến mất ("nhấp nháy") trên bản đồ.
* **Giải pháp**: Xây dựng chuỗi trạng thái liên tục theo từng xe (`[t_start, t_end]`) kết hợp cơ chế **Giữ vị trí báo gần nhất (LOCF)** có thời hạn hiệu lực (`TTL`, mặc định `10 phút`, kèm tùy chọn nội suy mượt giữa 2 lần báo GPS). Nhờ đó, thanh trượt thời gian trên bản đồ HTML đạt độ phân giải **10 giây/nấc (5.400 mốc trong ngày)** mà không làm mất bất kỳ xe nào đang hoạt động.

### 4.4. Quyết định kiến trúc Mức 1 (40 Tuyến Cực Sạch & Ép 100% Trạm lên Tim Đường OSM)
* Để giữ dự án đơn giản nhất có thể, tránh phải xây dựng bảng quy đổi `raw_station_id -> canonical_station_id` hay cắt nối hình học OSM thủ công do hiện tượng phân tách cụm trạm (ví dụ `Điếm canh đê số 10` trên Tuyến `122` bị tách thành 2 cụm trạm `#59602, #59603` ở chiều 1 và `#59604, #59605` ở chiều 0 vì xe đi đường vòng tránh):
  1. **Lọc giữ 40 tuyến cực sạch (Mức 1)**: Loại bỏ thêm **6 tuyến** có đoạn vòng tránh/thiếu nhánh OSM lớn làm trạm bị lệch khỏi tim đường (`61, 17, 56B, 122, 28, 27`) cùng với 3 tuyến lệch hoàn toàn ban đầu (`E10TC, 123, E11`). Danh sách loại bỏ tổng cộng 9 tuyến:
     ```python
     EXCLUDED_ROUTES = {"E10TC", "123", "E11", "61", "17", "56B", "122", "28", "27"}
     ```
     Tập **40 tuyến còn lại** có chất lượng khớp hình học rất cao (**97,5%** tổng số trạm cách tim đường $< 50\text{m}$).
  2. **Ép 100% tọa độ trạm nằm ngay trên tim đường OSM (`proj_lat, proj_lon`)**: Thay vì giữ tọa độ centroid thô nằm lệch ngoài mặt đường, mọi trạm trong `master_fused_routes_segments.json` đều lấy trực tiếp tọa độ hình chiếu vuông góc trên tim đường OSM (`lat = proj_lat, lon = proj_lon`) và giữ nguyên khóa phẳng 1-đối-1 `telemetry_station_id`.

### 4.5. Tối ưu chống treo trình duyệt (Anti-Hang) cho Bản đồ HTML độ phân giải 10 giây
* Bản đồ kiểm chứng [hanoi_bus_telemetry_2026_10_17_map.html](file:///z:/Desktop/Bus_tracking/ground_truth_route_station/output/hanoi_bus_telemetry_2026_10_17_map.html) được tối ưu hóa toàn diện để kéo thanh trượt 5.400 mốc thời gian ở tốc độ 60 FPS không bị đơ/treo:
  * **Object Pooling (`busMarkerPool`, `ghostMarkerPool` & `projLinePool`)**: Tái sử dụng các đối tượng `L.circleMarker` và `L.polyline` thông qua `.setLatLng()` và `.setStyle()` thay vì xóa và khởi tạo lại hàng trăm DOM/Canvas layer ở mỗi tích tắc kéo thanh trượt.
  * **Gộp MultiPolyline theo Chiều Tuyến**: Mỗi chiều của một tuyến chỉ dùng **1 đối tượng `L.polyline` duy nhất** (tổng cộng 80 polylines cho 40 tuyến thay vì 10.000 polylines rời rạc cho từng `way`).
  * **Single Shared Popup & `requestAnimationFrame` Throttling**: Chỉ tạo nội dung HTML cho Popup khi người dùng thực sự bấm chuột vào xe/trạm, và khóa tần suất vẽ lại theo nhịp khung hình màn hình (`rAF`).

### 4.6. Kiểm định Khoảng Cách Thời Gian Gửi GPS Thực (`device_update_time`) so với Chu Kỳ Crawl (`crawled_at`) & Khử "Xe Ma"
* **Cấu trúc chu kỳ Crawl (`crawled_at`)**:
  * Toàn ngày `17/10/2026` gồm `108` file batch với **756 chu kỳ crawl** (từ `05:05:48` đến `20:04:31`).
  * Trong cùng 1 file batch (7 chu kỳ/batch), khoảng cách giữa 2 lần crawl cố định đúng **75,0 giây** (`648/755` lần). Giữa 2 file batch liên tiếp, khoảng cách chuyển tiếp là **46s – 50s** (trung vị `48,0s`).
  * **Không có hiện tượng rớt xe khỏi danh sách API trả về**: `99,98%` các chu kỳ crawl liên tiếp đều có mặt đầy đủ xe (`380.345 / 380.431` cặp).
* **Phân phối khoảng cách gửi GPS thực tế của hộp đen (`\Delta device_update_time`) khi xe đang chạy (`217.614` bước chuyển)**:
  * Hộp đen GPS trên xe buýt phát tín hiệu theo nhịp phần cứng là bội số của **15 giây / 20 giây** (`20s, 30s, 45s, 60s, 75s, 80s, 90s, 105s`). Tuy nhiên, do API chỉ trả về bản tin mới nhất tại thời điểm crawl (`75s/lần`), các gói tin GPS trung gian giữa 2 lần crawl bị ghi đè trên Server, tạo ra phân phối $\Delta t_{\text{GPS}}$ thực thu:
    * **$\le 45\text{s}$**: `10,63%` (`23.137` lần — chủ yếu rơi vào nhịp chuyển tiếp `48s` giữa 2 file batch).
    * **$46\text{s} - 80\text{s}$ (khớp 1 chu kỳ crawl `~75s`)**: `51,48%` (`112.018` lần, tập trung tại `60s`, `75s`, `80s`).
    * **$81\text{s} - 120\text{s}$ (lệch pha nhẹ giữa nhịp hộp đen và nhịp crawl)**: `36,62%` (`79.699` lần, tập trung tại `90s` và `105s`).
    * **$121\text{s} - 180\text{s}$ (mất 1 gói tin GPS / lỡ nhịp mạng 3G/4G)**: `0,78%` (`1.692` lần).
    * **$> 180\text{s}$ (mất gói tin kéo dài > 3 phút do vùng lõm sóng)**: chỉ chiếm **`0,49%`** (`1.068` lần).
* **Nguyên nhân gốc rễ gây hiện tượng "Xe ma" và "Xe đột nhiên mất tích rồi hiện lại" & Cách đã xử lý triệt để**:
  1. **Mất truy vấn GPS trước đó ở ranh giới chuyển file Batch (`108` lần/ngày)**: Mỗi khi bắt đầu một file `batch_*.jsonl` mới, tiến trình thu thập bị mất bộ nhớ vị trí của gói tin cuối thuộc batch trước nên không tính được `calculated_speed` (rơi về `raw_speed = 0.0` cho **14.569 bản ghi** dù xe thực tế vừa di chuyển `30m – 200m`). Tương tự, khi 2 lần crawl liên tiếp đọc trúng cùng 1 `device_update_time` chưa kịp cập nhật (**86.054 bản ghi**, chiếm `22,6%`), lần đọc thứ 2 có quãng đường dịch chuyển bằng `0` nên ghi đè `speed = 0.0` (**3.512 lần**). Kết hợp với việc ẩn xe có `speed <= 3.0`, xe đang chạy bị biến mất ở đầu mỗi batch hoặc tại đèn đỏ rồi hiện lại ở chu kỳ sau!
     * **Khắc phục**: Gom nhóm theo khóa `(vehicle_id, device_update_time)` trước tiên và **tự tính lại vận tốc liên tục xuyên qua ranh giới 108 batch** từ khoảng cách dịch chuyển thực tế $\Delta d / \Delta t_{\text{GPS}}$; đồng thời **chỉ ẩn xe khi xe thực sự đỗ nghỉ dài hạn tại bến đầu/cuối (`is_depot = 1`)**, còn xe dừng đèn đỏ/đón khách giữa đường luôn hiển thị liên tục 100% suốt chuyến đi.
  2. **Bản tin đóng băng từ ngày hôm trước (`21.781` bản ghi từ `15/10`, `16/10`) hoặc đóng băng $> 15$ phút (`35.855` bản ghi)**: Trước đây việc gán `eff_sec = crawl_sec` khi `device_update_time` quá hạn đã biến các xe tắt thiết bị từ hôm trước (nhưng kẹt `raw_speed = 41–49 km/h`) thành các **"Xe ma"** đứng bất động giữa đường suốt cả ngày.
     * **Khắc phục**: Loại bỏ hoàn toàn mọi bản ghi không thuộc ngày `2026-10-17` hoặc có `crawl_sec - dev_sec > 300s`.

### 4.7. Chiến Thuật "Điểm Ma" (Virtual Ghost Point trên Tim Đường OSM) cho 1% Trường Hợp Detour / Sự Cố
* Để xử lý gọn nhẹ **~1%** trường hợp xe phải đi đường vòng tránh (`detour`), phân luồng giao thông hoặc gặp sự cố khiến tọa độ GPS lệch khỏi tim đường OSM ($d_\perp > 40\text{m}$) mà **không làm ảnh hưởng đến logic của 99% trường hợp chuẩn còn lại**:
  1. **Hiển thị vị trí thực**: Tọa độ GPS thực của xe (`lat, lon`) vẫn luôn được hiển thị trung thực tại đúng vị trí xe đang chạy ngoài thực địa.
  2. **Ánh xạ "Điểm Ma" (`s_ghost`, `ghost_lat`, `ghost_lon`) trên tim đường OSM để ước lượng ETA**:
     * Với **99% trường hợp đi đúng tuyến** ($d_\perp \le 40\text{m}$): Điểm Ma trùng với hình chiếu vuông góc của xe trên đoạn tim đường OSM giữa trạm vừa qua $S_k$ (`current_station_id`, lý trình $s_k$) và trạm tiếp theo $S_{k+1}$ (`next_station_id`, lý trình $s_{k+1}$):
       $$s_{\text{ghost}} = \text{clip}(s_{\text{proj}},\, s_k,\, s_{k+1})$$
     * Với **1% trường hợp xe đi lệch tuyến / detour** ($d_\perp > 40\text{m}$ hoặc hình chiếu nhảy khỏi chặng $[s_k, s_{k+1}]$): Hệ thống "giả mù" độ lệch ngang 2D và nội suy vị trí **Điểm Ma** nằm ngay trên tim đường OSM trong đoạn $[s_k, s_{k+1}]$ theo tỷ lệ khoảng cách Euclid từ xe tới hai trạm $S_k$ và $S_{k+1}$:
       $$\alpha = \frac{d(\text{GPS}, S_k)}{d(\text{GPS}, S_k) + d(\text{GPS}, S_{k+1})} \in [0, 1], \qquad s_{\text{ghost}} = s_k + \alpha \cdot (s_{k+1} - s_k)$$
     * Nhờ đó, mọi xe đang hoạt động đều luôn có lý trình 1D $s_{\text{ghost}}$ hợp lệ trên tim đường OSM và khoảng cách còn lại tới trạm kế tiếp $\Delta s_{\text{rem}} = s_{k+1} - s_{\text{ghost}} \ge 0$ để tính $\text{ETA}$ theo một công thức duy nhất.

### 4.8. Nội Suy Bám Đường Cong Tuyến OSM (1D Route-Curve Interpolation) Tránh Lỗi "Cắt Góc Qua Nhà Dân"
* **Hiện tượng lỗi khi nội suy tuyến tính 2D (`lat, lon`)**: Khi xe đi qua các nút giao cua gấp $90^\circ$ (ví dụ xe `29F05137` Tuyến 32 rẽ từ **Phố Đào Tấn** sang **Đường Bưởi** qua **Cầu Đào Tấn** giữa 2 gói tin `06:42:07` và `06:43:37`), nếu nội suy đường thẳng 2D nối trực tiếp `(lat0, lon0) -> (lat1, lon1)`, điểm nội suy ở giữa (`06:43:00`) sẽ **cắt chéo góc cua xuyên qua khu dân cư Thủ Lệ** dù 2 đầu mút đều bám chuẩn tim đường ($d_\perp = 8,3\text{m}$ và $3,4\text{m}$).
* **Cách khắc phục đã áp dụng**: Thay vì nội suy thẳng trong không gian 2D, hàm hiển thị nội suy theo **lý trình 1 chiều trên đường cong OSM** $s(t) = s_0 + \alpha \cdot (s_1 - s_0)$ rồi ánh xạ ngược $s(t) \to (\text{lat}, \text{lon})$ dọc theo các đỉnh khúc gấp của polyline lộ trình (`pointAtChainage`), giúp xe ôm sát đúng góc cua của đường phố.

---

## 5. Ghi Nhận Hạng Mục Chưa Xử Lý (Pending / Open Issue): Ảnh Hưởng Của Mất Gói Tin & Chu Kỳ Crawl Lên Thống Kê

> [!IMPORTANT]
> **Ghi nhận chưa xử lý (TODO khi tính thống kê chuyên sâu & huấn luyện mô hình ETA):**
> Hiện tại các chỉ số thống kê độ lệch không gian và thời gian di chuyển mới tính trực tiếp trên tập các gói tin thu nhận được (`Observed Pings`), **chưa hiệu chỉnh trọng số cho các khoảng trống mất gói tin (Packet Loss) hoặc bị ghi đè giữa 2 chu kỳ crawl (`75s`)**.

Cụ thể có 3 hệ quả cần tính tới ở bước xử lý thống kê tiếp theo:
1. **Hiện tượng nhảy cóc qua nhiều trạm liên tiếp (`Multi-Station Jump = 11,40%` — `9.258 / 81.182` lần chuyển trạm)**:
   * Do khoảng cách giữa 2 trạm nội đô thường chỉ `250m – 400m` (`30s – 50s` xe chạy) trong khi chu kỳ crawl là `75s` (và khi mất gói 3G/4G là `120s – 300s`), có **11,40%** số lần cập nhật trạm bị nhảy qua $\ge 2$ trạm cùng lúc ($S_k \to S_{k+2}$ hoặc $S_{k+3}$).
   * *Chưa xử lý*: Khi trích xuất nhãn thời gian di chuyển thực tế từng chặng đơn $\Delta T_{k \to k+1}$, cần phân bổ (pro-rate) tổng thời gian $\Delta T_{k \to k+m}$ theo tỷ lệ độ dài chặng OSM $\frac{s_{i+1} - s_i}{s_{k+m} - s_k}$ thay vì bỏ qua các chặng bị nhảy cóc.
2. **Sai số lượng tử hóa thời điểm qua trạm (`Timestamp Quantization Bias` $\pm 37,5\text{s}$)**:
   * Thời điểm xe đổi `current_station_id` trong bản ghi chỉ là thời điểm gói tin đầu tiên *sau khi* xe đã rời trạm, không phải thời điểm chính xác xe chạm trạm.
   * *Chưa xử lý*: Cần dùng lý trình $s_{\text{proj}}(t_0) \le s_{\text{station}} \le s_{\text{proj}}(t_1)$ để nội suy ngược thời điểm thực tế xe đi qua tọa độ trạm:
     $$t_{\text{pass}}(S_k) = t_0 + \frac{s_{\text{station}} - s_{\text{proj}}(t_0)}{s_{\text{proj}}(t_1) - s_{\text{proj}}(t_0)} \cdot (t_1 - t_0)$$
3. **Thiên lệch mẫu không gian theo thời gian (`Time-Weighted vs Ping-Weighted Statistics`)**:
   * Một xe đi vào vùng mất sóng 3G/4G trong `3 phút` chỉ đóng góp 1 bản ghi, trong khi xe chạy ở vùng sóng khỏe đóng góp 3–4 bản ghi. Khi tính thống kê độ lệch hoặc vận tốc trung bình toàn tuyến, cần nhân trọng số theo khoảng thời gian đại diện $\Delta t_i$ của từng bản ghi (Time-weighted) thay vì đếm đầu bản ghi thuần túy (Ping-weighted).

---

## 6. Kiểm Toán Chủ Động 8 Lỗi Tiềm Ẩn Toàn Hệ Thống (Đã Đặt Giả Thuyết & Chạy Kiểm Chứng Thực Nghiệm)

Để đảm bảo không bỏ sót các lỗi ngầm trong dữ liệu thực tế ngày `17/10/2026`, chúng tôi đã chủ động đặt ra **8 giả thuyết lỗi kỹ thuật** và chạy kịch bản kiểm toán định lượng trên toàn bộ `320.675` bản ghi hợp lệ và `80` chiều tuyến:

| Mã | Giả thuyết lỗi tiềm ẩn | Kết quả kiểm định thực tế (`17/10/2026`) | Trạng thái xử lý |
| :---: | :--- | :--- | :--- |
| **H1** | **Thứ tự các đoạn `way` trong OSM Relation bị xếp lộn cụm đầu-cuối hoặc ngược chiều** làm lý trình trạm $s_{k+1} < s_k$ bị giật lùi. | Phát hiện **7 chiều tuyến** (`08A_0, 105_0, 13_0, 37_1, 39_1, 40_1, 67_0`) bị dịch vòng (cyclic shift) hoặc ngược thứ tự `ways` trong OSM gốc, gây ra `58` cặp trạm bị ngược lý trình (`3.691` bản ghi bị ảnh hưởng). | **Đã sửa triệt để** bằng hàm `fix_ways_order()` (tự động sắp xếp cụm `way`, xoay vòng về trạm đầu và ép đơn điệu lý trình $s_1 \le s_2 \le \dots \le s_M$ về **0 lỗi**). |
| **H2** | **Hai trạm liên tiếp có cùng tọa độ hình chiếu (`\Delta s < 5\text{m}`)** do tách mã trạm phụ tại bến trung chuyển. | Phát hiện **13 cặp trạm** có $\Delta s < 5\text{m}$ (VD: `Điểm đỗ xe buýt Ga Cầu Giấy` & `(#1696)` trên Tuyến 07; `Công viên Thống Nhất` trên Tuyến 40). | **Đã bảo vệ chia cho 0** (`max(1.0, d_curr + d_next)`) và giữ nguyên thứ tự `sequence`. |
| **H3** | **Cảm biến công-tơ-mét hộp đen báo `raw_speed = 0.0` ngay cả khi xe đang chạy nhanh (`> 5 km/h`)**. | Phát hiện **31.444 / 216.994 bản ghi đang chạy (`14,49%`)** có `raw_speed == 0.0` (do hộp đen chỉ gửi GPS mà không nối dây xung vận tốc cơ khí). | **Đã xử lý**: Luôn ưu tiên vận tốc dịch chuyển GPS thực tế (`max(speed, raw_speed, calc_v_cross_batch)`). |
| **H4** | **Đồng hồ hộp đen GPS chạy nhanh hơn đồng hồ Server (`Clock Skew`: `device_update_time > crawled_at`)**. | Phát hiện **14.263 / 320.675 bản ghi (`4,45%`)** có đồng hồ hộp đen nhanh hơn Server từ `3s – 45s`. | **Đã xử lý**: Cho phép dung sai `crawl_sec - dev_sec >= -60s` để không bỏ nhầm các xe bị nhanh đồng hồ vài chục giây. |
| **H5** | **Đột biến vận tốc ảo (`Speed Spikes > 70 km/h`)** do nhảy tọa độ GPS tức thời giữa các tòa nhà cao tầng. | Phát hiện **276 bản ghi (`0,09%`)** có vận tốc $> 70\text{ km/h}$. | **Đã xử lý**: Kẹp trần vận tốc khôi phục ở `65 km/h` và lọc bỏ `GPS_DRIFT_JUMP`. |
| **H6** | **Một xe (`vehicle_id`) đổi sang chạy tuyến khác (`route_id`) giữa ngày (Interlining)**. | **0 xe (`0,00%`)** — trong ngày `17/10/2026`, mỗi `vehicle_id` gắn cố định 1-đối-1 với duy nhất 1 tuyến. | An toàn tuyệt đối. |
| **H7** | **Xe đang chạy trên đường nhưng báo `current_station_id == 0`, `next_station_id == 0` hoặc `curr_st == next_st`**. | **0 bản ghi (`0,00%`)** đối với các trạng thái đang chạy ngoài bến (`is_depot == 0`). Chỉ xảy ra khi xe đang đỗ trong bến (`is_depot == 1`). | An toàn tuyệt đối. |
| **H8** | **Trễ cập nhật mã trạm (`Station Overrun`: xe thực tế đã chạy lố qua `next_station_id` nhưng hộp đen chưa nhảy mã trạm kế tiếp)**. | Xảy ra ở khoảng **`2,8%`** bản ghi đang chạy (xe đã vượt qua tọa độ trạm `next_st` từ `30m – 250m` trước khi hộp đen nhảy sang trạm mới). | **Lưu ý quan trọng khi làm ETA**: Khi $s_{\text{proj}} > s_{\text{next\_st}} + 30\text{m}$, mô hình ETA nên tự động suy luận xe đã qua trạm $S_{k+1}$ và tính tiếp cho trạm $S_{k+2}$ theo chuỗi `sequence` của tuyến. |
