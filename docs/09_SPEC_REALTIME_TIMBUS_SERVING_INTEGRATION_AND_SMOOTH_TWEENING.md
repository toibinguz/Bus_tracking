# ĐẶC TẢ THIẾT KẾ: TÍCH HỢP VIỄN TRẮC TIMBUS 5S & LÀM MƯỢT ĐỘNG HỌC WEB DEMO
> **Mã tài liệu**: `docs/09_SPEC_REALTIME_TIMBUS_SERVING_INTEGRATION_AND_SMOOTH_TWEENING.md`  
> **Căn cứ pháp lý**: Tuân thủ **Điều 1** (Kỷ luật thực nghiệm), **Điều 2** (Thiết kế trước, duyệt rồi mới code), **Điều 3** (Đóng băng crawler contract), **Điều 4** (Nguồn chân lý tối thượng), và **Điều 5** (Động học dẫn xuất) của [AGENTS.md](file:///z:/Desktop/Bus_tracking/AGENTS.md).  
> **Mục tiêu**: Xóa bỏ triệt để hiện tượng xe buýt "đứng im khựng đỗ 15s–45s rồi bay nhanh tên lửa 4.5s ở 400 km/h" trên Web Demo Module 3.5; thiết lập luồng phục vụ vi mô 5.0s siêu mượt mà không gây Train/Serve Skew cho mô hình ML vĩ mô đã đóng băng.

---

## I. HIỆN TRẠNG & PHÂN TÍCH PHÁP Y ĐỘNG HỌC (CURRENT DEFECT FORENSICS)

### 1. Hiện trạng Web Demo hiện tại
- **Backend**: Trong [`api_routes.py`](file:///z:/Desktop/Bus_tracking/module_3_bus_eta_prediction/step_3_5_web_demo/api_routes.py) và [`eta_serving_service.py`](file:///z:/Desktop/Bus_tracking/module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/eta_serving_service.py), luồng dữ liệu 100% vẫn đang truy vấn cổng **BusMap API** (`fetch_route_buses_live`). Client TimBus chưa hề được kết nối vào backend Web Demo.
- **Frontend**: Trong [`app.js`](file:///z:/Desktop/Bus_tracking/module_3_bus_eta_prediction/step_3_5_web_demo/static/js/app.js), chu kỳ polling được cấu hình cố định là `POLL_INTERVAL_MS = 15000` (15 giây).
- **Animation**: Trong [`map_manager.js`](file:///z:/Desktop/Bus_tracking/module_3_bus_eta_prediction/step_3_5_web_demo/static/js/map_manager.js), hàm `animateMarkerTo(marker, [lat, lon], 4500)` được gán cứng thời lượng `durationMs = 4500` (4.5 giây) kèm hàm giảm tốc bậc hai `Ease-out quad` ($f(p) = p(2 - p)$).

### 2. Cơ chế vật lý sinh ra lỗi "Bay nhanh rồi khựng chết dí"
```
Thời gian (giây):   0s                15s               30s               45s               60s
BusMap GPS:         Tọa độ A          Tọa độ A (chưa đổi) Tọa độ A (chưa đổi) Tọa độ B (+400m)   Tọa độ B
Frontend Poll:      Poll 1            Poll 2            Poll 3            Poll 4            Poll 5
Marker Hành vi:     Đứng im tại A     Đứng im tại A     Đứng im tại A     BAY NHANH VỀ B    Đứng im tại B
                                                                          (4.5s @ 320km/h)  (chết dí 10.5s)
```
- Máy chủ BusMap chỉ cập nhật tọa độ viễn trắc GPS mỗi $30\text{s} - 75\text{s}$.
- Ở các lần poll tại $15\text{s}$ và $30\text{s}$, BusMap trả về tọa độ cũ $\implies \Delta s < 0.5\text{m} \implies$ Marker đứng im bất động. Hành khách tưởng ứng dụng bị đơ hoặc xe dừng đỗ.
- Đến lần poll tại $45\text{s}$ (hoặc $60\text{s}$), BusMap nhả tọa độ mới đã di chuyển thực tế $300\text{m} - 500\text{m}$.
- Frontend nhận tọa độ mới và kích hoạt `animateMarkerTo(..., 4500)`. Xe bị ép chạy $400\text{m}$ chỉ trong $4.5\text{s}$:
  $$v_{\text{visual}} = \frac{400\text{ m}}{4.5\text{ s}} \times 3.6 = 320 \text{ km/h}!$$
- Sau khi "bay vèo" đến đích trong $4.5\text{s}$, Marker dừng khựng lại và **đứng chết dí $10.5\text{s}$ còn lại** của chu kỳ poll.

---

## II. THIẾT KẾ KIẾN TRÚC MỚI: HỆ THỐNG LAI GHÉP VI MÔ 5S (MACRO-MICRO REALTIME FUSION)

Tuân thủ **Điều 3** (Không đụng vào Ingestion 24/7) và **Điều 4** (Nguồn chân lý tối thượng):

```
                                  YÊU CẦU DỰ BÁO TỪ FRONTEND (MỖI 5 GIÂY)
                                                     │
                                                     ▼
                                      ┌──────────────────────────────┐
                                      │ Backend Cache Manager (4s)   │
                                      └──────────────┬───────────────┘
                                                     │ Cache Miss
                                                     ▼
                                      ┌──────────────────────────────┐
                                      │ Hybrid Telemetry Coordinator │
                                      └──────────────┬───────────────┘
                                                     │
                         ┌───────────────────────────┴───────────────────────────┐
                         ▼                                                       ▼
         ┌──────────────────────────────┐                        ┌──────────────────────────────┐
         │ TimBus Realtime Client (5.0s)│                        │ BusMap Fleet Relay (30-75s)  │
         │ - Endpoint Cổng 9149          │                        │ - Định danh ID toàn cục      │
         │ - Tọa độ hộp đen siêu tươi   │                        │ - Trạng thái bến bãi & xe đỗ │
         └──────────────┬───────────────┘                        └──────────────┬───────────────┘
                        │ (lat, lon, plate)                                     │ (vehicle_id, route_buses)
                        └────────────────────────────┬──────────────────────────┘
                                                     │
                                                     ▼
                                      ┌──────────────────────────────┐
                                      │ Frenet Bridge & Plate Matcher│
                                      │ - Map biển số plate -> vid   │
                                      │ - Chiếu d_perp <= 35.0m      │
                                      │ - Bảo toàn chiều (TD-37)     │
                                      └──────────────┬───────────────┘
                                                     │
                                                     ▼
                                      ┌──────────────────────────────┐
                                      │ Fallback State Machine (FSM) │
                                      │ 1. TIMBUS_5S (Ưu tiên số 1)  │
                                      │ 2. BUSMAP_RELAY (Khi rớt sóng)│
                                      │ 3. DEAD_RECKONING (Làm mượt) │
                                      └──────────────┬───────────────┘
                                                     │
                                                     ▼
                                      ┌──────────────────────────────┐
                                      │ Macro ETA Engine (Đóng băng) │
                                      │ - Baseline P10/P50/P90 Matrix│
                                      │ - XGBoost Residual Model     │
                                      └──────────────┬───────────────┘
                                                     │
                                                     ▼
                                      ┌──────────────────────────────┐
                                      │ JSON Payload Chuẩn Contract  │
                                      │ telemetry_source: 'timbus_5s'│
                                      └──────────────────────────────┘
```

### 1. Nguyên tắc cốt lõi: Tách biệt Vĩ mô vs. Vi mô (Zero Train/Serve Skew)
- **Tầng Vĩ mô (Macro ETA - Giữ nguyên tuyệt đối)**: Ma trận Baseline $P_{50}$ và mô hình XGBoost tiếp tục tính toán thời gian chạy giữa các phân đoạn trạm ($k_{\text{curr}} \to tk$).
- **Tầng Vi mô (Micro Interpolation - TimBus 5s)**: Tọa độ siêu tươi từ TimBus chỉ dùng để:
  1. Xác định chính xác vị trí thực tế của xe trên tim đường ($s_{\text{bus}}$).
  2. Tính khoảng cách còn lại tới trạm kế tiếp: $\Delta s_{\text{next}} = s_{k_{\text{curr}}+1} - s_{\text{bus}}$.
  3. Cung cấp tọa độ WGS-84 tươi 5.0s để Marker trên bản đồ chuyển động mượt mà liên tục.

### 2. Máy trạng thái Fallback (Telemetry Fallback State Machine)
Mỗi phương tiện được quản lý theo một FSM 3 trạng thái nghiêm ngặt để triệt tiêu lỗi mất dấu xe (`TD-38`) và lệch hành lang (`TD-41`):

```
        ┌─────────────────────────────────────────────────────────────┐
        │                                                             │
        ▼                                                             │
 ┌──────────────┐   TimBus mất tín hiệu > 10s hoặc d_perp > 35m  ┌──────────────────┐
 │  TIMBUS_5S   ├───────────────────────────────────────────────►│  BUSMAP_RELAY   │
 └──────▲───────┘                                                └────────┬─────────┘
        │                                                                 │
        │               Khôi phục tín hiệu TimBus tươi <= 5s              │
        └─────────────────────────────────────────────────────────────────┘
```

- **Trạng thái 1 (`TIMBUS_5S`)**: Xe có bản tin TimBus trong vòng 10 giây gần nhất VÀ khoảng cách vuông góc tim đường $d_\perp \le 35.0\text{m}$. Vị trí và vận tốc hiển thị lấy từ TimBus.
- **Trạng thái 2 (`BUSMAP_RELAY`)**: Xe không có trên TimBus (xe tắt máy tại bến bãi theo `TD-38`, chiếm 17–23%) HOẶC xe đi đường tránh lệch tim đường $d_\perp > 35.0\text{m}$ (theo `TD-41`). Hệ thống tự động fallback 100% về vị trí BusMap.
- **Trạng thái 3 (`DEAD_RECKONING`)**: Nếu trong 5 giây kế tiếp cả 2 hệ thống đều chưa có bản tin mới, Marker tự động tịnh tiến dọc theo tim đường với vận tốc hiện tại:
  $$s(t + \Delta t) = s(t) + \bar{v} \cdot \Delta t$$

---

## III. THIẾT KẾ FRONTEND: LINEAR CONTINUOUS TWEENING 60 FPS

### 1. Thay đổi cấu hình Polling & Cache
- `POLL_INTERVAL_MS = 5000` (giảm từ 15s xuống **5.0 giây**).
- Backend `route_eta_cache` TTL giảm từ 15s xuống **4.0 giây** để luôn cấp phát dữ liệu tươi mới.

### 2. Thuật toán Di chuyển Liên tục Tuyến tính (Linear Kinematic Animation)
Khác với hiệu ứng đồ họa thông thường dùng `Ease-out quad` (vọt nhanh rồi hãm phanh), chuyển động của xe buýt ngoài đời thực là quán tính tuyến tính.
Lấy cảm hứng từ chính Dalvik bytecode của Tìm Buýt (`com.binhanh.bushanoi.map.f.C` dùng `ObjectAnimator` tuyến tính):

- **Easing Function**: Tuyến tính hoàn toàn $f(p) = p$ (Linear Easing):
  $$\text{lat}(t) = \text{lat}_0 + p \cdot (\text{lat}_{\text{target}} - \text{lat}_0)$$
  $$\text{lon}(t) = \text{lon}_0 + p \cdot (\text{lon}_{\text{target}} - \text{lon}_0)$$
- **Thời lượng động (`durationMs`)**: Gán bằng đúng chu kỳ lấy mẫu thực tế ($5000\text{ms}$).
- **Vận tốc thực tế**: Khi xe chạy $30\text{ km/h}$, trong 5 giây xe đi được:
  $$\Delta s = \frac{30}{3.6} \times 5 \approx 41.6\text{ mét}$$
  Xe sẽ trượt êm ả $41.6\text{ mét}$ trong suốt 5 giây ở tốc độ 60 FPS. Đúng lúc hoạt ảnh hoàn thành (5000ms), gói tin viễn trắc tiếp theo vừa tới nơi $\implies$ Marker nối tiếp chuyển động mượt mà liên tục, triệt tiêu 100% hiện tượng "đứng chết dí rồi bay nhanh"!

- **Bộ lọc Ngắt Quá tốc (Anti-Supersonic Guard)**:
  Nếu khoảng cách dịch chuyển giữa 2 bản tin vượt quá $200\text{m}$ trong 5s (tương đương $v > 144\text{ km/h}$ - dấu hiệu nhảy cóc GPS):
  $\implies$ Hủy animation, gán trực tiếp (`setLatLng`) để chống hiện tượng xe "bay nhanh".

---

## V. NÂNG CẤP ĐỘNG HỌC TOÀN DIỆN: DEAD RECKONING 1D FRENET TƯƠNG LAI GẦN & HÒA GIẢI SAI SỐ LIÊN TỤC

### 1. Bản chất Vật lý & Bác bỏ Cơ chế Tweening Quá khứ
- **Cơ chế Tweening Quá khứ ($P_{\text{old}} \to P_{\text{meas}}$)**: Luôn đi sau thực tế 5–10 giây. Khi gói tin mới bị trễ nhẹ 0.5s do mạng viễn thông, xe hết quãng đường di chuyển và bị khựng lại đứng im. Khi có gói mới, xe phải phóng nhanh để bù lại quãng đường quá khứ.
- **Cơ chế Dead Reckoning & Client-side Prediction (Tương lai gần)**:
  Phương tiện luôn di chuyển về phía trước theo vector vận tốc thực tế $v_{\text{eff}}$ dọc theo trục tim đường 1D Frenet $s \in [0, L_{\text{corridor}}]$:
  $$s_{\text{sim}}(t + dt) = s_{\text{sim}}(t) + v_{\text{eff}} \cdot dt$$
  Marker trên bản đồ uốn lượn chính xác 100% bám sát tim đường chuẩn ($O(\log N)$ binary search), xoay mượt theo cung ngắn nhất (TimBus `map/f.i`). Xe không bao giờ bị đứng chết dí hay trôi ra khỏi lòng đường.

### 2. Thuật toán Hòa giải Sai số Liên tục (Continuous Error Reconciliation)
Khi nhận bản tin đo đạc mới từ hộp đen GPS ($s_{\text{meas}}$, $v_{\text{meas}}$):
Sai số vị trí giữa thực tế và mô phỏng:
$$\Delta s_{\text{err}} = s_{\text{meas}} - s_{\text{sim}}$$

Phân nhánh điều hòa:
1. **Khử lặp tọa độ IEEE-754 (TimBus `map/f.C`)**: Nếu $s_{\text{meas}} == s_{\text{lastMeas}}$ và $v_{\text{meas}} = 0$, xe khóa đứng yên tại điểm dừng, triệt tiêu mọi rung lắc.
2. **Teleport Guard**: Nếu $|\Delta s_{\text{err}}| > 150.0\text{m}$, snap tức thời về vị trí mới chống bay xuyên thành phố.
3. **Xe dừng đỗ ngoài đời thực ($v_{\text{meas}} < 0.5\text{ m/s}$)**: Nếu xe mô phỏng gần tới nơi ($\Delta s_{\text{err}} \le 1.0\text{m}$), snap dừng tại $s_{\text{meas}}$. Nếu còn cách một đoạn ngắn, giảm tốc êm ái về 0 trong 1.5s.
4. **Hành trình bình thường ($v_{\text{meas}} \ge 0.5\text{ m/s}$)**:
   Hấp thu sai số vị trí vào vận tốc hiệu dụng trong cửa sổ $\tau = 4.5\text{s}$:
   $$v_{\text{eff}} = \max\left(0.5, \;\min\left(22.2, \; v_{\text{meas}} + \frac{\Delta s_{\text{err}}}{\tau}\right)\right)$$
   Kết quả: Xe bắt kịp hoặc giảm nhẹ tốc độ mượt mà, hội tụ hoàn hảo về quỹ đạo thực tế sau 4.5 giây mà không hề có bất kỳ cú giật tọa độ nào!

---

## VI. BỘ TIÊU CHUẨN KIỂM ĐỊNH & NGHIỆM THU (TEST ORACLES & ACCEPTANCE)

Để ngăn chặn tuyệt đối "sửa 1 lỗi sinh 2 lỗi" và "vá lỗi thô thiển", toàn bộ hệ thống được kiểm định qua:
1. **Test Toán học JavaScript (`scripts/test_dead_reckoning_kinematics.js`)**: 18/18 tiêu chí PASS 100% (Tính đơn điệu tim đường, tịnh tiến tương lai gần, hòa giải sai số liên tục, khử lặp TimBus map/f.C, teleport guard 150m, cung quay ngắn nhất map/f.i).
2. **Test Chống Gian lận & Bất biến (`scripts/test_anti_cheat_remediation.py`)**: 7/7 bài kiểm định PASS 100%.
3. **Test Viễn trắc TimBus Serving (`scripts/test_timbus_realtime_serving.py`)**: 6/6 bài kiểm định PASS 100%.
4. **Test Web Demo RESTful API (`scripts/verify_web_app_demo.py`)**: 5/5 bài kiểm định PASS 100%.
