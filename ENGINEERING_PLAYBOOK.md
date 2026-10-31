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

### Bẫy "Hai Nguồn Chân Lý" Giữa App Thương Mại (BusMap) vs Quản Lý Nhà Nước (TimBus)
- **Bản chất vấn đề**:
  - **Dữ liệu BusMap**: Có trường GPS real-time của xe, nhưng danh bạ trạm dừng và đường đi bị trễ hạn, không có tim đường hình học phân đoạn chính thức.
  - **Dữ liệu TimBus (TRAMOC / Sở GTVT Hà Nội)**: Có tọa độ WGS84 chuẩn của toàn bộ trạm dừng và chuỗi tọa độ tim đường chính thức, nhưng không cung cấp API GPS real-time công khai.
- **Giải pháp Crosswalk (Station & Route Matching)**:
  - Lấy TimBus làm **Master Ground Truth duy nhất** về không gian.
  - Khởi tạo bảng trung gian `dim_station_crosswalk` và `dim_route_crosswalk`:
    - Ánh xạ trạm bằng thuật toán lân cận không gian kết hợp điều kiện hướng:
      $$\text{Distance}(P_{\text{BusMap}}, P_{\text{TimBus}}) \le 50\text{m} \quad \text{AND} \quad \text{Direction}_{\text{BusMap}} == \text{Direction}_{\text{TimBus}}$$
  - **Bài học xương máu**: **BẮT BUỘC PHẢI KHỚP THEO CẢ HƯỚNG DI CHUYỂN (`go`/`return`)**. Nếu chỉ tìm trạm gần nhất theo cự ly Euclidean đơn thuần, thuật toán sẽ map nhầm sang trạm của chiều ngược lại ở phía đối diện đường đôi!

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
