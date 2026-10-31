# CẨM NANG KỸ THUẬT & BÀI HỌC CÔNG CỤ (ENGINEERING & TOOLING PLAYBOOK)
> **Phạm vi**: Ghi chép và chuẩn hóa toàn bộ bài học kinh nghiệm về công cụ, môi trường thực thi, hạ tầng dữ liệu và GIS.  
> **Mục đích**: Tách biệt hoàn toàn với thư mục `docs/` (vốn dành cho phân tích bài toán nghiệp vụ xe buýt Hà Nội). Tài liệu này lưu trữ các giải pháp kỹ thuật nền tảng để tránh lặp lại sai lầm và tái sử dụng cho mọi dự án tương lai.

---

## MỤC LỤC
1. [Chương 1: Quản Trị Môi Trường Python Trên Windows](#chương-1-quản-trị-môi-trường-python-trên-windows)
2. [Chương 2: Hạ Tầng Bản Đồ & Máy Chủ Map Tile](#chương-2-hạ-tầng-bản-đồ--máy-chủ-map-tile)
3. [Chương 3: Cơ Sở Dữ Liệu Cục Bộ (SQLite & Columnar Parquet)](#chương-3-cơ-sở-dữ-liệu-cục-bộ-sqlite--columnar-parquet)
4. [Chương 4: Tự Động Hóa Đám Mây 24/7 (GitHub Actions Watchdog)](#chương-4-tự-động-hóa-đám-mây-247-github-actions-watchdog)
5. [Chương 5: Phân Quyền Sandbox & Ranh Giới Thực Thi](#chương-5-phân-quyền-sandbox--ranh-giới-thực-thi)
6. [Chương 6: Chuẩn Hóa Encoding Tiếng Việt Trên Windows](#chương-6-chuẩn-hóa-encoding-tiếng-việt-trên-windows)

---

## CHƯƠNG 1: QUẢN TRỊ MÔI TRƯỜNG PYTHON TRÊN WINDOWS

### 1.1. Hiện tượng "Lạc Môi Trường" (MSYS2 Path Masking)
- **Triệu chứng**: Máy đã cài đầy đủ `pandas`, `torch`, `xgboost` nhưng khi script chạy (hoặc terminal AI/IDE gọi lệnh) lại báo `ModuleNotFoundError: No module named pip` hoặc thiếu thư viện.
- **Nguyên nhân gốc rễ**: 
  - Trong biến môi trường `PATH`, thư mục `C:\msys64\ucrt64\bin` (chứa các công cụ GCC/C++) có sẵn một binary `python.exe` trần trụi (Python 3.12 của MSYS2 không kèm `pip`).
  - Bản Python chính của người dùng cài qua winget/user-level nằm tại `AppData\Local\Python` bị hạn chế quyền hoặc nằm sau MSYS2 trong `PATH`.
- **Giải pháp triệt để**:
  1. Đưa thư mục Python chính (VD: `C:\Users\<User>\AppData\Local\Python\pythoncore-3.14-64`) lên **vị trí đầu tiên** của User `PATH`.
  2. Đăng ký Python chuẩn **PEP 514** vào Windows Registry:
     ```powershell
     $baseKey = "HKCU:\Software\Python\PythonCore\3.14"
     New-Item -Path "$baseKey\InstallPath" -Force
     Set-ItemProperty -Path "$baseKey\InstallPath" -Name "ExecutablePath" -Value "C:\Users\<User>\AppData\Local\Python\pythoncore-3.14-64\python.exe"
     ```
  3. Sau khi đăng ký, launcher chuẩn Windows `py -0p` sẽ nhận diện Python 3.14 làm mặc định toàn hệ thống.

### 1.2. Chuẩn Khởi Tạo Virtual Environment (`.venv`)
- Luôn sử dụng lệnh `py` với cờ kế thừa thư viện hệ thống:
  ```powershell
  py -m venv .venv --system-site-packages
  ```
- **Lợi ích**: Tái sử dụng ngay 100% các gói nặng (PyTorch CUDA, PySpark, GeoPandas, XGBoost) đã cài ở môi trường gốc mà không mất thời gian và dung lượng tải lại.
- Bắt buộc khai báo `.venv/` trong `.gitignore`.

---

## CHƯƠNG 2: HẠ TẦNG BẢN ĐỒ & MÁY CHỦ MAP TILE

### 2.1. Cạm Bẫy Của OpenStreetMap Standard (`tile.openstreetmap.org`)
- **Vấn đề**: OSM.org có chính sách Tile Usage Policy cực kỳ nghiêm ngặt:
  - Bắt buộc phải có `User-Agent` HTTP header hợp lệ.
  - Chặn hoặc rate-limit gắt gao các truy vấn không có header (Headerless) từ webview, iframe hoặc script kiểm thử cục bộ.
- **Hậu quả**: Bản đồ hiển thị các ô xám hoặc lỗi HTTP 403 Forbidden.

### 2.2. Sự Sai Lệch Hình Học Của CARTO Basemaps (CartoDB Positron)
- **Vấn đề**: Các basemap thương mại miễn phí như CARTO Positron áp dụng thuật toán làm đơn giản hóa hình học đường sá (Geometry Simplification / Generalization) ở các mức zoom trung bình và thấp.
- **Hậu quả**: Khi vẽ tim đường WGS84 chuẩn của cơ quan quản lý (TimBus) hoặc các điểm GPS thực tế lên nền CARTO, ta có thể thấy đường xe chạy bị lệch nhẹ khỏi mặt đường trên ảnh tile, gây ngộ nhận là xe chạy sai làn.

### 2.3. Giải Pháp Tối Ưu: Máy Chủ OpenStreetMap France (`osm_fr`)
- **Tọa độ Tile Server**:
  `https://{s}.tile.openstreetmap.fr/osmfr/{z}/{x}/{y}.png` (Subdomains: `abc`)
- **Đặc tính vượt trội**:
  - **Headerless 100%**: Hoạt động mượt mà trong Leaflet/Mapbox/HTML mà không bị chặn User-Agent.
  - **Keyless 100%**: Không cần đăng ký tài khoản hay API Key.
  - **Độ trung thực cao nhất**: Dữ liệu render trực tiếp từ dữ liệu vector OpenStreetMap gốc, không bị làm mịn/đơn giản hóa như CARTO.
- **Cấu hình tập trung**: Được quản lý qua `config/system_config.py` với `DEFAULT_TILE_SERVER = "osm_fr"`.

---

## CHƯƠNG 3: CƠ SỞ DỮ LIỆU CỤC BỘ (SQLITE & COLUMNAR PARQUET)

### 3.1. Kỷ Luật Schema và Single-Writer trong SQLite
- SQLite là CSDL Serverless cực nhanh cho đọc ($< 1\text{ ms}$), nhưng khóa toàn bộ tệp khi ghi (Single-Writer Lock).
- **Quy tắc**:
  1. Chỉ một tiến trình ghi dữ liệu tại một thời điểm; tránh mở nhiều tiến trình song song ghi vào cùng file `.db`.
  2. Bắt buộc tạo Index theo bộ khóa truy vấn:
     ```sql
     CREATE INDEX IF NOT EXISTS idx_segment_matrix_lookup 
     ON agg_segment_travel_times (route_code, direction, time_window, day_type);
     ```
  3. Sau khi drop các bảng lớn hoặc import hàng loạt, bắt buộc chạy lệnh `VACUUM;` để thu hồi các trang đĩa bị phân mảnh và giảm dung lượng file vật lý.

### 3.2. Chống Bẫy Lặp Không Gian 1D (Looping Polyline Ambiguity)
- **Vấn đề**: Khi một tuyến xe buýt có lộ trình vòng lặp khép kín (như Tuyến 56B) hoặc đi qua các nút giao lập thể (cầu vượt, hầm chui), phép chiếu khoảng cách Euclidean gần nhất sẽ bị nhầm lẫn giữa nhánh đi và nhánh về.
- **Hậu quả**: Tọa độ $s$ bị giật lùi hàng km ($\Delta s < -200\text{m}$) trong vài chục giây.
- **Khắc phục**: Thuật toán chiếu bắt buộc phải có **Ràng buộc Đơn điệu Không gian - Thời gian (Monotonicity Spatial Guard)**: Chỉ tìm điểm chiếu trong lân cận $s \in [s_{\text{prev}} - 50\text{m}, s_{\text{prev}} + 1500\text{m}]$.

---

## CHƯƠNG 4: TỰ ĐỘNG HÓA ĐÁM MÂY 24/7 (GITHUB ACTIONS WATCHDOG)

### 4.1. Sự Cố Đứt Xích Im Lặng (Silent Relay Failure)
- **Cơ chế Relay**: Runner cào 9 phút, sau đó gửi API call dispatch đánh thức runner tiếp theo.
- **Điểm yếu chí mạng**: Nếu runner bị GitHub hủy đột ngột (do bảo trì node, timeout hoặc hủy thủ công), bước trigger tiếp theo không bao giờ được chạy $\to$ Hệ thống dừng hẳn mà không có thông báo.
- **Giải pháp**: Thiết lập **Watchdog Cron dự phòng 2 giờ**:
  ```yaml
  on:
    schedule:
      - cron: '0 */2 * * *'
    repository_dispatch:
      types: [relay-next-crawler]
  ```
  Nếu xích tự relay hoạt động bình thường, cron sẽ chỉ đóng vai trò bảo hiểm. Nếu xích đứt, tối đa sau 2 giờ cron sẽ tự động đánh thức lại toàn bộ hệ thống.

---

## CHƯƠNG 5: PHÂN QUYỀN SANDBOX & RANH GIỚI THỰC THI

### 5.1. Cơ Chế Cô Lập Thư Mục Của Agent Sandbox
- Agent Sandbox (trên Windows) mặc định cấp quyền đọc/ghi trong thư mục Workspace của dự án, nhưng **chặn truy cập vào `C:\Users\<User>\AppData\Local\`**.
- **Bài học**:
  - Không đặt các tệp CSDL hay mã nguồn thực thi quan trọng trong `AppData\Local`.
  - Mọi tệp dữ liệu phải nằm trọn vẹn trong workspace (`data/`, `reports/`, `models/`).
  - Khi cần gọi các binary ngoài workspace bị chặn quyền (như Python 3.14 gốc), phải thực thi ở chế độ bypass sandbox hoặc dùng venv nằm ngay trong dự án.

---

## CHƯƠNG 6: CHUẨN HÓA ENCODING TIẾNG VIỆT TRÊN WINDOWS

### 6.1. Lỗi `UnicodeEncodeError: 'charmap' codec can't encode...`
- **Nguyên nhân**: Mặc định Windows PowerShell và Command Prompt sử dụng bảng mã Code Page tiếng Anh (CP1252 hoặc CP437). Khi Python in các ký tự tiếng Việt có dấu (như `ầ`, `ố`, `đ`), hàm `print()` sẽ quăng lỗi và dừng chương trình.
- **Chuẩn hóa bắt buộc**: Đầu mọi script Python có in log hoặc xử lý tên trạm tiếng Việt phải thêm 4 dòng:
  ```python
  import sys
  if sys.stdout.encoding != 'utf-8':
      try:
          sys.stdout.reconfigure(encoding='utf-8')
      except Exception:
          pass
  ```
  Hoặc khi mở file text, luôn chỉ định rõ ràng: `open(path, "r", encoding="utf-8")`.
