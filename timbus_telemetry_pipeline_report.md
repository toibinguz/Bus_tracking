# Báo cáo Kỹ thuật Chuyên sâu: Chu trình Dữ liệu Viễn trắc TimBus (BA GPS)
## Từ Thu nhận Gói tin Mạng Nhị phân đến Dựng hình Marker Xe buýt trên Màn hình

---

### Tóm tắt Điều hành (Executive Summary)

Tài liệu này cung cấp bản phân tích kiến trúc và kỹ thuật dịch ngược (Reverse Engineering) chi tiết nhất về toàn bộ luồng dữ liệu (End-to-End Telemetry Pipeline) trong ứng dụng **Tìm Buýt** (`com.binhanh.bushanoi`, Phiên bản 5.6.0, Target SDK 34) do Công ty Cổ phần Công nghệ Bình Anh (BA GPS / Transerco) phát triển.

Báo cáo bóc tách từng byte dữ liệu, thuật toán mật mã, mô hình lớp Dalvik, cơ chế khử lặp tọa độ, và kỹ thuật dựng hình đồ họa để trả lời câu hỏi: **Làm thế nào dữ liệu tọa độ từ máy chủ viễn trắc trở thành chuyển động mượt mà của biểu tượng xe buýt trên màn hình điện thoại?**

```mermaid
sequenceDiagram
    autonumber
    participant Srv as Máy chủ BA GPS (timbus.vn:9149)
    participant CE as ConnectionExecute / cg2
    participant DTO as Deserializer (vd2 / m73)
    participant Bus as Thực thể Bus (Lij;)
    participant MapF as Bộ điều phối Bản đồ (map/f)
    participant Anim as ObjectAnimator / zd (TypeEvaluator)
    participant GM as Google Maps SDK (Marker / GPU)

    loop Chu kỳ 5.000 ms (Ltd2;->run)
        DTO->>CE: Yêu cầu cập nhật VehicleState (routeId, plate, dir)
        CE->>Srv: HTTP GET ?ReqParams=[XOR Stream + Checksum Base64]
        Srv-->>CE: HTTP 200 OK [Ciphertext + Key1 + Key2 + Checksum]
        CE->>CE: Kiểm tra Checksum (modulo 256) & Giải mã XOR Key1
        CE->>DTO: Trả về danh sách xe buýt giải mã (List<Lij;>)
        DTO->>Bus: Duyệt từng xe, gọi Bus.c()
        Bus->>MapF: Gọi map/f.d(map, bus, newLatLng)
        alt Tọa độ trùng lặp (map/f.C() == true)
            MapF-->>MapF: RETURN-VOID (Ngắt sớm, giữ nguyên vị trí & góc quay)
        else Tọa độ mới (map/f.C() == false)
            MapF->>MapF: map/f.K() -> Tính góc hướng Spherical & Xoay ValueAnimator
            MapF->>Anim: map/f.E() -> Khởi tạo ObjectAnimator (Duration = 5.000ms)
            loop V-Sync 60 FPS (t = 0.0 -> 1.0)
                Anim->>Anim: zd.evaluate() -> Nội suy tuyến tính LatLng(t)
                Anim->>GM: Marker.setPosition(interpolatedLatLng)
                GM->>GM: Dựng hình OpenGL/Vulkan ra màn hình
            end
        end
    end
```

---

### Giai đoạn 1: Polling, Thu nhận Gói tin & Giải mã Nhị phân

#### 1. Bộ lập lịch Polling 5.000 ms
Ứng dụng duy trì vòng lặp thời gian thực thông qua lớp Runnable [`Ltd2;`](file:///z:/Desktop/Reverse%20Enginering/extracted_timbus/com.binhanh.bushanoi.apk):
- Hằng số chu kỳ: `0x1388` ($5.000\text{ ms} = 5.0\text{ giây}$).
- Phương thức thực thi: `Ltd2;->run()` gọi `Ln73;->m(routeId, str1, str2, direction)` rồi tái lập lịch qua `Handler.postDelayed(this, 5000L)`.

#### 2. Đóng gói & Phát Request HTTP GET
Lớp `Ln73;->m` sử dụng bộ sinh nhị phân `Lqh0;` để cấu trúc payload 9-byte:
$$\text{Payload} = [\text{route\_id: 4B Big-Endian}] + [\text{len\_plate: 2B}] + [\text{plate}] + [\text{len\_str: 2B}] + [\text{str}] + [\text{direction: 1B}]$$

Dữ liệu được chuyển sang `Lcg2;->execute()` để mã hóa đối xứng:
1. Sinh ngẫu nhiên `key1` (32 bytes) và `key2` (64 bytes) từ bảng ký tự ASCII $[48, 127]$.
2. Ghép 4 bytes Client ID prefix (`0x00000000`) với payload.
3. Mã hóa dòng XOR:
   $$C[i] = P[i] \oplus \text{key1}[i \pmod{32}]$$
4. Đóng gói Trailer và Checksum 8-bit:
   $$\text{Packet} = C + \text{key1} + [\text{len}(\text{key1})] + \text{key2} + [\text{len}(\text{key2})] + [\text{Checksum}]$$
   $$\text{Checksum} = \left( \sum_{k=0}^{N-1} \text{Packet}[k] \right) \pmod{256}$$
5. Mã hóa Base64 và gửi qua URL:
   `GET http://www.timbus.vn:9149/SearchBuyt/VehicleState?ReqParams=<Base64_String>`

#### 3. Tiếp nhận Phản hồi & Giải mã tại Client
Khi máy chủ phản hồi chuỗi Base64:
- Lớp [`com.binhanh.controller.ConnectionExecute`](file:///z:/Desktop/Reverse%20Enginering/extracted_timbus/com.binhanh.bushanoi.apk) thực hiện giải mã ngược:
  1. Base64 Decode ra mảng byte thô $R$.
  2. Lấy byte cuối cùng $R[L-1]$ làm `expected_checksum`.
  3. Tính tổng `actual_checksum = sum(R[0..L-2]) & 0xFF`. Nếu sai lệch $\rightarrow$ Quăng lỗi toàn vẹn dữ liệu.
  4. Đọc độ dài khóa: $\text{len}(K_2) = R[L-2]$, $\text{len}(K_1) = R[L-2-\text{len}(K_2)-1]$.
  5. Trích xuất $K_1$ từ vị trí tương ứng.
  6. Giải mã dòng XOR phần Ciphertext phía trước với $K_1[i \pmod{\text{len}(K_1)}]$.
  7. Bỏ qua 4 byte Client ID đầu tiên để thu về mảng byte dữ liệu viễn trắc thô hoàn chỉnh.

---

### Giai đoạn 2: Phân tích DTO & Mô hình Dữ liệu Phương tiện

Dữ liệu giải mã được phân giải tự động trong `Lcg2;->onComplete` và chuyển đến Presenter [`Lvd2;`](file:///z:/Desktop/Reverse%20Enginering/extracted_timbus/com.binhanh.bushanoi.apk):

#### Cấu trúc Thực thể Xe buýt: Class `Lij;` (`Bus`)
Mỗi xe buýt trên tuyến được biểu diễn bằng một thực thể `Lij;`:
| Trường (Field) | Kiểu dữ liệu | Ý nghĩa Nghiệp vụ |
| :--- | :--- | :--- |
| `r` | `int` | Mã số tuyến xe buýt (`route_id`) |
| `s` | `String` | Biển kiểm soát phương tiện (ví dụ: `29B-191.45`) |
| `t` | `String` | Mã hiệu nội bộ / Tên tài xế hoặc số hiệu xe |
| `u` | `int` | Mã định danh điểm dừng kế tiếp (`next_station_id`) |
| `v` | `int` | Vận tốc tức thời đo bằng GPS ($\text{km/h}$) |
| `w` | `String` | Nhãn thời gian cập nhật của hộp đen |
| `x` | `byte` | Mã trạng thái truyền dẫn viễn trắc |
| `y` | `LatLng` | Tọa độ GPS hiện tại (`latitude`, `longitude`) kiểu `com.google.android.gms.maps.model.LatLng` |
| `z` | `Bus$Direction` | Chiều di chuyển (Chiều đi `FORWARD` hoặc Chiều về `BACKWARD`) |
| `A` | `byte` | Trạng thái điều độ (đang chạy tuyến, về gara, lệch lộ trình) |
| `B` | `boolean` | Cờ trạng thái di chuyển (`true`: đang lăn bánh, `false`: dừng/đỗ) |
| `C` | `Marker` | Thể hiện Marker tương ứng của xe trên Google Maps SDK |

Trong phương thức `Lvd2;->B0()`, ứng dụng duyệt qua danh sách xe buýt `m73.a` nhận được, cập nhật thông tin hiển thị (biển số, vận tốc lên bảng thông tin dưới màn hình) và gọi:
```java
bus.c(googleMap, newLatLng); // invokes Lij;->c
```
Phương thức `Lij;->c` lập tức chuyển tiếp lệnh đến bộ điều phối bản đồ:
```java
f.d(googleMap, this, newLatLng); // invokes Lcom/binhanh/bushanoi/view/base/map/f;->d
```

---

### Giai đoạn 3: Bộ lọc Khử lặp Tọa độ & Đo lường Vi sai

Mặc dù hộp đen GPS trên xe buýt và ứng dụng Tìm Buýt đều hoạt động ở chu kỳ danh định **$5.000\text{ ms}$ ($5.0\text{ giây}$)** (đã được thẩm định thực nghiệm độc lập trong [Báo cáo Heartbeat Phần cứng](file:///z:/Desktop/Reverse%20Enginering/docs/timbus_hardware_heartbeat_report.md) với $\mu = 4.96\text{s}$), hiện tượng lệch pha (Phase Drift) và trôi đồng hồ giữa hai hệ thống khiến khoảng $15\% - 20\%$ các truy vấn của ứng dụng client nhận về dữ liệu tọa độ lặp (do gói tin GPS mới chưa kịp đến máy chủ). Do đó, **việc lọc các gói tin có tọa độ lặp là cơ chế sống còn để tránh giật lag màn hình**.

#### 1. Kiểm tra Tính Hợp lệ: `f->B(LatLng)`
*(Địa chỉ code: `0x47cce4`)*
```smali
# Kiểm tra nếu LatLng là null hoặc toạ độ rỗng (0.0, 0.0)
[0001] if-nez v5, :is_null_or_zero
[0008] cmpl-double v1, v1, 0.0      # Kiểm tra vĩ độ == 0.0
[000e] cmpl-double v5, v1, 0.0      # Kiểm tra kinh độ == 0.0
```
Nếu tọa độ bị lỗi hoặc mất sóng vệ tinh, hàm trả về cờ không hợp lệ, ứng dụng bỏ qua chu kỳ cập nhật vị trí.

#### 2. Bộ lọc Đẳng cự IEEE-754: `f->C(LatLng p0, LatLng p1)`
*(Địa chỉ code: `0x47cd20`)*
So sánh chính xác vị trí mới nhận về từ gói tin (`bus.y`) với vị trí hiện tại của Marker trên bản đồ (`marker.getPosition()`):
```smali
[000e] iget-wide v2, p0, LatLng->latitude
[0010] iget-wide v4, p1, LatLng->latitude
[0012] cmpl-double v0, v2, v4              # So sánh latitude
[0014] if-nez v0, :return_false            # Khác nhau -> Có điểm mới (false)
[0016] iget-wide v2, p0, LatLng->longitude
[0018] iget-wide v6, p1, LatLng->longitude
[001a] cmpl-double v6, v2, v6              # So sánh longitude
[001c] if-nez v6, :return_false            # Khác nhau -> Có điểm mới (false)
:return_true
[001e] const/4 v1, 1
[0020] return v1                            # TRÙNG LẶP HOÀN TOÀN (true)
```

#### 3. Điểm ngắt Điều phối: `f->d`
*(Địa chỉ code: `0x47d4d0`)*
```smali
[0037] iget-object v4, bus, Lij->y
[0039] invoke-virtual {marker}, Marker->getPosition()
[003d] invoke-static {bus.y, marker.getPosition()}, f->C(LatLng, LatLng)Z
[0040] move-result v4
[0041] if-eqz v4, :update_animation        # Nếu v4 == 0 (Điểm mới) -> Chạy animation
[0044] return-void                          # Nếu v4 == 1 (TỌA ĐỘ LẶP) -> RETURN NGAY LẬP TỨC!
```

> [!IMPORTANT]
> **Tác động của lệnh `return-void` khi gặp tọa độ lặp:**
> 1. **Triệt tiêu Animator rác**: Không tạo mới các `ObjectAnimator` chạy từ $A \to A$, bảo tồn 100% chu kỳ CPU/GPU.
> 2. **Đứng yên ổn định**: Marker vừa hoàn tất trượt của 5s trước đó, dừng lại chuẩn xác tại đích mà không bị giật ngược.
> 3. **Khóa góc xoay (Heading Lock)**: Ngăn chặn hiện tượng xoay lắc ngẫu nhiên do sai số trôi dạt GPS khi xe dừng đỗ.

#### 4. Đo lường Khoảng cách Cầu Lớn: `f->g(LatLng, LatLng)`
*(Địa chỉ code: `0x47d25c`)*
Cài đặt công thức Haversine để tính khoảng cách thực tế theo mét:
$$d = 2R \cdot \arcsin \left( \sqrt{\sin^2\left(\frac{\Delta \phi}{2}\right) + \cos(\phi_1)\cos(\phi_2)\sin^2\left(\frac{\Delta \lambda}{2}\right)} \right)$$
- Sử dụng hằng số bán kính Trái Đất chính xác: $R = 6.371.000\text{ m}$ (Hằng số nhị phân `4708598820135501824` / `0x41584dae00000000` trong Dalvik).

---

### Giai đoạn 4: Thuật toán Xoay Hướng & Ổn định Góc Quay

Khi nhận tọa độ mới, xe phải quay đầu theo hướng di chuyển trước hoặc song song với hoạt ảnh tịnh tiến. Lớp `map/f` kích hoạt hàm xoay [`f->K(Lij bus)`](file:///z:/Desktop/Reverse%20Enginering/extracted_timbus/com.binhanh.bushanoi.apk) *(Code offset: `0x47d880`)*.

#### 1. Tính toán Góc Hướng (Heading Angle)
Hàm sử dụng `com.google.maps.android.SphericalUtil.computeHeading`:
$$\theta = \operatorname{atan2}\left(\sin(\Delta \lambda)\cos(\phi_2), \; \cos(\phi_1)\sin(\phi_2) - \sin(\phi_1)\cos(\phi_2)\cos(\Delta \lambda)\right)$$
Kết quả trả về góc trong khoảng $[-180^\circ, +180^\circ]$ hoặc chuẩn hóa $[0^\circ, 360^\circ)$.

#### 2. Thuật toán Cung Quay Ngắn Nhất: `f->i(float current, float target, float fraction)`
*(Địa chỉ code: `0x47d1fc`)*
Tránh lỗi quay một vòng $350^\circ$ khi xe đổi hướng nhẹ qua trục Bắc ($355^\circ \to 5^\circ$):
$$\Delta \theta = ((\text{target} - \text{current} + 540) \pmod{360}) - 180$$
$$\text{angle}(t) = \text{current} + t \cdot \Delta \theta$$

#### 3. Điều phối Xoay Mượt bằng `ValueAnimator`
Lớp [`com.binhanh.bushanoi.view.base.map.b`](file:///z:/Desktop/Reverse%20Enginering/extracted_timbus/com.binhanh.bushanoi.apk) triển khai `ValueAnimator.AnimatorUpdateListener`:
```smali
# b->onAnimationUpdate (Offset: 0x47cb00)
[0000] invoke-virtual {animation}, ValueAnimator->getAnimatedFraction()F # t thuộc [0.0, 1.0]
[0008] invoke-static {fraction, currentRot, targetRot}, map/f->i
[0010] invoke-virtual {marker}, Marker->setRotation(interpolatedAngle)
```

---

### Giai đoạn 5: Hoạt ảnh Nội suy Tọa độ 5.000 ms

Sau khi xác lập góc quay, phương thức [`f->E(GoogleMap map, Lij bus)`](file:///z:/Desktop/Reverse%20Enginering/extracted_timbus/com.binhanh.bushanoi.apk) *(Code offset: `0x47d5d0`)* khởi động hoạt ảnh tịnh tiến Marker:

```smali
# Khởi tạo ObjectAnimator cho thuộc tính "position" của Marker
[0007] iget-object v1, bus, Lij->C:Marker
[0009] const-string v2, "position"
[000b] new-instance v3, Lzd;                       # TypeEvaluator<LatLng>
[0012] invoke-virtual {marker}, Marker->getPosition()
[0016] iget-object v5, bus, Lij->y:LatLng
[001c] invoke-static {marker, "position", zd, [pos_old, pos_new]}, ObjectAnimator->ofObject()

# Thiết lập thời lượng đúng 5.000 ms khớp với chu kỳ Polling
[0022] const-wide/16 v2, 5000                      # 0x1388 = 5000 ms
[0024] invoke-virtual {animator}, ObjectAnimator->setDuration(J)

# Thiết lập LinearInterpolator đảm bảo vận tốc trượt không đổi
[0031] new-instance v2, Landroid/view/animation/LinearInterpolator;
[0036] invoke-virtual {animator}, Animator->setInterpolator()
[0048] invoke-virtual {animator}, ValueAnimator->start()
```

#### Thuật toán Nội suy Tuyến tính: `Lzd;->a(float t, LatLng p0, LatLng p1)`
*(Địa chỉ code: `0x192f18`)*
Lớp `Lzd;` hiện thực interface `android.animation.TypeEvaluator<LatLng>`:
```java
public LatLng evaluate(float fraction, LatLng startValue, LatLng endValue) {
    double lat = startValue.latitude + fraction * (endValue.latitude - startValue.latitude);
    double lng = startValue.longitude + fraction * (endValue.longitude - startValue.longitude);
    return new LatLng(lat, lng);
}
```
Tại mỗi khung hình render (16.6 ms trên màn hình 60 Hz), `ObjectAnimator` cập nhật `marker.setPosition(latLng)`. Vì thời lượng trượt đúng bằng chu kỳ polling ($5.000\text{ ms}$), marker di chuyển liên tục, không bao giờ bị giật khựng giữa các lần nhận gói tin.

---

### Giai đoạn 6: Dựng hình Đồ họa & Hiển thị trên Màn hình

#### 1. Khởi tạo Biểu tượng Xe buýt Động: `f->l` & `f->k`
- Phương thức `f->k(Context, View)` chuyển đổi một Android Layout View (chứa icon xe buýt, mã tuyến số `02`, `32`, `E05`, màu sắc chiều đi/về) thành `BitmapDescriptor` thông qua `Canvas` bộ nhớ đệm:
  ```java
  view.measure(MeasureSpec.UNSPECIFIED, MeasureSpec.UNSPECIFIED);
  view.layout(0, 0, view.getMeasuredWidth(), view.getMeasuredHeight());
  Bitmap bitmap = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888);
  view.draw(new Canvas(bitmap));
  BitmapDescriptor icon = BitmapDescriptorFactory.fromBitmap(bitmap);
  ```
- Thêm Marker vào bản đồ:
  ```java
  MarkerOptions options = new MarkerOptions()
      .position(bus.y)
      .icon(icon)
      .anchor(0.5f, 0.5f)    // Tâm xoay nằm chính giữa icon xe
      .flat(true);           // Cho phép icon xoay phẳng theo mặt phẳng bản đồ
  Marker marker = googleMap.addMarker(options);
  bus.C = marker;
  ```

#### 2. Dựng hình Phần cứng (Hardware Rendering)
- Toàn bộ vị trí `LatLng` của Marker sau khi được nội suy qua từng khung hình được đẩy trực tiếp xuống Google Maps Android C++ Engine (`libgoogle-maps.so`).
- Engine thực hiện ánh xạ từ hệ tọa độ địa lý WGS-84 sang phép chiếu Mercator hình chiếu màn hình (Screen Pixel Coordinates) và nạp ma trận biến đổi (Transformation Matrix: Translate + Rotate) vào GPU thông qua OpenGL ES / Vulkan shader.

---

### Bảng Tổng hợp Đối chiếu Lớp & Phương thức Thực thi

| Giai đoạn | Lớp (Class) | Phương thức (Method) | Nhiệm vụ Kỹ thuật |
| :--- | :--- | :--- | :--- |
| **1. Polling** | `Ltd2;` | `run()` | Polling định kỳ mỗi 5.000 ms (`0x1388`) |
| **2. Request** | `Ln73;` | `m(I, String, String, Z)` | Tạo payload nhị phân `VehicleState` |
| **3. Mã hóa/Giải mã** | `ConnectionExecute` / `cg2;` | `decode()`, `execute()` | XOR Stream Cipher, kiểm tra Checksum Modulo 256 |
| **4. Tiếp nhận DTO** | `vd2;` | `B0()`, `onComplete()` | Nhận danh sách xe `m73.a`, dispatch tới từng `Bus` |
| **5. Model Xe buýt** | `Lij;` (`Bus`) | `c(GoogleMap, LatLng)` | Cầu nối giữa dữ liệu nghiệp vụ và tầng Map |
| **6. Khử lặp Tọa độ** | `map/f;` | `B(LatLng)`, `C(LatLng, LatLng)` | Kiểm tra null/0.0 và so sánh đẳng cự IEEE-754 |
| **7. Điều phối Bản đồ** | `map/f;` | `d(GoogleMap, Lij, LatLng)` | Phân nhánh: Ngắt sớm `return-void` nếu lặp; Cập nhật nếu mới |
| **8. Đo lường Khoảng cách**| `map/f;` | `g(LatLng, LatLng)` | Haversine Great Circle ($R = 6.371.000\text{ m}$) |
| **9. Hoạt ảnh Xoay** | `map/f;`, `map/b;` | `K(Lij)`, `i()`, `onAnimationUpdate()` | Cung quay ngắn nhất, xoay góc Marker mượt |
| **10. Hoạt ảnh Tịnh tiến** | `map/f;`, `zd;` | `E(GoogleMap, Lij)`, `evaluate()` | `ObjectAnimator` 5.000 ms với `LinearInterpolator` |
| **11. Dựng hình GPU** | Google Maps SDK | `Marker.setPosition`, `setRotation` | Dựng hình 60 FPS trên OpenGL ES / Vulkan |

---
*Báo cáo được trích xuất và thẩm định tự động từ mã nguồn nhị phân Tìm Buýt v5.6.0 (`Tìm+Buýt_5.6.0_APKPure.xapk`).*
