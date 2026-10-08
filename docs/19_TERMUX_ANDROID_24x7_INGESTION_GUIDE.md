# HƯỚNG DẪN TRIỂN KHAI CRAWLER 24/7 TRÊN THIẾT BỊ ANDROID CHÍNH (TERMUX)

Tài liệu này cung cấp hướng dẫn từng bước để biến chiếc điện thoại Android bạn đang sử dụng hằng ngày thành một trạm thu thập dữ liệu (Ingestion Worker) hoạt động bền bỉ, êm ái trong túi quần, không làm nóng máy, không tốn pin và không ảnh hưởng đến việc nghe gọi, giải trí hằng ngày.

---

## 1. ĐÁNH GIÁ ẢNH HƯỞNG ĐẾN ĐIỆN THOẠI HÀNG NGÀY

Trước khi cài đặt, hãy xem xét các chỉ số tài nguyên thực tế:
* **Mức tiêu thụ CPU:** < **0.2%** trung bình. Mỗi 60 giây, crawler chỉ thức dậy khoảng **1.5 - 2 giây** để gửi request đồng thời qua 6 luồng nhẹ, sau đó CPU ngủ sâu (idle) suốt **58 giây** còn lại.
* **Mức tiêu hao RAM:** ~ **35MB - 45MB** (các điện thoại Android hiện nay đều có 6GB - 12GB RAM, mức 45MB chỉ chiếm **0.4%** dung lượng RAM).
* **Mức tiêu hao Pin:** Khoảng **1.5% - 2.5%** cho cả một ngày dài (05:00 đến 22:00) nhờ cơ chế ngủ giữa các chu kỳ.
* **Dung lượng 4G/Wi-Fi:** Khoảng **50 KB / phút** $\approx$ **3 MB / giờ** $\approx$ **50 MB / ngày** (chưa bằng dung lượng xem 2 video ngắn trên TikTok/Facebook).
* **Tự động nghỉ đêm:** Sau 22:00, script tự động chuyển sang chế độ ngủ, sáng 05:00 tự hoạt động trở lại.

---

## 2. BƯỚC 1: CÀI ĐẶT TERMUX CHUẨN (KHÔNG DÙNG GOOGLE PLAY)

> [!WARNING]
> **Tuyệt đối KHÔNG cài Termux từ Google Play Store!** Phiên bản trên Play Store đã ngừng cập nhật từ năm 2020 do chính sách của Google, các kho lưu trữ package (`pkg`) trên bản đó đều bị lỗi 404/SSL.

Hãy tải file cài đặt APK chính thức từ 1 trong 2 nguồn sau:
1. **F-Droid (Khuyên dùng):** [https://f-droid.org/packages/com.termux/](https://f-droid.org/packages/com.termux/) (Kéo xuống dưới mục **Download APK**).
2. **GitHub Releases:** [https://github.com/termux/termux-app/releases](https://github.com/termux/termux-app/releases) (Tải file `termux-app_v..._universal.apk`).

Cài đặt file APK vào máy như ứng dụng bình thường.

---

## 3. BƯỚC 2: CẤU HÌNH HỆ ĐIỀU HÀNH ANDROID (QUAN TRỌNG NHẤT)

Android có tính năng tiết kiệm pin rất gắt gao, nếu không cấu hình thì khi bạn tắt màn hình hoặc bỏ túi 5-10 phút, hệ điều hành sẽ tự đóng tiến trình chạy ngầm. Hãy làm 3 bước sau:

1. **Tắt tối ưu hóa pin cho Termux:**
   * Vào **Cài đặt** $\rightarrow$ **Ứng dụng** $\rightarrow$ tìm **Termux**.
   * Chọn mục **Pin (Battery)** $\rightarrow$ Đổi sang **Không hạn chế (Unrestricted)**.
2. **Khóa Termux trong danh sách Đa nhiệm (Recent Apps):**
   * Mở Termux lên, sau đó vuốt mở màn hình đa nhiệm (Recent Apps).
   * Nhấn giữ biểu tượng Termux (hoặc nhấn dấu 3 chấm) $\rightarrow$ Chọn **Khóa ứng dụng (Lock / Padlock icon)** để tránh bị bấm "Đóng tất cả" làm mất tiến trình.
3. **Cho phép sử dụng Dữ liệu nền:**
   * Trong thông tin ứng dụng Termux $\rightarrow$ **Dữ liệu di động** $\rightarrow$ Bật **Cho phép sử dụng dữ liệu nền**.

---

## 4. BƯỚC 3: THIẾT LẬP VÀ CHẠY TRÊN TERMUX

Mở ứng dụng Termux trên điện thoại, copy và chạy lần lượt các lệnh sau:

### 3.1. Cài đặt môi trường cơ bản (Chỉ làm lần đầu)
```bash
# Cập nhật kho gói và cài Python, Git, WakeLock
pkg update -y && pkg install -y python git openssh termux-api

# Cài thư viện hỗ trợ đẩy dữ liệu lên Hugging Face Cloud
pip install huggingface_hub
```

### 3.2. Tải mã nguồn dự án
```bash
git clone https://github.com/toibinguz/Bus_tracking.git
cd Bus_tracking
```

### 3.3. Nhập Token & API Key
Tạo file chứa Token và API Key trực tiếp trên điện thoại (chỉ cần làm 1 lần):
```bash
# Nhập TomTom Key
echo "YOUR_TOMTOM_KEY" > Test_tomtom/TOMTOM_API_KEY.txt

# Nhập Hugging Face Token (Role: Write)
echo "YOUR_HF_TOKEN" > access_token_hf.txt
```
*(Thay thế `YOUR_TOMTOM_KEY` và `YOUR_HF_TOKEN` bằng chuỗi token thực tế của bạn).*

---

## 5. BƯỚC 4: KHỞI ĐỘNG CRAWLER

Bạn có 2 cách chạy tùy nhu cầu:

### Lựa chọn A: Chạy xem trực tiếp trên màn hình (Đề xuất cho lần đầu)
```bash
# Kích hoạt chế độ giữ CPU thức (kể cả khi tắt màn hình)
termux-wake-lock

# Chạy crawler
python scripts/run_production_crawler.py
```
*Bạn sẽ thấy từng nhịp 60 giây hiển thị số lượng 52 xe buýt được ghi nhận thành công.*

---

### Lựa chọn B: Chạy ẩn hoàn toàn dưới nền (Dùng hàng ngày)
Chạy ngầm để bạn có thể thoát app Termux, chơi game, lướt web mà crawler vẫn âm thầm thu thập:
```bash
bash scripts/start_termux_daemon.sh
```

**Các lệnh quản trị tiện ích:**
* **Xem nhật ký thu thập thời gian thực:**
  ```bash
  tail -f crawler.log
  ```
  *(Bấm `Ctrl + C` trên bàn phím Termux để thoát màn hình xem log mà không làm dừng crawler).*
* **Dừng crawler khi cần:**
  ```bash
  bash scripts/stop_termux_daemon.sh
  ```

---

## 6. BƯỚC 5: ĐỒNG BỘ DỮ LIỆU TỪ ĐIỆN THOẠI VỀ MÁY TÍNH

Bạn có 2 phương thức cực kỳ linh hoạt để lấy dữ liệu về laptop:

### Phương thức 1: Tự động 100% qua Hugging Face Dataset (Khuyên dùng)
* Điện thoại khi chạy có cấu hình `access_token_hf.txt` sẽ **tự động tải dữ liệu lên Cloud sau mỗi 10 phút**.
* Khi bạn mở laptop (ở trường hoặc ở nhà), chỉ cần chạy 1 lệnh trên terminal laptop:
  ```powershell
  python scripts/sync_from_hf.py
  ```
* Toàn bộ dữ liệu điện thoại đã thu gom suốt cả ngày sẽ tự động tải về thư mục `data/raw/` trên laptop của bạn!

### Phương thức 2: Chuyển trực tiếp qua Wi-Fi nội bộ (Không cần qua Cloud)
Nếu bạn không muốn đẩy dữ liệu lên Internet:
1. Trên Termux (điện thoại), gõ lệnh mở web server chia sẻ file:
   ```bash
   python -m http.server 8080 --directory data/raw
   ```
2. Kiểm tra IP của điện thoại bằng lệnh:
   ```bash
   ifconfig
   ```
   *(Tìm địa chỉ `inet` dạng `192.168.1.X`)*
3. Mở trình duyệt trên máy tính cùng mạng Wi-Fi và truy cập:
   `http://192.168.1.X:8080`
   Bạn sẽ thấy danh sách toàn bộ các file `.jsonl` để tải trực tiếp về laptop trong tích tắc.
