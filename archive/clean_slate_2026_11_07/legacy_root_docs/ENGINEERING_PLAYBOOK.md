# SỔ TAY KỸ THUẬT & NHẬT KÝ THỰC CHIẾN (ENGINEERING PLAYBOOK & LOGS)
> **Bản nháp sống (Living Field Notes)**: Ghi chép nối tiếp các kinh nghiệm kỹ thuật, cạm bẫy công cụ và bài học xương máu trong quá trình phát triển hệ thống. Cấu trúc dạng nhật ký mở để tiếp nối liên tục ở cuối file khi phát sinh bài học mới, không dùng mục lục hình thức. Tách biệt hoàn toàn với `docs/` (nghiệp vụ giao thông).

---

## 1. KINH NGHIỆM CRAWLER 24/7 & HẠ TẦNG THU THẬP REAL-TIME

### Bẫy Rate Limit HTTP 429 & Bể Thiết Bị Ảo (Progressive Commuter Pool)
- **Cạm bẫy gặp phải**: Ban đầu, crawler dùng chung 1 Device ID hoặc hardcode 1 token để query API vị trí của ~500 xe buýt liên tục. Chỉ sau 10 - 15 phút, máy chủ BusMap chặn toàn bộ IP hoặc trả về HTTP 429 Too Many Requests.
- **Nguyên nhân**: Máy chủ backend của app xe buýt có cơ chế kiểm tra tần suất gọi trên mỗi `Device-ID`. Một người dùng thông thường không bao giờ query vị trí 500 xe buýt một lúc.
- **Giải pháp thực chiến**:
  - Xây dựng **Bể hành khách ảo tăng trưởng lũy tiến (Progressive Commuter Pool)** từ 300 lên 5.000 thiết bị:
    ```python
    MASTER_DEVICE_POOL = [
        hashlib.sha256(f"hust_commuter_device_{i:04d}".encode("utf-8")).hexdigest()[:16]
        for i in range(MAX_POOL_SIZE)
    ]
    ```
  - Cấp phát Device ID ngẫu nhiên cho từng micro-batch hoặc xoay vòng.
  - Tần suất mỗi Device ID ảo gọi lên server giảm xuống cực thấp ($< 1$ request/phút), triệt tiêu hoàn toàn mã lỗi 429 mà không cần proxy xoay IP tốn kém.

### Điều Phối Pacing & Micro-Batching (Chống Treo Socket)
- **Cạm bẫy**: Gửi đồng loạt 504 request cùng lúc (thông qua threading/async) làm nghẽn socket kết nối, timeout hàng loạt và tạo đỉnh tải (spike) dễ bị tường lửa chặn.
- **Giải pháp**:
  - Chia 504 xe thành **28 micro-batches (18 xe/batch)**.
  - Dãn cách giữa các batch bằng khoảng nghỉ nhỏ: `BUS_MICRO_BATCH_DELAY_SEC = 0.40s`.
  - Toàn bộ quá trình quét 504 xe hoàn tất trong ~30 giây, sau đó cho worker nghỉ 45 giây $\to$ Tạo chu kỳ quét chuẩn nhịp nhàng **75 giây/vòng** (`BUS_POLL_INTERVAL_SEC = 75`).
  - Toàn bộ worker chỉ dùng thư viện chuẩn Python (`urllib.request`, `json`, `socket`), không phụ thuộc `requests` hay `aiohttp` để đảm bảo chạy mượt trên mọi môi trường tối giản.

### GitHub Actions Runner: Giới Hạn 6 Giờ & Phao Cứu Sinh Cron Watchdog
- **Cạm bẫy**: GitHub Actions Runner miễn phí có giới hạn cứng: tự động tắt sau tối đa 6 giờ chạy liên tục (job timeout). Ngoài ra, nếu runner bị hủy giữa chừng do bảo trì, chuỗi tự đánh thức tiếp sức (`if: success() -> repository_dispatch`) sẽ bị đứt xích im lặng (Silent Chain Break), làm crawler dừng nhiều ngày không ai biết.
- **Giải pháp**:
  - **Chủ động ngắt phiên**: Giới hạn mỗi runner chỉ chạy đúng 9 phút (`SESSION_DURATION_SEC = 540`), sau đó tự trigger phiên runner mới qua GitHub API `POST /dispatches` để reset bộ đếm thời gian.
  - **Lắp phao cứu sinh Watchdog**: Trong file workflow `.github/workflows/crawl_bus.yml`, bắt buộc khai báo thêm lịch cron chạy ngầm mỗi 2 giờ:
    ```yaml
    on:
      schedule:
        - cron: '0 */2 * * *'
      repository_dispatch:
        types: [relay-next-crawler]
    ```
    Nếu xích tiếp sức chạy bình thường, cron chỉ đóng vai trò chạy đệm. Nếu xích đứt vì bất kỳ lý do gì, tối đa sau 2 giờ cron sẽ tự khởi động lại chuỗi runner.

### Đồng Bộ Dữ Liệu Lớn Lên Cloud (Hugging Face Datasets)
- **Kinh nghiệm**: Không lưu hàng triệu bản ghi raw trực tiếp vào Git repo (làm phình to `.git` và vi phạm giới hạn kích thước file của GitHub).
- **Giải pháp**:
  - Cào dữ liệu theo định dạng dòng nối tiếp JSON Lines (`.jsonl`), nén theo từng batch nhỏ theo ngày và khung giờ.
  - Cứ mỗi 10 phút, runner tự đồng bộ tệp JSONL mới nhất lên Hugging Face Dataset (`Toibinguz/hust-bus-data/raw_data/`) qua API token.
  - Git repository chỉ lưu trữ mã nguồn và các file metadata sức khỏe nhẹ (`tomtom_quota_tracker.json`, `daily_catalog_health.json`).

---

## 2. KINH NGHIỆM MERGE DỮ LIỆU BẢN ĐỒ & KHÔNG GIAN (GIS & SPATIAL PIPELINE)

### Bài Học "Hai Nguồn Chân Lý" & Thống Nhất BusMap Canonical Ground Truth
- **Bản chất vấn đề lịch sử**:
  - Trước đây, hệ thống cố gắng hòa trộn giữa telemetry thời gian thực của BusMap với danh bạ của TimBus thông qua bảng ánh xạ `dim_station_crosswalk`.
  - **Hệ quả**: Gây xung đột mã trạm, sai lệch cự ly và phức tạp hóa kiến trúc không cần thiết.
- **Giải pháp dứt khoát hiện tại**:
  - Đã loại bỏ hoàn toàn TimBus và bảng `dim_station_crosswalk`.
  - Thống nhất **BusMap Canonical Ground Truth** (`canonical_station_master`, `canonical_shape_master`, `canonical_route_master` với 176 tuyến, 13.301 trạm và 118.563 điểm tim đường) là Master Ground Truth duy nhất, đồng bộ 1:1 với telemetry GPS thời gian thực.

### Phép Chiếu Không Gian 1D Frenet & Xử Lý Đoạn Vòng Lặp (Looping Topology)
- **Bản chất**: Biến đổi tọa độ GPS 2D $(lat, lon)$ thành hệ tọa độ 1D dọc tim đường:
  - $s_{\text{bus}}$: Quãng đường tích lũy dọc tim đường tính từ đầu tuyến (mét).
  - $d_\perp$: Sai số trực giao vuông góc từ vị trí xe đến tim đường (mét).
- **Cạm bẫy cự ly WGS84**: Tuyệt đối không dùng khoảng cách hình học phẳng (Euclidean Cartesian $\sqrt{\Delta x^2 + \Delta y^2}$) trên kinh độ/vĩ độ thô vì $1^\circ$ kinh độ tại Hà Nội khác $1^\circ$ vĩ độ. Bắt buộc dùng công thức Haversine hoặc chiếu về hệ tọa độ UTM Zone 48N (EPSG:32648) để đơn vị luôn là mét chuẩn.
- **Cạm bẫy bước nhảy lùi ($\Delta s < -200\text{m}$)**:
  - Tuyến có vòng lặp (như Tuyến 56B): Nhánh đi và nhánh về cắt ngang nhau hoặc chạy song song cách nhau vài mét. Thuật toán tìm điểm gần nhất bị nhầm lẫn giữa 2 nhánh, khiến tọa độ $s$ bị giật lùi hàng km.
  - **Giải pháp**: Thiết lập **Ràng buộc Đơn điệu Không gian (Monotonicity Spatial Guard)**: Khi một xe đang di chuyển, điểm chiếu kế tiếp bắt buộc phải nằm trong khoảng hợp lý so với điểm trước:
    $$s_{\text{candidate}} \in [s_{\text{prev}} - 50\text{m}, s_{\text{prev}} + 1500\text{m}]$$
    Nếu điểm gần nhất nằm ngoài khoảng này, giữ nguyên đoạn tim đường hiện tại hoặc gắn cờ ngoại lai.

### Cạm Bẫy Bản Đồ Nền Tile: OpenStreetMap Standard vs CARTO vs OSM France
- **OSM Standard (`tile.openstreetmap.org`)**:
  - Có Tile Usage Policy cực kỳ nghiêm ngặt, **bắt buộc phải có `User-Agent` HTTP header**.
  - Nếu gọi từ browser/webview cục bộ không gửi custom header, máy chủ sẽ rate-limit hoặc chặn mã lỗi HTTP 403 Forbidden.
- **CARTO Basemap (CartoDB Positron)**:
  - Bản đồ nền CARTO Positron áp dụng thuật toán **đơn giản hóa hình học (Geometry Simplification / Generalization)** ở các mức zoom thấp và trung bình để tối ưu tốc độ render.
  - Hậu quả: Khi vẽ tim đường WGS84 chính xác lên nền CARTO, tim đường nhìn như bị trượt khỏi mặt đường trên ảnh tile, gây ngộ nhận là xe buýt chạy sai làn.
- **Giải pháp chuẩn xác - OSM France (`osm_fr`)**:
  - URL template: `https://{s}.tile.openstreetmap.fr/osmfr/{z}/{x}/{y}.png` (Subdomains: `abc`).
  - **Headerless 100%**: Hoạt động mượt mà trong Leaflet mà không bị chặn User-Agent.
  - **Keyless 100%**: Miễn phí, không cần API Key.
  - **Độ trung thực cao nhất**: Render trực tiếp từ vector OpenStreetMap gốc, không bị làm mịn/lệch nét đường.

---

## 3. KINH NGHIỆM MÔI TRƯỜNG PYTHON & WINDOWS RUNTIME

### Bẫy Xung Đột MSYS2 Path Masking
- **Hiện tượng**: Máy tính đã cài đầy đủ các thư viện nặng (`pandas`, `torch`, `xgboost`) trên Python chính, nhưng khi chạy lệnh qua terminal AI hoặc subprocess thì bị văng lỗi `No module named pip` hoặc thiếu thư viện.
- **Nguyên nhân**:
  - Trong biến môi trường `PATH`, thư mục `C:\msys64\ucrt64\bin` (chứa trình biên dịch GCC) có sẵn một binary `python.exe` trần trụi (Python 3.12 tối giản không có `pip`).
  - Khi sandbox hoặc terminal bị chặn quyền đọc thư mục người dùng `AppData\Local`, Windows tự động nhảy xuống thư mục tiếp theo trong PATH $\to$ Gọi trúng MSYS2 Python.
- **Giải pháp triệt để**:
  1. Đưa thư mục Python chính (VD: `C:\Users\<User>\AppData\Local\Python\pythoncore-3.14-64`) lên **đầu danh sách User PATH**.
  2. Đăng ký Python chuẩn **PEP 514** vào Windows Registry:
     ```powershell
     $baseKey = "HKCU:\Software\Python\PythonCore\3.14"
     New-Item -Path "$baseKey\InstallPath" -Force
     Set-ItemProperty -Path "$baseKey\InstallPath" -Name "ExecutablePath" -Value "C:\Users\<User>\AppData\Local\Python\pythoncore-3.14-64\python.exe"
     ```
  3. Lệnh `py` trên Windows sẽ nhận diện đúng phiên bản 3.14 làm mặc định toàn hệ thống.

### Chuẩn Tạo Virtual Environment Trên Windows
- Luôn tạo môi trường ảo bằng lệnh launcher chính thống kết hợp cờ kế thừa:
  ```powershell
  py -m venv .venv --system-site-packages
  ```
- **Lợi ích**: Tái sử dụng ngay lập tức toàn bộ kho thư viện khoa học dữ liệu ở máy chủ mà không phải tải lại, và file thực thi `.venv\Scripts\python.exe` nằm ngay trong workspace không bị sandbox chặn quyền.

### Lỗi Mã Hóa Tiếng Việt Trên Console Windows (CP1252)
- **Triệu chứng**: `UnicodeEncodeError: 'charmap' codec can't encode character...` khi in tên trạm xe buýt hoặc lộ trình tiếng Việt ra màn hình PowerShell.
- **Nguyên nhân**: Console Windows mặc định dùng bảng mã CP1252 (tiếng Anh) thay vì UTF-8.
- **Giải pháp**: Bắt buộc thêm cấu hình UTF-8 ở đầu các script Python độc lập:
  ```python
  import sys
  if sys.stdout.encoding != 'utf-8':
      try:
          sys.stdout.reconfigure(encoding='utf-8')
      except Exception:
          pass
  ```

---

## 4. KINH NGHIỆM CƠ SỞ DỮ LIỆU & QUẢN TRỊ DỮ LIỆU LỚN CỤC BỘ

### SQLite: Khóa Ghi Đơn (Single-Writer Lock) & Dọn Rác VACUUM
- SQLite là CSDL nhúng cực kỳ xuất sắc cho truy vấn phân tích đọc ($< 1\text{ ms}$ cho hàng triệu bản ghi), nhưng có cơ chế khóa cứng file khi ghi.
- **Quy tắc**:
  1. Tuyệt đối không mở nhiều tiến trình ghi đồng thời vào file `.db`.
  2. Khi drop bảng lớn (như xóa bảng tạm 285k rows), dung lượng file `.db` trên ổ đĩa **không tự động giảm** mà bị phân mảnh trang trống. Bắt buộc phải chạy câu lệnh `VACUUM;` để thu hồi đĩa thật.
  3. Mọi truy vấn phân tích phục vụ dự báo ETA phải có index bao phủ:
     ```sql
     CREATE INDEX IF NOT EXISTS idx_segment_matrix_lookup 
     ON agg_segment_travel_times (route_code, direction, time_window, day_type);
     ```

### Chiến Lược Thuật Toán: Đơn Giản Trước, Phức Tạp Sau
- **Bài học đắt giá**: Đừng bao giờ vội vàng triển khai Machine Learning (XGBoost, LightGBM, Deep Learning) khi ma trận thời gian thực nghiệm chưa được xây dựng hoàn chỉnh.
- **Ma trận Thời gian phân đoạn ($P_{50}$)** qua thuật toán Linear Station Crossing Interpolation chạy trong 4 giây, không cần GPU, miễn nhiễm với lỗi hội tụ mô hình và cung cấp baseline mỏ neo vững chắc cho toàn bộ 48 tuyến. Mọi cải tiến ML sau này chỉ đóng vai trò học phần dư ($\Delta t_{\text{ML}}$).

---

## 5. KINH NGHIỆM XUẤT BÁO CÁO HTML, BẢN ĐỒ LEAFLET & TRUY TÌM DỊ THƯỜNG (GIS REPORTING)

### Cạm Bẫy Cú Pháp LaTeX Trong Giao Diện Web (Lỗi Font & Ký Tự Lạ)
- **Hiện tượng**: Báo cáo HTML xuất hiện các chuỗi ký tự thô như `($\bar{V} < 5\text{ km/h}$)`, `($d_\perp > 50\text{m}$)`, `($\Delta s < -200\text{m}$)`, khiến người dùng tưởng là lỗi font hoặc vỡ bảng mã.
- **Nguyên nhân**: Trình duyệt web thông thường chỉ render HTML/CSS, hoàn toàn không có bộ phân giải LaTeX tích hợp. Nếu không nạp thư viện KaTeX hay MathJax, toàn bộ công thức toán học sẽ bị in trần trụi dạng mã nguồn.
- **Giải pháp**:
  1. **Chuẩn hóa Typography Web**: Sử dụng ký tự Unicode trực tiếp và thẻ HTML thuần túy:
     - Dùng `V̄ < 5 km/h` hoặc `V_tb < 5 km/h` thay cho `$\bar{V} < 5\text{ km/h}$`.
     - Dùng `d<sub>⊥</sub> > 50m` thay cho `$d_\perp > 50\text{m}$`.
     - Dùng `Δs < -200m` thay cho `$\Delta s < -200\text{m}$`.
     - Dùng `≤ 15m` thay cho `$\le 15\text{m}$`, `P₅₀` thay cho `$P_{50}$`.
  2. Nạp thêm thư viện KaTeX qua CDN (`katex.min.css`, `katex.min.js`) vào `<head>` làm lưới an toàn nếu cần hiển thị biểu thức toán phức tạp.

### Cú Pháp Python f-string Làm Sập Toàn Bộ JavaScript (Lỗi Bản Đồ Không Hiển Thị)
- **Hiện tượng**: Mở file HTML báo cáo thì thấy bản đồ Leaflet không hiển thị với mọi máy chủ tile, màn hình trắng trơn hoặc bản đồ đứng im.
- **Nguyên nhân cốt lõi**:
  - Khi sinh HTML bằng Python f-string `rf"""..."""`, lập trình viên vô tình viết cú pháp định dạng số của Python vào trong template literal của JavaScript:
    ```javascript
    // Trong file Python:
    document.getElementById('stats').innerHTML = `Tổng ${{data.total_pings_in_db:,}} pings`;
    // Ra file HTML sinh ra:
    document.getElementById('stats').innerHTML = `Tổng ${data.total_pings_in_db:,} pings`;
    ```
  - Trong JavaScript, `${data.total_pings_in_db:,}` là **lỗi cú pháp chí mạng (Uncaught SyntaxError: Unexpected token ',')**.
  - Khi trình duyệt gặp lỗi cú pháp này, nó **ngừng thực thi toàn bộ thẻ `<script>`**, khiến toàn bộ lệnh khởi tạo bản đồ Leaflet, Chart.js và event listener đều bị tê liệt hoàn toàn!
- **Giải pháp**:
  - Trong JavaScript, bắt buộc dùng hàm chuẩn `Number.prototype.toLocaleString()`:
    ```javascript
    document.getElementById('stats').innerHTML = `Tổng ${data.total_pings_in_db.toLocaleString()} pings`;
    ```
  - Thêm `window.addEventListener('load', () => setTimeout(() => map.invalidateSize(), 300));` để đảm bảo Leaflet tính toán chính xác kích thước container sau khi DOM và CSS hoàn tất dàn trang.

### Thiết Kế Bộ Điều Hướng Dị Thường Không Gian - Thời Gian (Spatial-Temporal Navigator)
- **Bài toán**: Với hàng trăm ngàn điểm GPS trên một tuyến đường dài 20 - 40km, người dùng không thể tự mò mẫm tìm điểm xe đi lệch 155m hoặc điểm nhảy lùi tọa độ.
- **Kiến trúc giải pháp**:
  - **Tách lọc sự kiện thực nghiệm từ Python**: Trích xuất các danh sách ngoại lai nghiêm trọng nhất per-route:
    1. Lệch tim đường $d_\perp > 50\text{m}$ (Detour / sai làn).
    2. Bước nhảy lùi $\Delta s < -200\text{m}$ (Nghi vấn nhầm chiều hoặc vòng lặp).
    3. Nút nghẽn giao thông cực đoan $V < 5\text{ km/h}$ và siêu tốc $V > 60\text{ km/h}$.
  - **Cơ chế nhảy nhanh tương tác (Quick-Jump & FlyTo)**:
    - Cung cấp bảng sự kiện có nút `[Bay Tới Điểm]`.
    - Khi bấm, thực thi `map.flyTo([lat, lon], 17, { duration: 1.2 })`.
    - Đặt một điểm định vị động có hiệu ứng sóng xung kích lan tỏa (`pulse-beacon-ring` CSS keyframe animation) ngay tại tọa độ mục tiêu.
    - Tự động mở popup hiển thị toàn bộ hồ sơ thực nghiệm (Biển số xe, ID, Vận tốc, Sai số $d_\perp$, Vị trí 1D $s$, Timestamp chính xác).



---

## 6. KINH NGHIỆM CHIẾU FRENET & BẪY QUY ƯỚC CHIỀU DI CHUYỂN (DIRECTIONALITY)

### Bẫy Quy Ước Chiều `direction IN (0, 1)` vs `-1`
- **Hiện tượng**: Bảng `route_projected_telemetry` sau khi chạy xong chỉ có đúng 285.621 bản ghi, và 100% bản ghi đều mang nhãn hướng `go`. Toàn bộ dữ liệu chiều về (`re`) biến mất không dấu vết dù bảng dữ liệu thô `vehicle_unique_pings` có tới 663.342 pings.
- **Nguyên nhân cốt lõi**:
  - Trong logic truy vấn SQL của `multi_route_projector.py`, lập trình viên viết:
    ```sql
    WHERE route_id = ? AND direction IN (0, 1)
    ```
  - Tuy nhiên, trong cơ sở dữ liệu cào thực tế từ BusMap:
    - Chiều đi (Outbound / Go) được đánh số là `1`.
    - Chiều về (Inbound / Return) được đánh số là **`-1`** (hoàn toàn không có số `0`!).
  - Câu lệnh `IN (0, 1)` đã âm thầm lọc bỏ toàn bộ **375.901 pings chiều về**, làm mất 56.7% dữ liệu của toàn bộ 48 tuyến!
- **Giải pháp**:
  - Đổi câu truy vấn thành:
    ```sql
    WHERE route_id = ? AND direction IN (-1, 1)
    ```
  - Ánh xạ nhãn hướng nhất quán:
    ```python
    d_str = "go" if p[5] == 1 else "re"
    ```
  - Kết quả: Tổng số ping được định vị không gian 1D Frenet vọt lên **646.823 pings**, phủ trọn vẹn cả 2 chiều đi và về cho tất cả 48 tuyến.

---

## 7. KINH NGHIỆM LỌC NGOẠI LAI THỰC ĐỊA: BÃI ĐỖ GARA & LỆCH TOUR

### Bẫy Xe Đỗ Chết Gara Làm Biến Dạng Thống Kê Bám Làn ($d_\perp$)
- **Hiện tượng**: Tuyến 39 có tỷ lệ bám làn chỉ đạt 39.9% và sai số trung vị $d_\perp$ vọt lên tới 131m (nghi ngờ lỗi tim đường nghiêm trọng).
- **Nguyên nhân khi đào sâu dữ liệu**:
  - Tuyến có 2 xe buýt mang biển số `29B19755` và `29B20953`. Hai xe này nằm im tại xưởng sửa chữa/gara ở huyện Thanh Trì suốt 24 giờ.
  - Thiết bị GPS trên xe vẫn gửi định vị liên tục, sinh ra **2.336 pings** (chiếm 51.6% tổng dữ liệu của tuyến).
  - Thuật toán cố ép các điểm này vào tim đường cách đó hàng trăm mét, kéo tụt toàn bộ chỉ số chất lượng của tuyến.
- **Giải pháp**:
  - Đo biên độ dịch chuyển không gian cả ngày của từng phương tiện:
    $$\Delta s_{\text{day}} = \max(s_{\text{bus}}) - \min(s_{\text{bus}})$$
  - Nếu $\Delta s_{\text{day}} < 1.000\text{ m}$ và số ping $> 50$, xe được xác định là nằm trong xưởng/bãi đỗ $\to$ Gắn nhãn `depot_garage_parked` và loại bỏ khỏi tập tính toán vận tốc vận hành.
  - Tương tự, tại các bến đầu/cuối ($s < 300\text{m}$ hoặc $s > S_{\max} - 300\text{m}$), nếu vận tốc $V < 5\text{ km/h}$ thì phân loại là `terminal_dwell`.

### Bẫy Tour Tuyến Chậm Cập Nhật Giữa Nhà Nước vs Thực Địa (Case E04 & OSM Cross-check)
- **Bài học xương máu**: Master Ground Truth của nhà nước (TimBus) có thể bị chậm cập nhật khi luồng giao thông thực tế được điều chỉnh.
  - Điển hình: Tuyến E04 trên TimBus đi vòng Dương Nội - Lê Trọng Tấn, nhưng ngoài thực địa xe chạy thẳng theo trục Vạn Phúc - Chu Văn An - Quang Trung (độ lệch lên tới 2.5 km).
- **Giải pháp tự động**:
  - Dùng thuật toán kiểm tra cự ly đa giác giữa TimBus và OpenStreetMap (`hanoi_all_bus_routes_raw.json`).
  - Nếu khoảng cách tối đa giữa TimBus và OSM vượt quá $250\text{m}$, lập tức gắn cờ cảnh báo `TIER_3_FLAGGED` (Tour Mismatch).
  - **Quy tắc vàng**: Chỉ đưa vào tập huấn luyện Pilot các tuyến thuộc `TIER_1_GOLD` (độ lệch TimBus vs OSM $\le 15\text{m}$ và tỷ lệ bám làn thực tế $\ge 90\%$).

---

## 8. KINH NGHIỆM THỰC THI PYTHON MODULE TRÊN WINDOWS POWERSHELL

### Tránh Lỗi `ModuleNotFoundError: No module named 'config'` Khi Chạy Script Sâu
- **Cạm bẫy**: Khi chạy trực tiếp file script nằm sâu trong thư mục con:
  ```powershell
  python module_1_data_ingestion_and_preprocessing/step_1_4_frenet_spatial_projection/multi_route_projector.py
  ```
  Python sẽ tự động đặt `sys.path[0]` là thư mục chứa script đó, dẫn đến không tìm thấy gói `config` ở thư mục gốc của dự án.
- **Giải pháp tối ưu**:
  1. Sử dụng cú pháp chạy dạng module với cờ `-m` từ thư mục gốc của dự án:
     ```powershell
     .\.venv\Scripts\python.exe -m module_1_data_ingestion_and_preprocessing.step_1_4_frenet_spatial_projection.multi_route_projector
     ```
     Cú pháp này đảm bảo Python luôn đưa thư mục làm việc hiện tại (`.`) vào đầu danh sách `sys.path`.
  2. Không lạm dụng việc set biến môi trường `$env:PYTHONPATH='.'` trong chuỗi lệnh PowerShell vì ký tự `$` và dấu nháy có thể bị parser của shell phân giải sai hoặc chặn ký tự.


---

## 9. ĐỘNG HỌC THỰC CHIẾN: BÓC TÁCH XE CHẠY THẬT (ACTIVE RUNNING) VS NGHỈ GIỮA TUYẾN & ĐỖ ĐÊM (22:00 - 06:00)

### Cạm Bẫy Đánh Đồng Dữ Liệu GPS Khi Xe Đỗ Nghỉ
- **Hiện tượng**: Tuyến BRT01 và Tuyến 39 ban đầu có tỷ lệ bám làn rất thấp (BRT01 chỉ đạt 55%, Tuyến 39 chỉ đạt 39.9%), làm dấy lên nghi ngờ tim đường bị vẽ sai lệch nghiêm trọng.
- **Bản chất khi phân tích động học không gian - thời gian**:
  - Thiết bị GPS trên xe buýt không tắt khi xe dừng hoạt động.
  - Ban đêm (từ 21:45 đến 05:15 sáng hôm sau) và các giờ chuyển ca ban ngày, hàng loạt xe dừng tại bãi đỗ/gara/xưởng tập trung nằm cách tuyến từ 100m đến hơn 3.6km (ví dụ: bãi xe Kim Mã, Yên Nghĩa, Thanh Trì, Mai Dịch).
  - Các xe này vẫn liên tục gửi tọa độ GPS về hệ thống. Thuật toán cố chiếu các điểm nằm ngoài thực địa này lên tim đường, sinh ra hàng ngàn điểm có sai số $d_\perp > 100\text{m} - 3.700\text{m}$, làm "bẩn" hoàn toàn phân phối thống kê bám làn.
  - Ngoài bến đầu/cuối, xe buýt còn có các điểm dừng nghỉ giữa tuyến (nghỉ ăn trưa, dừng kỹ thuật, đổi ca tài xế) kéo dài hàng chục phút tại các vị trí $s$ trung gian.

### Giải Pháp Phân Tách Trạng Thái Động Học 3 Tầng (3-State Kinematic Filter)
- Không dựa vào cảm biến vận tốc tức thời thô (`speed == 0`), mà áp dụng vận tốc dẫn xuất không gian - thời gian ($\bar{v} = \Delta s / \Delta t$) và độ dịch chuyển trong cửa sổ trượt 3.5 phút ($[t - 105\text{s}, t + 105\text{s}]$):
  1. **Trạng thái Đỗ Đêm (`NIGHT_PARK`)**: Pings trong khung giờ 21:45 đến 05:15 có độ dịch chuyển $\Delta s_{210\text{s}} < 40\text{m}$ hoặc vận tốc dẫn xuất $V < 8\text{ km/h}$.
  2. **Trạng thái Dừng Nghỉ Kéo Dài / Bãi Đỗ Ban Ngày (`INTERMEDIATE_OR_DEPOT_LAYOVER`)**: Pings ban ngày (05:15 - 21:45) đứng yên trong phạm vi $\Delta s_{210\text{s}} < 25\text{m}$ liên tục $> 3$ phút và $V < 5\text{ km/h}$. (Các trạm dừng đón trả khách thông thường chỉ kéo dài 15-45 giây nên độ dịch chuyển 3.5 phút luôn $> 50\text{m}$).
  3. **Trạng thái Vận Hành Thực Sự (`ACTIVE_RUNNING`)**: Xe đang di chuyển trên tuyến ($\Delta s \ge 25\text{m}$ hoặc $V \ge 5\text{ km/h}$ trong giờ vận hành).

### Kết Quả Thực Nghiệm Bóc Tách Toàn Mạng Lưới (646.823 Pings - 48 Tuyến)
- **Cơ cấu trạng thái đội xe**:
  - **Xe Chạy Thực Sự (`ACTIVE_RUNNING`)**: **500.174 pings (77.3%)**.
  - **Dừng Nghỉ Ban Ngày (`DAY_LAYOVER`)**: **138.126 pings (21.4%)**.
  - **Đỗ Nghỉ Qua Đêm (`NIGHT_PARK`)**: **8.523 pings (1.3%)**.
- **Chỉ số bám làn thực tế khi bóc tách**:
  - Tuyến BRT01: Tỷ lệ bám làn vọt từ 55% lên **89.7%**, sai số trung vị chỉ **9.4 mét**!
  - Tuyến 22A, 02: Tỷ lệ bám làn đạt **97.0% - 97.4%**, sai số trung vị chỉ **5.3m - 5.5 mét**!
  - Tuyến E06: Tỷ lệ bám làn đạt **95.9%**, sai số trung vị chỉ **4.6 mét**!
  - **36 Tuyến đạt chuẩn GOLD** (Bám làn $\ge 88.0\%$, trung vị $d_\perp \le 10\text{m}$).
  - **10 Tuyến đạt chuẩn SILVER** (Bám làn $75\% - 88\%$, trung vị $d_\perp \le 15\text{m}$).
  - **Chỉ 2 Tuyến xếp BRONZE** (Tuyến 39 do lệch tour một nhánh, Tuyến E11 chỉ có 16 pings do mới thử nghiệm).
- **Kết luận**: Master Ground Truth từ BusMap hoàn toàn chính xác và đạt chuẩn thương mại. Việc bóc tách động học đã giải quyết triệt để vấn đề nhiễu layover và mở đường hoàn tất Module 1 để chuyển sang Module 2.


---

## 10. KHOA HỌC HÓA WORKSPACE & QUẢN TRỊ CẤU TRÚC DỰ ÁN

### Bối Cảnh Sau Khi Hoàn Thành Module 1
- Sau quá trình thử nghiệm bóc tách BusMap và chạy nhiều vòng kiểm toán, các thư mục rác xuất hiện ở root (`hanoi_bus_data/`, `latex/`), các tệp database cũ chiếm hàng trăm megabyte (`telemetry_audit_2026_10_17_18.db` 529MB), và thư mục `experiments/` bị phân mảnh bởi nhiều đợt thăm dò ad-hoc.
- **Nguyên tắc bất biến**: Không can thiệp vào các biến môi trường và tệp token đang được gọi trực tiếp bởi các script crawler (`access_token_hf.txt`) để tránh tạo ra các lỗi ngầm không đáng có.

### Các Bước Chuẩn Hóa Đã Thực Hiện
1. **Dữ liệu BusMap Native**: Di chuyển từ `hanoi_bus_data/` về đúng cây dữ liệu chuẩn `data/ground_truth/busmap_canonical/`, xóa các tệp rỗng 2 bytes (`routes.json`, `stations.json`). Cập nhật `ingest_busmap_canonical.py` để trỏ vào đường dẫn mới.
2. **Tài liệu học thuật**: Di chuyển `latex/` vào `docs/academic_proposal/` nhằm tập trung toàn bộ tài liệu dự án trong `docs/`.
3. **Giải phóng không gian đĩa**: Di chuyển snapshot database cũ `telemetry_audit_2026_10_17_18.db` (529.4 MB) vào `archive/legacy_dumps/`, chỉ giữ `data/hanoi_bus_system.db` (619 MB) làm Single Source of Truth cho dữ liệu vận hành.
4. **Hợp nhất báo cáo trực quan**: Chuyển `data/visualizations/*.html` vào thư mục `reports/`.
5. **Gom gọn Experiments**: Chuyển 6 thư mục thử nghiệm ad-hoc cũ vào `archive/legacy_experiments/`, giữ cho `experiments/` chỉ tập trung vào đợt kiểm toán hiện tại (`route_cleanliness_audit/`).
6. **Kiểm thử hồi quy**: Chạy thành công `verify_canonical_architecture.py` đạt 100% kiểm tra hợp lệ, không gây đứt gãy bất kỳ đường dẫn nào.


---

## 11. DỌN DẸP & ĐỒNG BỘ SCRIPTS TOÀN BỘ CÁC MODULE (QUÁN TÍNH CŨ & BẪY LOGIC)

### Cạm Bẫy Quán Tính Cũ Trong Các Scripts Đã Bị Bóc Mẽ
1. **Bẫy Chiều Xe `direction == -1` trong `telemetry_sanitizer.py` & `catalog_refresher.py`**:
   - Trong code cũ: `if direction == -1 and raw_speed == 0: status = "DEPOT"`.
   - **Tác hại**: Giao thức BusMap quy định `direction: 1` là chiều đi (`go`), và **`-1` là chiều về (`re`)**. Một xe buýt đang chạy chiều về dừng đèn đỏ (`raw_speed == 0`) hoặc chưa gán trạm bị đánh đồng là xe đỗ chết bãi (`IDLE_DEPOT`), làm sai lệch thống kê đội xe và vi phạm trực tiếp **Điều 5 Hiến pháp**.
   - **Đã khắc phục**: Chỉ phân loại xe `IDLE_DEPOT` khi `direction == 0` (không gán hướng) hoặc `route_id <= 0` và vận tốc dẫn xuất/làm mịn bằng 0 (`smoothed_speed == 0.0`).
2. **Bẫy Thứ Tự `sys.path.insert` trong `lakehouse_exporter.py`, `feature_extractor.py`, `train_eta_model.py`**:
   - Các file này ban đầu đặt lệnh `from config.system_config import ...` tại dòng 14, trong khi `sys.path.insert(0, ...)` lại đặt ở tận dòng 21 - 24.
   - Khi chạy script từ thư mục con, Python báo lỗi chí mạng: `ModuleNotFoundError: No module named 'config'`.
   - **Đã khắc phục**: Đưa `sys.path.insert` lên đầu toàn bộ file trước mọi câu lệnh import nội bộ.
3. **Bẫy Nguồn Dữ Liệu Trạm Cũ (`dim_station_crosswalk` vs `canonical_station_master`)**:
   - Các file `db_manager.py` (tạo view `v_bus_to_next_station`) và `baseline_segment_average.py` (tính ma trận thời gian chạy) ban đầu vẫn kết nối vào bảng cũ `dim_station_crosswalk` (chỉ có 3.646 trạm của TimBus trước đây).
   - **Đã nâng cấp**: Trỏ trực tiếp vào `canonical_station_master` (13.301 trạm dừng chuẩn của 176 tuyến). Kết quả sinh ra **27.872 ô ma trận thời gian liên trạm** cho toàn mạng lưới.
4. **Bổ sung Script Facade Chuẩn**:
   - Thêm `scripts/ingest_canonical_busmap_master.py` làm đầu vào chuẩn tắc đại diện cho luồng di chuyển dữ liệu BusMap Native.
5. **Kỷ luật kiểm thử Live Crawler**:
   - Sau toàn bộ các chỉnh sửa trên, crawler thực địa được kiểm tra trực tiếp qua cả 2 kênh: `cloud_crawler_step.py --test` (504/504 xe, 7.9s) và `run_production_crawler.py --test` (504 xe, 14.2s), xác nhận 100% hệ sinh thái vận hành thông suốt.

---

## 12. CHÍNH SÁCH QUỸ ĐẠO: DEADHEADING, DETOUR NÉ TẮC VÀ MÁY TRẠNG THÁI TÁI NHẬP TUYẾN (DOC 54)

### 1. Bản Chất Nghiệp Vụ Vận Hành
- **Deadheading (Chạy rỗng tiếp vận)**: Sáng sớm (04:30 - 05:45) xuất phát từ gara ra trạm giữa tuyến để phân bổ sức chứa; tối muộn (21:30 - 23:00) chạy tắt về bãi đỗ/gara để kết ca.
- **Detour Né Tắc (Ad-hoc Avoidance)**: Tài xế chủ động/theo điều độ rẽ nhánh sang đường gom, phố phụ né điểm nghẽn và có thể bỏ qua trạm dừng.
- **Biến dạng toán học Frenet**: Ép chiếu trực giao khi $d_\perp > 45\text{m}$ (đặc biệt $d_\perp > 1\text{km}$) sinh ra vận tốc chiếu ảo $\bar{v} > 168\text{km/h}$ do hình chiếu $s$ bị giật dọc theo tim đường.

### 2. Chiến Lược 2 Tầng (Bifurcated Policy)
1. **Tầng Huấn Luyện & Lakehouse (Module 2 & Baseline)**:
   - **LOẠI BỎ TRIỆT ĐỂ** các pings/phân đoạn có $d_\perp > 45\text{m}$ hoặc deadheading khỏi ma trận thời gian chạy và tập huấn luyện XGBoost. Chỉ dùng dữ liệu vàng `ST_ACTIVE_REVENUE` ($d_\perp \le 35\text{m}$).
2. **Tầng Phục Vụ Trực Tiếp (Online Serving SLA)**:
   - **Xe Deadhead**: Ẩn hoàn toàn khỏi app hành khách (tránh lỗi "Xe Ma").
   - **Xe Detour**: Gắn cờ `DETOUR_ALERT`, đóng băng ETA tại các trạm bị bỏ qua.
   - **Khử giật Tái Nhập Tuyến (Re-entry Gate)**: Yêu cầu tối thiểu $K = 2$ pings liên tiếp có $d_\perp \le 25\text{m}$ và cùng chiều tim đường mới kích hoạt lại ETA từ trạm $S_{\text{next}}$ tiếp theo.
- **Chi tiết đặc tả**: Xem [`docs/54_DEADHEADING_DETOUR_AND_ANOMALOUS_TRAJECTORY_ETA_POLICY.md`](docs/54_DEADHEADING_DETOUR_AND_ANOMALOUS_TRAJECTORY_ETA_POLICY.md).

