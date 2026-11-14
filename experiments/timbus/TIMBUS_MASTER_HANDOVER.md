# Tài liệu Bàn giao Tổng thể: Thẩm định Giao thức & Tích hợp TimBus API (`VehicleState`)

> **Phạm vi & Cô lập**: Toàn bộ mã nguồn, dữ liệu thực nghiệm, SQLite DB TimBus và tài liệu bàn giao được cô lập 100% trong `experiments/timbus/` (không chỉnh sửa `module_*`, `config/`, `data/`).  
> **Đối tượng mục tiêu**: Nhóm Kỹ thuật & Phát triển Sản phẩm (WebApp Demo / ETA Pipeline).  
> **Tài liệu kèm theo**:  
> - Quy trình & Kiến trúc WebApp Demo (5 bước): [`TIMBUS_WEBAPP_DEMO_PROCEDURE.md`](file:///z:/Desktop/Bus_tracking/experiments/timbus/TIMBUS_WEBAPP_DEMO_PROCEDURE.md)  
> - Client Python hậu chỉnh sửa: [`timbus_tracker.py`](file:///z:/Desktop/Bus_tracking/experiments/timbus/timbus_tracker.py)  
> - Script tái lập toàn bộ thí nghiệm: [`reproduce_all_experiments.py`](file:///z:/Desktop/Bus_tracking/experiments/timbus/reproduce_all_experiments.py)

---

## 1. Tóm tắt Điều hành & Đánh giá Trung thực (Không Che giấu Giới hạn)

### 1.1. TimBus làm được gì tốt?
1. **Độ tươi GPS vượt trội**: Chu kỳ cập nhật phần cứng hộp đen đạt danh định **5.0 giây** (đo thực tế toàn đội xe **$\mu = 4.96\text{s}$**), nhanh hơn nhiều so với nhịp cập nhật ~20–30s của BusMap Public API.
2. **Độ chính xác tọa độ đồng nhất với BusMap**: Khi đối chiếu cặp bản ghi cùng mốc thời gian (`|Δτ| <= 5s`, `N = 250`), trung vị sai lệch Haversine bằng **0.0 m** (trung bình **15.7 m**, `67.2% <= 15.0 m`). Sai lệch lớn ở ảnh chụp ngẫu nhiên (`310.1 m` trung vị chưa căn thời gian) là do BusMap cập nhật chậm hơn, **không phải** lỗi tọa độ của TimBus.
3. **Khả năng bám đuổi 4 xe trung tâm ổn định**: Chế độ đích danh biển số (`vehicle_param=<plate>`) + `route_param=""` + neo trạm bến cuối chạy liên tục **20 chu kỳ × 4.9s × 4 xe** đạt **80/80 (100%)**, `0` lỗi, độ trễ `P50 = 176.8 ms`, `max = 530.6 ms`, tổng thời gian 1 chu kỳ max `1,912.9 ms`.

### 1.2. Các "Số liệu Xấu" & Giới hạn Nghiêm trọng Bắt buộc Phải Biết
1. **Chỉ có 1 endpoint duy nhất & Bị giới hạn cứng (Shadowing 92.0%) khi quét theo trạm**:
   - Server trả tối đa **1–2 xe gần nhất** mỗi tuyến/chiều khi `vehicle_param=""`. Trên 30 vòng quét Tuyến 32, **46/50 ca (`92.0%`)** xe chạy nối đuôi bị che khuất hoàn toàn; tỷ lệ bao phủ đoàn xe trung bình chỉ đạt **85.1%** (`13.8` vs `16.0` xe).
   - Xe nặng như `29F05223` mất mặt tới **28/30** lượt (`23` lượt do shadowing); `29F05208` mất **17/30** lượt; `29F05272` mất **15/30** lượt.
2. **DB tĩnh APK 02/2020 (`timbus_hanoi.sqlite`) & `routes.json` đã lỗi thời nặng**:
   - Thiếu **`65 / 176` (`36.9%`)** tuyến của BusMap 2026; **`96 / 111` (`86.5%`)** tuyến trùng bị lệch số lượng trạm; **`324`** trạm trùng `station_id` nhưng lệch tọa độ `> 50 m` (lệch tới **`48,426.0 m` / `48,480.2 m`** theo bán kính Trái Đất — tái sử dụng ID trạm ở vị trí hoàn toàn khác).
   - **`62 / 111` (`55.9%`)** tuyến trùng bị lệch trạm bến cuối `> 100 m`; **`342`** trạm TimBus lệch tim đường shape BusMap từ `100–600 m` (tuyến `104` lệch tới **`597.5 m`**).
3. **Quét trực tiếp trạm để lấy "xe gần nhất" sai rất nặng (`25.5%` sai xe)**:
   - Trong `1,860` lượt quét Tuyến 32 không có cổng kiểm chứng: **`474` lượt (`25.5%`) trả nhầm xe** (`253` xe chạy sau, `6` xe đã qua trạm, `215` xe ngược chiều/khác trạm) + **`90` lượt trả rỗng** (`30/30` tại trạm `395 - 54 Lý Thường Kiệt`).
4. **Không phủ toàn bộ mạng lưới tuyến Hà Nội**:
   - Trong 111 tuyến trùng mã với BusMap, tổng cộng **89/111 (`80.2%`)** cho dữ liệu live (sau khi áp dụng dự phòng trạm giữa + `route_param=""`), nhưng còn **`22/111` (`19.8%`) trả rỗng hoàn toàn** khi kiểm tra (`08A, 08ACT, 08B, 08BCT, 09A, 09B, 19, 21A, 21B, 37, 43, 46, 57, 58, 59, 60A, 60B, 61, 64, 65, 72, 74`).
   - Ngoài ra vẫn có hiện tượng rớt gói/rỗng tức thời khi xe mới rời bến, sát bến cuối (xe thứ 4 trong lượt live check `3/4`), hoặc lỗi socket thoáng qua (`WinError 10065`).
5. **Trường dữ liệu phản hồi bị đặt sai tên trong mã nguồn cũ**:
   - Trường `next_station_id` trong DTO thực chất là **cự ly (mét)** tới trạm hỏi; trường `distance_m` thực chất là **ETA (giây)** tới trạm hỏi; trường `direction` bị cố định `'Về'` ở **504/504** bản ghi lịch sử.

---

## 2. Đặc tả Kỹ thuật Đầy đủ API TimBus (`VehicleState`)

### 2.1. Truyền dẫn & Đóng gói Mật mã (XOR + Checksum Modulo-256)
- **Endpoint duy nhất**: `GET http://www.timbus.vn:9149/SearchBuyt/VehicleState?ReqParams=<URL-encoded Base64>`
- **Headers**: `User-Agent: Dalvik/2.1.0 ...`, `Connection: Keep-Alive`, `Accept-Encoding: gzip`.
- **Cấu trúc Request đóng gói**:
  1. `plain = ClientID (4B LE, mặc định 0x001B02F5) + RequestBody`
  2. Sinh ngẫu nhiên `Key1` (`32B`) và `Key2` (`64B`) trong khoảng ASCII `[48, 127]`
  3. `Cipher[i] = plain[i] XOR Key1[i % len(Key1)]`
  4. `Packet = Cipher + Key1 + len(Key1)[1B] + Key2 + len(Key2)[1B]`
  5. Nối cuối `Checksum = sum(Packet) & 0xFF`, mã hóa Base64 gửi qua `ReqParams`.
- **Giải mã Response**: Tối thiểu `67 bytes`, kiểm tra `raw[-1] == (sum(raw[:-1]) & 0xFF)`, đọc `len_key2 = raw[-2]`, `len_key1 = raw[-2 - len_key2 - 1]`, tách `Key1` và XOR giải mã phần `Cipher`.

### 2.2. Request Body & Hành vi Thực tế của Server

| Thứ tự | Tham số | Kiểu nhị phân | Hành vi Thực tế Đã Kiểm chứng Live |
| :---: | :--- | :---: | :--- |
| 1 | `station_id` | `int32` (4B LE) | **Bắt buộc > 0 và nằm phía trước xe trên tuyến TimBus**. Truyền `sid = 0` với biển số hợp lệ (`29F05192`) -> `0` bản ghi. Truyền trạm không gắn tuyến (`395` trên Tuyến 32) -> **`[]` cho mọi xe**. Xe đã đi qua `station_id` (như `157 - ĐH Bách Khoa` ở km 14.4 thay vì bến cuối `1676`) -> `[]`. |
| 2 | `route_param` | `uint16 len` + UTF-8 | **Khuyến nghị truyền `""` khi đã truyền `vehicle_param`**: Bỏ qua lệch mã đổi hậu tố (`04->04CT, 11->11CT, 23->23CT, 30->30CT, 40->40CT, 86CT->86`) và bắt được tuyến mới ngoài DB 2020 (tuyến `122`, xe `29B21262`). Chỉ điền danh sách tuyến khi quét trạm `vehicle_param=""`. |
| 3 | `vehicle_param` | `uint16 len` + UTF-8 | `""` kích hoạt quét theo trạm (**bị shadowing 92%**); truyền biển số chuẩn hóa không dấu (`"29F05192"`) kích hoạt **tra cứu đích danh, không bị shadowing**. |
| 4 | `direction` | `uint8` (1B) | `0` = Đi, `1` = Về. Ở các trạm giữa tuyến 1 chiều, server phụ thuộc nhiều vào hướng vật lý của `station_id` hơn tham số `direction`; ở bến cuối 2 chiều giúp lọc đúng chiều rõ hơn. |

### 2.3. Response Body: Đính chính Ý nghĩa 10 Trường Dữ liệu & Bằng chứng

Header phản hồi bắt đầu bằng `Count (1 byte)`, theo sau bởi `Count` bản ghi:

| # | Kiểu nhị phân | Tên trường `BusRecord` (tương thích ngược) | Tên Property mới / **Ý nghĩa Thực tế Đã Kiểm chứng** | Lưu ý / Sai khác Phát hiện |
| :---: | :---: | :--- | :--- | :--- |
| 1 | `1B len` + UTF-8 | `plate` | Biển kiểm soát (VD `"29F05192"`) | Chuẩn hóa hoa, bỏ `-`, `.`, khoảng trắng trước khi so khớp |
| 2 | `1B len` + UTF-8 | `route` | Mã tuyến thực tế trên server (VD `"32"`, `"04CT"`) | Có thể khác hậu tố `CT`/`TC` so với DB 2020 |
| 3 | `int32` (4B LE) | `next_station_id` | **`distance_to_queried_station_m`**: Cự ly (mét) từ xe tới **`station_id` vừa truyền vào request** | **Không phải ID trạm!** |
| 4 | `int32` (4B LE) | `distance_m` | **`eta_to_queried_station_sec`**: Thời gian dự kiến (giây) tới `station_id` vừa hỏi | Ước lượng của server TimBus, không đưa vào Model 6 |
| 5 | `int16 len` + UTF-8 | `next_station_name` | **`destination_name`**: Tên bến cuối của chiều chạy (`"Bến xe Giáp Bát"`, `"Nhổn"`) | Không phải tên trạm dừng kế tiếp |
| 6 | `uint8` (1B) | `speed_kmh` | Vận tốc tức thời hộp đen (`0–255 km/h`) | Tin cậy được cùng cặp `(lat, lon)` |
| 7 | `float32` (4B LE) | `latitude` | Vĩ độ WGS-84 | Có thể trùng `9.2%–20%` ở 2 chu kỳ 5s liên tiếp do trôi pha |
| 8 | `float32` (4B LE) | `longitude` | Kinh độ WGS-84 | Luôn kiểm tra `(lat, lon) != (0, 0)` |
| 9 | `uint8` (1B) | `status` | Chiều thực tế trên gói tin (`0` = Đi, `1` = Về trên Tuyến 32) | Trong `504` bản ghi Tuyến 32: `275` (`0`), `229` (`1`); có xe đổi sớm gần bến cuối |
| 10 | `uint8` (1B) | `direction` | Byte hướng cuối gói tin | **Cố định `'Về'` (`1`) ở 504/504 (100%) bản ghi!** Cấm dùng phân biệt chiều |

**Bằng chứng kiểm chứng Trường 3 & 4 trên xe `29F05192`** (`verify_protocol_fields_realtime.json`):
- `station_id = 0` -> **`0` bản ghi**
- `station_id = 242` (*Số 9 Hồ Tùng Mậu*, khoảng cách thực trên shape tới xe = `492.7 m`) -> Trường 3 = **`492`**, Trường 4 = **`126 s`**, Trường 5 = `"Bến xe Giáp Bát"`
- `station_id = 531` (*TH Lý Thường Kiệt*, cách `7,298.5 m`) -> Trường 3 = **`7,350`**, Trường 4 = **`1,890 s`**, Trường 5 = `"Bến xe Giáp Bát"`
- `station_id = 1676` (*(A) BX Giáp Bát*, cách `13,760.4 m`) -> Trường 3 = **`13,749`**, Trường 4 = **`3,535 s`**, Trường 5 = `"Bến xe Giáp Bát"`

**Hiện tượng kỹ thuật cần lưu ý trong gói Response**:
- **Trùng bản ghi (`Count = 2`) khi hỏi 1 biển số**: Đo được tại bến cuối `1778` (trên `29F05182`, `29F05106`, `29F05130`, `29F05242`) -> `timbus_tracker.py` lấy bản ghi hợp lệ đầu tiên để khử trùng lặp.
- **Lẫn xe ngược chiều tại mỏ neo bến cuối**: Khi gọi `re` vẫn có `56/284` lượt trả về xe `status=0` (và `1/220` ngược lại). Thử nghiệm live gần nhất với `route_code=""` tại `[1676, 157]` trả `3/4` xe, trong đó `29F05272` trả về `status=1, dest="Nhổn"` -> bắt buộc dùng **BusMap geometry ở Bước 5** để xác định chiều thực tế theo quỹ đạo tuyến thay vì tin cứng tham số gửi đi.

---

## 3. Tổng hợp Đầy đủ Số liệu Thực nghiệm (Tốt & Xấu)

### 3.1. Đối chứng Tuyến 32 trong 10 Phút (30 Sweeps, `run_route32_parity_experiment.py`)
| Chỉ số đo | Giá trị | Ghi chú / Giải thích trung thực |
| :--- | :---: | :--- |
| Đoàn xe độc nhất phát hiện | **20 / 20 xe** | Cả hai nguồn đều thấy đủ đoàn xe trong toàn bộ 10 phút |
| Số xe đang chạy trung bình/vòng | BusMap **16.0** vs TimBus **13.8** | Tỷ lệ bao phủ trung bình: **85.1%** |
| Hiện tượng Shadowing (quét trạm `vehicle_param=""`) | **46 / 50 ca (92.0%)** | Server chỉ trả `1–2` xe đầu đoạn trạm (đo trực tiếp `2` xe tại `1676`, `2` xe tại `1778`) |
| Sai lệch GPS **chưa** căn thời gian (30 sweeps) | Trung vị **310.1 m** | Do BusMap trễ nhịp cập nhật 20–30s |
| Sai lệch GPS **đã** căn `|Δτ| <= 5s` (`N = 250`) | **Trung vị 0.0 m** (Mean **15.7 m**, `67.2% <= 15m`) | Khẳng định dùng chung dữ liệu phần cứng GPS WGS-84 |

### 3.2. Sai khác DB Tĩnh (`hanoi_bus_system.db` 2026 vs `timbus_hanoi.sqlite` 02/2020 & `routes.json`)
> Lưu ý kỹ thuật trích xuất APK (`timbus_stations_and_routes_report.md`): Bảng `Orders` trong `timbus_hanoi.sqlite` là **chỉ số đỉnh polyline**, không phải thứ tự trạm dừng `0..N-1`; file [`routes.json`](file:///z:/Desktop/Reverse%20Enginering/data/timbus/routes.json) có cùng 129 tuyến và danh sách trạm cuối như `timbus_hanoi.sqlite`.

- **Cấp tuyến (`176` BM vs `129` TB)**: Trùng mã chuẩn hóa **`111`**, chỉ BusMap **`65` (`36.9%`)**, chỉ TimBus **`18`**, trùng cả `route_id == fleet_id` **`102 / 111`**. Chỉ **`15 / 111` (`13.5%`)** khớp chính xác số lượng trạm 2 chiều; **`96 / 111` (`86.5%`)** lệch số trạm (`station_route_diff_summary.json` từng đếm trùng `4` tuyến đối xứng `bm_go == bm_re == tb_dir0 == tb_dir1` vào mục `exact_match_swapped`; thực tế số tuyến đảo chiều thuần go/re bằng **`0`**).
- **Cấp trạm toàn mạng**: BusMap `5,221` ID vs TimBus `3,789` ID, trùng ID **`3,356`**:
  - Cùng `station_id` nhưng lệch tọa độ: Median `0.2 m`, P90 `47.9 m`, **`324` trạm lệch `> 50 m`**, cực đại **`48,426.0 m`** (R=6371km) / **`48,480.2 m`** (R=6378.137km) do tái sử dụng ID trạm.
  - Khoảng cách tới trạm TimBus gần nhất: Median `0.4 m`, P90 `1,952.1 m`, có **`1,643` trạm BusMap không có trạm TimBus nào trong `100 m`**.
- **Phân rã `8,535` lượt trạm trên 111 tuyến trùng (`nearest_bus_station_experiment.json`)**:
  - **Case 1** (Khớp `<= 30 m`): **`5,956` (`69.8%`)**
  - **Case 2** (Lệch `> 30 m` nhưng vẫn trên shape BM `ct <= 30 m`): **`1,182` (`13.8%`)**, trong đó **`780`** trùng `station_id` nhưng bị dời vị trí (gây trượt pha: nhận nhầm xe chạy sau).
  - **Case 3** (Lệch shape BM `ct > 30 m` hoặc mất trạm trong `500 m`): `283 + 1,114` = **`1,397` (`16.4%`)**.
- **Đoạn lệch shape nghiêm trọng (`audit_assumptions_high_shape_diff.json`)**: Có **`342` trạm** TimBus lệch khỏi shape BusMap `100–600 m` (lớn nhất: tuyến `104` `597.5 m`, tuyến `90` `589.1 m`, tuyến `19` `585.5 m`). Trên Tuyến 32:
  - Chiều `re` trạm `395` (*54 Lý Thường Kiệt*, DB 2020 chỉ gắn tuyến `49`) vs `636` (*Chùa Quán Sứ*): lệch `129.9 m` / cross-track `116.8 m`; quét `395` trên live trả **`0/30` lượt**.
  - Các trạm mới BusMap không có trong DB 2020 (`6220`, `6189`, `6166`) lại trả **`30/30` lượt** khi quét live -> server TimBus hiện tại chia sẻ không gian `station_id` mới hơn file `.tsc` 2020, nhưng giữ lại sai khác lộ trình cục bộ (`395`, `09A` trạm `2089`, `43` trạm `425`).
  - Sai lầm nhầm bến cuối `157` (*ĐH Bách Khoa*) vs `1676` (*(A) BX Giáp Bát*) trên Tuyến 32 `go`: dùng `157` làm `3/10` xe cuối tuyến bị trả `0` (gồm 2 xe ở `16,417.6 m` và `16,688.0 m`), chỉ lấy được `7/10` (`verify_protocol_fields_realtime.json`), trong khi chiều `re` dùng `1778` (*Nhổn*) lấy đủ `10/10`.

### 3.3. Benchmark Tìm "Xe Gần Trạm S Nhất" (1,860 Lượt / 1,667 Lượt Có Xe Tiến Tới)

| Phương pháp | Khớp / Chấp nhận trên `1,667` ca | Số ca sai xe | Fallback / Rỗng | Nhận xét thực nghiệm |
| :--- | :---: | :---: | :---: | :--- |
| **M1**: Quét thẳng 1 trạm `S` (tin tuyệt đối server) | **1,296 (77.7%)** | **311** (`474 / 1,860 = 25.5%` gồm ngược chiều/qua trạm/xe sau) | `60` (`90 / 1,860`) | **Không chấp nhận được**: trả nhầm xe sau ở Case 2 (`6220`), rỗng `30/30` ở Case 3 (`395`). |
| **M2**: 1 trạm `S` + Verification Gate | **1,269 (76.1%)** | **0 (0.0%)** | `398` (`591 / 1,860`) | An toàn tuyệt đối (`0` sai), nhưng bỏ lỡ **23.9%** khi `B1` bị lag hoặc shadowing. |
| **M3**: Đích danh Top-3 Xe Trung tâm + Gate hậu kiểm | **1,615 (96.9%)** | **0 (0.0%)** | **52 (3.1%)** | Cứu `137` ca `B1` đã qua `S` + `167` ca `B1` thiếu. **52 FB** gồm `21` cả Top-3 đã qua trạm, `25` thiếu TimBus, `4` đổi chiều sớm, `2` lệch shape Quán Sứ. |

**Lý do bỏ ngưỡng cứng `cross_track <= 35 m` khi nhận gói (`audit_assumptions_high_shape_diff.json`)**:
- Phát hiện **`3` lượt TimBus** (`104.7–118.8 m`) và `2` lượt BusMap (`119.8–120.6 m`) đi phố Quán Sứ hợp lệ dù shape BusMap vẽ Lý Thường Kiệt, cùng **`20` lượt TimBus** nút Giải Phóng – Giáp Bát có `ct = 46.0–68.9 m`. Do đó **chỉ lọc biển số + tọa độ khác `(0, 0)` ở tầng thu thập**, để tầng hình học BusMap xử lý sau.

### 3.4. Thẩm định Độ phủ Toàn Hệ thống (111 Tuyến Trùng) & Tính Ổn định 4.9s
1. **Bến cuối tĩnh 111 tuyến (`stability_and_terminals_result.json`)**: `57/111` trùng `station_id` cả 2 chiều, `49/111 (44.1%)` lệch `<= 100 m`, `0` đảo chiều go/re, **`62/111 (55.9%)` lệch `> 100 m`**.
2. **Kiểm tra live 3 bước trên 111 tuyến**:
   - **Vòng 1** (`audit_111_routes_terminals_live.json`, theo bến cuối & mã tuyến): **`80 / 111`** có xe (`63 tb_go + 15 tb_re + 2 bm_go`), `31` rỗng.
   - **Vòng 2** (`recheck_31_empty_routes.json`, dò 3–4 trạm giữa tuyến): cứu thêm **`3`** tuyến (`05, 104, 96`) có bến cuối 2020 bị lỗi thời -> `28` rỗng.
   - **Vòng 3** (`recheck_28_routes_empty_route_param.json`, giữ trạm TimBus chuẩn nhưng truyền `route_param=""`): cứu thêm **`6`** tuyến bị đổi hậu tố mã (`04->04CT, 11->11CT, 23->23CT, 30->30CT, 40->40CT, 86CT->86`), đồng thời phát hiện thêm tuyến mới `122` (`29B21262`, không nằm trong DB 2020).
   - **Tổng độ phủ xác nhận**: **`89 / 111` (`80.2%`) hoạt động**, **`22 / 111` (`19.8%`) rỗng hoàn toàn** tại thời điểm kiểm tra (`08A, 08ACT, 08B, 08BCT, 09A, 09B, 19, 21A, 21B, 37, 43, 46, 57, 58, 59, 60A, 60B, 61, 64, 65, 72, 74`). Lưu ý tồn tại nhiễu tức thời theo giờ: tuyến `02` từng rỗng khi quét 1 lượt ở test mẫu nhưng trả `6/6` xe khi kiểm tra sâu (`diagnose_5_failed_routes.json`).
3. **Test ổn định 4.9s × 4 xe (`stability_and_terminals_result.json`)**: `20` chu kỳ (`1676`, `4` xe Tuyến 32 `29F05223, 29F05241, 29F05208, 29F05192`) -> **`80 / 80` (100%)** thành công, `0` rỗng, `0` lỗi; `69` tọa độ mới + `7` tọa độ trùng (`9.2%` trên `76` bước chuyển); độ trễ `P50 = 176.8 ms`, `P90 = 367.3 ms`, `max = 530.6 ms`; max 1 chu kỳ `1,912.9 ms` (`0/20` vượt ngưỡng `4.9s`).
4. **Kiểm chứng live trên code mới (`reproduce_all_experiments.py --live`)**: Chạy `TimBusClient.query_central_vehicles([1676, 157], ..., route_code="")` thu được `3/4` xe (`29F05106`, `29F05130`, `29F05272`; xe thứ 4 `29F05183` trả rỗng -> fallback BusMap).

---

## 4. Quy tắc Áp dụng API Tối ưu & Ranh giới Tuyệt đối

| Nên làm (Best Practice) | Tuyệt đối Tránh (Anti-Pattern) |
| :--- | :--- |
| Dùng **BusMap** chọn tối đa **4 biển số trung tâm** (`3` sắp tới + `1` vừa qua trạm `S`), cập nhật danh sách mỗi 15–20s. | Quét toàn trạm/toàn tuyến với `vehicle_param=""` (**Shadowing 92%**) hoặc tin kết quả thô `M1` (**25.5% sai xe**). |
| Query đích danh bằng `TimBusClient.query_central_vehicles` với **`route_code=""`**, **`station_ids=[bến_cuối, trạm_kế_cuối, bến_cuối_bm]`**, chu kỳ **4.9–5.0s**, `timeout=3s`, **không retry**. | Truyền `station_id = 0` (luôn rỗng), truyền trạm mục tiêu `S` dễ lệch (`395`), hoặc cứng nhắc truyền mã tuyến DB 2020 làm hụt các tuyến `*CT`. |
| Ở bước nhận gói tin: chỉ kiểm tra **khớp biển số chuẩn hóa** và **`(lat, lon) != (0, 0)`**, lấy bản ghi đầu nếu trùng `Count=2`. | Cắt bỏ ở tầng parse dựa vào `cross_track <= 35 m` (mất xe Quán Sứ/Giáp Bát) hoặc tin `record.direction` (`'Về'` 100%). |
| Đưa `(lat, lon, speed)` về **hệ quy chiếu `canonical_shape_master` (BusMap)** để lọc `s <= s_S + 15 m`, tính khoảng cách, feature Model 6 và fallback mượt về BusMap khi thiếu. | Đưa `next_station_id`, `distance_m`, hoặc `station_id` của TimBus vào **Lakehouse lịch sử**, **feature đoàn xe `FAMILY_B`**, hoặc tính **ETA thẳng từ TimBus**. |

---

## 5. Chỉ mục Bàn giao Mã nguồn, Tài liệu & Tái lập Thực nghiệm

### 5.1. Tài liệu & Mã nguồn chính thức
1. **Bàn giao kỹ thuật tổng hợp (tài liệu này)**: [`TIMBUS_MASTER_HANDOVER.md`](file:///z:/Desktop/Bus_tracking/experiments/timbus/TIMBUS_MASTER_HANDOVER.md)
2. **Quy trình WebApp Demo 5 bước**: [`TIMBUS_WEBAPP_DEMO_PROCEDURE.md`](file:///z:/Desktop/Bus_tracking/experiments/timbus/TIMBUS_WEBAPP_DEMO_PROCEDURE.md)
3. **Client viễn trắc TimBus đã chỉnh sửa**: [`timbus_tracker.py`](file:///z:/Desktop/Bus_tracking/experiments/timbus/timbus_tracker.py) (bổ sung semantic properties trên `BusRecord`, `normalize_plate`, sửa mặc định `route_code=""` + lọc đúng biển số trong `query_targeted_vehicle`, thêm `query_central_vehicles` đa trạm neo & no-retry).
4. **Script tái lập tổng hợp (1 lệnh kiểm chứng tất cả)**: [`reproduce_all_experiments.py`](file:///z:/Desktop/Bus_tracking/experiments/timbus/reproduce_all_experiments.py)

```powershell
# Kiểm chứng offline toàn bộ số liệu DB tĩnh, 30 sweeps Tuyến 32, shadowing, M1/M2/M3, 111 tuyến & unit test codec
.\.venv\Scripts\python.exe experiments/timbus/reproduce_all_experiments.py --offline

# Kiểm chứng kèm 1 chu kỳ query live bằng query_central_vehicles() trên 4 xe Tuyến 32
.\.venv\Scripts\python.exe experiments/timbus/reproduce_all_experiments.py --live

# Truy vấn nhanh 1 xe bằng CLI mới (mặc định route_param="")
.\.venv\Scripts\python.exe experiments/timbus/timbus_tracker.py --station 1676 --plate 29F05192 --direction 0
```

### 5.2. Tài liệu Reverse Engineering & Script Thực nghiệm Gốc Tham chiếu (trong `experiments/timbus/`)
- **Tài liệu dịch ngược APK gốc**: [`timbus_gps_query_request_response_report.md`](file:///z:/Desktop/Bus_tracking/experiments/timbus/timbus_gps_query_request_response_report.md), [`timbus_stations_and_routes_report.md`](file:///z:/Desktop/Bus_tracking/experiments/timbus/timbus_stations_and_routes_report.md), [`timbus_hardware_heartbeat_report.md`](file:///z:/Desktop/Bus_tracking/experiments/timbus/timbus_hardware_heartbeat_report.md), [`timbus_telemetry_pipeline_report.md`](file:///z:/Desktop/Bus_tracking/experiments/timbus/timbus_telemetry_pipeline_report.md), [`timbus_smooth_map_rendering_engine.md`](file:///z:/Desktop/Bus_tracking/experiments/timbus/timbus_smooth_map_rendering_engine.md).
- **DB tĩnh & dữ liệu lưu trữ**: [`timbus_hanoi.sqlite`](file:///z:/Desktop/Bus_tracking/experiments/timbus/timbus_hanoi.sqlite), [`routes.json`](file:///z:/Desktop/Bus_tracking/experiments/timbus/routes.json), thư mục kết quả JSON/CSV & raw sweeps `experiments/timbus/data/`.
- **Các script thành phần**: `experiments/timbus/scripts/` (`compare_timbus_busmap_stations_routes.py`, `run_route32_parity_experiment.py`, `analyze_update_time_and_shadowing.py`, `analyze_nearest_bus_station_experiment.py`, `run_unified_nearest_bus_benchmark.py`, `audit_assumptions_and_high_shape_diff.py`, `verify_protocol_fields_realtime.py`, `test_stability_and_terminals.py`, `audit_all_111_routes_terminals_live.py`, `recheck_31_empty_routes_midstops.py`, `recheck_28_routes_empty_route_param.py`).
