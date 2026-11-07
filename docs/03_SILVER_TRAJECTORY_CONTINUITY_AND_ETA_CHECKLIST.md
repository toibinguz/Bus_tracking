# ĐẶC TẢ KIỂM TOÁN DÒNG GPS TẦNG SILVER & CHECKLIST BẮT BUỘC KHI XÂY DỰNG PIPELINE ETA
> **Mã tài liệu**: `docs/03_SILVER_TRAJECTORY_CONTINUITY_AND_ETA_CHECKLIST.md`  
> **Căn cứ pháp lý**: Tuân thủ **Điều 1** (Kỷ luật Thực nghiệm), **Điều 4** (Master Ground Truth), **Điều 5** (Động học dẫn xuất), và **Điều 8** (Minh bạch Nợ kỹ thuật) của [AGENTS.md](file:///z:/Desktop/Bus_tracking/AGENTS.md).  
> **Script kiểm chứng thực nghiệm**: [`experiments/eda_silver_tier_comprehensive.py`](file:///z:/Desktop/Bus_tracking/experiments/eda_silver_tier_comprehensive.py) & [`experiments/audit_vehicle_gps_stream_continuity.py`](file:///z:/Desktop/Bus_tracking/experiments/audit_vehicle_gps_stream_continuity.py).  
> **Ngày ban hành**: 07/11/2026  

---

## I. TỔNG HỢP SỐ LIỆU THỰC NGHIỆM TẦNG SILVER (SAU KHI KHÓA 48 TUYẾN CHUẨN)

1. **Quy mô dữ liệu chuẩn hóa (`2026-10-08` $\to$ `2026-11-07`)**:
   * **Tổng bản ghi Silver sạch ($d_\perp \le 35,0\text{m}$)**: **5.336.214 dòng** trên **48 tuyến chuẩn cụm HUST** (481 xe buýt), đồng bộ 1:1 giữa SQLite `route_projected_telemetry` (13 cột) và `data/lakehouse/silver/route_projected_telemetry/` (1.191 phân vùng Parquet).
   * **Tổng bản ghi sự cố TomTom khớp tuyến**: **836.761 dòng** trên **46/48 tuyến** có giao cắt sự cố đô thị (`fact_route_tomtom_incidents`).
   * **Đã loại bỏ vĩnh viễn**: 6 tuyến thử nghiệm 2 ngày đầu (`E07TC`, `35B`, `31`, `41`, `25`, `03A`), 5 bản ghi trôi thời gian ngày `2026-10-07`, và 100% các bước nhảy lùi giữa tuyến do nhiễu GPS/giao cắt vòng lặp.
2. **Đặc trưng chu kỳ phát tin ($\Delta t$) & bước nhảy không gian ($\Delta s$)**:
   * Chu kỳ giữa 2 bản tin liên tiếp cùng xe: Trung vị $P_{50} = \mathbf{80,0\text{s}}$ ($P_{25} = 60\text{s}$, $P_{75} = 90\text{s}$, $P_{90} = 105\text{s}$).
   * Khoảng cách giữa 2 trạm dừng liên tiếp trên mạng lưới: Trung vị $P_{50} = \mathbf{579,6\text{m}}$.
   * Quãng đường xe chạy giữa 2 bản tin liên tiếp ($\Delta s > 0$): Trung vị $P_{50} = \mathbf{384,1\text{m}}$, $P_{75} = \mathbf{572,8\text{m}}$, $P_{90} = \mathbf{792,0\text{m}}$.

---

## II. CHECKLIST 5 QUY TẮC BẮT BUỘC KHI XỬ LÝ QUỸ ĐẠO XE & TÍNH TOÁN ETA

Mọi thuật toán ở các giai đoạn tiếp theo (tách chuyến, tính ma trận thời gian di chuyển lịch sử, trích xuất đặc trưng và huấn luyện ETA) **BẮT BUỘC** phải tích hợp và pass đủ 5 checklist dưới đây:

### [ ] Checklist 1: Luật Ghép Chuyến Xuyên Qua Lỗ Thủng Detour / Mất Sóng Ngắn ($\Delta t > 300\text{s}$)
* **Bằng chứng thực nghiệm**: Trên dòng GPS cùng 1 xe và cùng 1 chiều (`direction`), có **26.158 lần** khoảng trống thời gian $300\text{s} < \Delta t \le 1800\text{s}$ (do xe đi vòng detour/cầu vượt bị cắt $d_\perp > 35\text{m}$ hoặc mất sóng 3G ngắn hạn), trong đó **22.006 lần (84,1%)** xe vẫn tiến về phía trước ($\Delta s > 100\text{m}$) trên cùng chuyến với vận tốc trung bình hợp lý $\bar{v} = \Delta s / \Delta t \in [3, 50]\text{ km/h}$.
* **Quy tắc bắt buộc**:
  * **CẤM** cắt chuyến mới chỉ dựa vào điều kiện đơn lẻ $\Delta t > 300\text{s}$.
  * Chỉ cắt sang `trip_id` mới khi xảy ra một trong 3 điều kiện vật lý:
    1. Đổi chiều hành trình (`direction[i] != direction[i-1]`), HOẶC
    2. Quay lùi không gian thực sự ($\Delta s = s_i - s_{i-1} < -200\text{m}$ — xe đã bắt đầu vòng chạy mới), HOẶC
    3. Ngắt quãng quá dài ($\Delta t > 1800\text{s}$ / 30 phút), hoặc $300\text{s} < \Delta t \le 1800\text{s}$ nhưng vận tốc trung bình qua khoảng trống nằm ngoài ngưỡng vật lý $[2, 60]\text{ km/h}$.

### [ ] Checklist 2: Luật Xử Lý Đầu Bến Cuối ($s \approx L$) — Cắt Đuôi "Treo Trạng Thái Chuyến Cũ"
* **Bằng chứng thực nghiệm**: Khi xe chạm bến cuối ($s \approx L$), thiết bị GPS trên xe **không đổi chiều ngay** mà giữ nguyên nhãn chiều cũ (`raw_dir` cũ) với $v \approx 0\text{ km/h}$ suốt 5–15 phút đỗ nghỉ trong bến.
* **Quy tắc bắt buộc**:
  * Thời điểm xe hoàn thành đoạn trạm cuối cùng của chuyến là **bản tin ĐẦU TIÊN** xe tiến vào vùng đích ($s \ge s_{\text{station\_last}} - 50\text{m}$).
  * **Cắt bỏ toàn bộ chuỗi bản tin đứng im ($\Delta s \approx 0, \bar{v} < 1\text{ km/h}$) ở phần đuôi của chuyến** tại vùng bến cuối, tuyệt đối không cộng thời gian xe đỗ nghỉ tại bến vào thời gian di chuyển của đoạn trạm cuối.

### [ ] Checklist 3: Luật Xử Lý Đầu Bến Xuất Phát ($s = 0$) — Xử Lý "Trễ Đổi Chiều"
* **Bằng chứng thực nghiệm**: Khi xe xuất bến chuyến mới, 77,9% số chuyến bị trễ cập nhật chiều (`raw_dir` chỉ lật sang chiều mới khi xe đã rời Trạm 0 được vài trăm mét, trung vị $P_{50}(s_{\text{start}}) = 410\text{m}$).
* **Quy tắc bắt buộc**:
  * **Tuyệt đối không ngoại suy ngược về Trạm 0** nếu bản tin đầu tiên của chuyến đã nằm ở $s_{\text{start}} > s_{\text{station\_0}}$.
  * Với mỗi chuyến xe, chỉ trích xuất thời gian di chuyển và mẫu huấn luyện ETA cho các trạm dừng nằm **từ vị trí bản tin mở đầu chuyến trở về sau** ($s_{\text{station}} \ge s_{\text{start}}$).
  * Nếu đầu chuyến có chuỗi bản tin đỗ chờ tại vạch xuất phát ($s \le 100\text{m}, \bar{v} < 1\text{ km/h}$), lấy **bản tin cuối cùng trước khi xe tăng tốc rời vùng $s \le 100\text{m}$** làm mốc bắt đầu lăn bánh.

### [ ] Checklist 4: Luật Xử Lý Nhảy Cóc Trạm Dừng ($\Delta \text{st} \ge 2$) & Cắt Đoạn Detour
* **Bằng chứng thực nghiệm**: Giữa 2 bản tin liên tiếp có **43,23%** bước đi qua 1 trạm ($\Delta \text{st} = +1$) và **6,53% (343.546 bước)** nhảy cóc qua $\ge 2$ trạm ($\Delta \text{st} \ge +2$). Ngoài ra, các đoạn xe đi detour bị cắt $d_\perp > 35\text{m}$ sẽ tạo ra khoảng trống $(\Delta t_{\text{gap}}, \Delta s_{\text{gap}})$ lớn giữa 2 bản tin trước và sau detour.
* **Quy tắc bắt buộc**:
  * **Nội suy thời điểm qua trạm $\hat{t}(s_k)$**: Khi trạm $k$ (tọa độ $s_k$) nằm giữa 2 bản tin liên tiếp $s_{i-1} \le s_k \le s_i$:
    $$\hat{t}(s_k) = t_{i-1} + \frac{s_k - s_{i-1}}{s_i - s_{i-1}}(t_i - t_{i-1})$$
  * **Điều kiện chặn chất lượng nội suy (Bracketing Guard)**:
    * **Đối với tính thời gian chạy từng cặp trạm liền kề $(k \to k+1)$ (Baseline Matrix)**: Chỉ nội suy thời điểm qua trạm $k$ nếu cặp bản tin kẹp hai đầu trạm thỏa mãn $\Delta t_i = t_i - t_{i-1} \le 150\text{s}$ và $\Delta s_i = s_i - s_{i-1} \le 1.000\text{m}$. Nếu trạm $k$ nằm lọt giữa một cú nhảy cóc lớn do detour/mất sóng ($\Delta t_i > 150\text{s}$ hoặc $\Delta s_i > 1.000\text{m}$), **bỏ qua không dùng bước nhảy đó để tính thời gian vi mô của cặp trạm đơn lẻ $(k \to k+1)$**, tránh san phẳng sai số.
    * **Đối với nhãn mục tiêu dự báo ETA đa trạm ($s_{\text{bus}} \to s_{\text{target}}$)**: Chỉ cần tại điểm đích $s_{\text{target}}$ có cặp bản tin kẹp chặt ($\Delta t_{\text{target}} \le 150\text{s}$), còn ở giữa hành trình dù xe có đi qua đoạn detour bị khuyết vài bản tin thì **tổng thời gian thực tế $\text{ETA}_{\text{actual}} = \hat{t}(s_{\text{target}}) - t_{\text{current}}$ vẫn hoàn toàn chính xác 100%** (vì đồng hồ thời gian thực ở điểm đầu $t_{\text{current}}$ và điểm đích $\hat{t}(s_{\text{target}})$ là bất biến!).

### [ ] Checklist 5: Phân Tách Vai Trò Dữ Liệu Huấn Luyện Lịch Sử vs. Dữ Liệu Live Serving
* **Dữ liệu lịch sử hiện tại (5,60 triệu pings, $\Delta t \approx 80\text{s}$)**: Đóng vai trò học phân phối thời gian di chuyển trên mạng lưới và quy luật tắc nghẽn theo không gian - thời gian.
* **Dữ liệu Live Service (giai đoạn triển khai thực tế)**: Khi áp dụng kỹ thuật truy vấn toàn tuyến trong 1 request để tăng tần suất lấy mẫu (ví dụ $\Delta t \approx 10\text{–}15\text{s}$), vị trí hiện tại $s_{\text{bus}}$ và vận tốc tức thời gần nhất $\bar{v}_{\text{recent}}$ lúc serving sẽ còn chính xác hơn nữa mà **hoàn toàn tương thích 100% với mô hình đã huấn luyện trên dữ liệu hiện tại**.

---

## III. CHECKLIST SỬA LỖI TỪNG BƯỚC & NGHIỆM THU ĐÓNG BĂNG MODULE 1 – MODULE 2 (ZERO-REGRESSION LEDGER)

Mọi thay đổi đối với phép chiếu Frenet và tầng lưu trữ Silver phải được thực hiện **từng bước một (Step-by-Step)**, có đo kiểm trước và sau mỗi bước để đảm bảo **không sửa 1 lỗi sinh ra 2 lỗi**:

| Thứ tự | Mã Lỗi & Hạng Mục Sửa Chữa | Số Liệu Lỗi Trước Khi Sửa (Baseline) | Kết Quả Nghiệm Thu Thực Nghiệm Sau Khi Sửa (48 Tuyến) | Trạng Thái |
| :---: | :--- | :--- | :--- | :---: |
| **Bước 1** | **Tập trung hóa toàn bộ Magic Numbers vào `config/system_config.py`** (Điều 4.2 Hiến pháp) | 14 hằng số vật lý/hình học hardcode rải rác (`45.0`, `35.0`, `20.0`, `-30.0`, `1500.0`, `25.0`, `300.0`, `80.0`, `2026-10-08`...) | 100% hằng số được import từ `config/system_config.py` trên toàn bộ `module_1` & `module_2`; thống nhất `MAX_CORRIDOR_CROSS_TRACK_M = 35.0` và `MAX_GPS_BACKWARD_JITTER_M = 20.0`. | ✅ **PASSED** |
| **Bước 2** | **Xóa bỏ cột tàn dư `is_dwell` khỏi SQLite Schema, Views & Parquet Exporter** | Cột `is_dwell` tồn tại trong `route_projected_telemetry`, `v_bus_to_next_station`, `v_active_fleet_summary`. | Schema bảng `route_projected_telemetry` còn đúng **13 cột** (`CLEAN - no is_dwell`); 2 SQL Views hoạt động bình thường. | ✅ **PASSED** |
| **Bước 3** | **Sửa lỗi `abs(ds)/dt` biến nhiễu giật lùi GPS ($-20\text{m} \le \Delta s < 0\text{m}$) thành vận tốc tiến dương** | **89.435 dòng** có $\Delta s < 0$ nhưng `derived_speed_kmh > 0` (`4.718` trên tuyến 01/02/05). | Thay `abs(ds)/dt` bằng `max(0.0, ds)/dt`. Kiểm định toàn mạng 48 tuyến: **0 dòng** (`[Defect 2] = 0`). | ✅ **PASSED** |
| **Bước 4** | **Sửa lỗi tính `derived_speed_kmh` trước khi lọc hành lang $d_\perp \le 35,0\text{m}$** | **44.349 dòng** hợp lệ bị mất vận tốc (`NULL`) do có 1 điểm nhiễu $d_\perp > 35\text{m}$ xen giữa (`1.190` trên tuyến 01/02/05). | Lọc giữ các điểm $d_\perp \le 35,0\text{m}$ trước rồi mới tính vận tốc dẫn xuất trên chuỗi điểm hợp lệ. Kiểm định toàn mạng 48 tuyến: **0 dòng** (`[Defect 3] = 0`). | ✅ **PASSED** |
| **Bước 5** | **Khóa chặt `Global Search Fallback` & Duyệt tuần tự thời gian có Gộp Chùm Chiều (`Direction Run Coalescing`)** | **11.219 bước** nhảy lùi giữa tuyến ($\Delta s < -20\text{m}$ trong $\Delta t \le 300\text{s}$) do `Global Search` không chặn lùi và cập nhật `prev_s` cả trên điểm ngoài hành lang. | (1) Chỉ cập nhật `prev_s` khi $d_\perp \le 35\text{m}$; (2) Gộp chùm nhiễu lật chiều ngắn hạn trong $\Delta t \le 300\text{s}$ và reset cửa sổ khi đổi chiều thật; (3) Trong $\Delta t \le 300\text{s}$ cùng chiều, chỉ cho phép nhảy lùi về đầu bến ($s_{\text{new}} \le 800\text{m}$) khi điểm trước ở cuối bến ($s_{\text{prev}} \ge L - 800\text{m}$). Kiểm định 48 tuyến: **0 bước nhảy lùi giữa tuyến** (`[Defect 4] = 0`). | ✅ **PASSED** |
| **Bước 6** | **Chạy lại toàn mạng 48 tuyến, Tái xuất Silver Parquet & Nghiệm thu Đóng băng Module 2** | `route_projected_telemetry` và Silver Parquet chứa 4 lỗi trên. | Đã chạy lại toàn mạng 48 tuyến (**5.336.214 dòng**, cân bằng `go = 49,78%` / `re = 50,22%`) $\to$ Xuất lại **1.191 phân vùng Silver Parquet** $\to$ Pass 100% cả 5 kiểm định Zero-Regression trên toàn bảng SQLite và Parquet. | ✅ **FROZEN** |
