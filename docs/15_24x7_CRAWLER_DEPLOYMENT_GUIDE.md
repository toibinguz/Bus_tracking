# Hướng Dẫn Vận Hành Hệ Thống Crawler Dữ Liệu 24/7 (05:00 - 22:00)

Hệ thống crawler của chúng ta đã được đóng gói hoàn chỉnh trong script:
[`scripts/run_production_crawler.py`](file:///z:/Desktop/Bus_tracking/scripts/run_production_crawler.py).

Script này đảm nhận song song 2 nhiệm vụ:
1. **Bus-as-a-Probe (BaaP):** Quét tọa độ GPS của **52 xe buýt** (thuộc 5 tuyến Bách Khoa: 32, 31, 08A, 26, 21A) mỗi **60 giây**.
2. **TomTom Bottleneck Probe:** Quét tốc độ và độ trễ tại **19 nút giao trọng yếu** (mỗi 6 phút vào giờ cao điểm, 12 phút vào giờ thấp điểm, tự động khống chế dưới trần 2.200 req/ngày).
3. **Cơ chế Sinh học Xe Buýt (Operating Schedule):**
   * **Từ 05:00 đến 22:00:** Hoạt động liên tục, tự động xoay file dữ liệu theo từng giờ (`bus_telemetry_YYYY-MM-DD_HH.jsonl`).
   * **Từ 22:00 đến 05:00 sáng hôm sau:** Xe buýt ngừng chạy, script **tự động ngủ đông (sleep)** để tiết kiệm 100% CPU và mạng, tự động thức dậy đúng 05:00 sáng để tiếp tục!

Dưới đây là các phương án triển khai tùy thuộc vào thói quen sử dụng máy tính của bạn:

---

## CÁCH 1: Chạy Trực Tiếp Trên Máy Tính Windows (Dễ nhất - 1 Click)

### Lựa chọn 1.1: Chạy có giao diện dòng lệnh (để quan sát trực quan)
* Mở thư mục `z:\Desktop\Bus_tracking\scripts\`.
* Nhấp đúp chuột vào file: **[`start_crawler.bat`](file:///z:/Desktop/Bus_tracking/scripts/start_crawler.bat)**.
* Một cửa sổ terminal sẽ hiện lên hiển thị trực quan số xe hoạt động và tiến độ TomTom. Bạn có thể thu nhỏ cửa sổ xuống Taskbar và làm việc khác bình thường.

### Lựa chọn 1.2: Chạy hoàn toàn ẩn ngầm (Silent Background)
* Nhấp đúp chuột vào file: **[`start_crawler_background.vbs`](file:///z:/Desktop/Bus_tracking/scripts/start_crawler_background.vbs)**.
* Script sẽ chạy ngầm trong Windows background mà không mở bất kỳ cửa sổ console nào.
* Để tắt tiến trình ngầm: Mở Task Manager (Ctrl + Shift + Esc) ➔ Tìm `Python` ➔ Bấm End Task.

---

## CÁCH 2: Tự Động Chạy Mỗi Khi Bật Máy Tính (Startup)

Nếu bạn muốn mỗi khi bật laptop/PC lên dùng, crawler sẽ tự động chạy mà bạn không cần nhớ để bật:
1. Nhấn tổ hợp phím `Windows + R` trên bàn phím.
2. Gõ `shell:startup` rồi bấm Enter (thư mục Startup của Windows sẽ mở ra).
3. Chuột phải vào file `start_crawler_background.vbs` trong thư mục `scripts/` ➔ Chọn **Create shortcut** (Tạo lối tắt).
4. Kéo lối tắt (shortcut) đó ném vào thư mục `shell:startup` vừa mở.
5. **Xong!** Từ giờ mỗi lần bật máy tính, Windows sẽ tự động chạy crawler ngầm dưới nền. Khi bạn tắt máy, crawler tự dừng.

---

## CÁCH 3: Tự Động Theo Lịch Bằng Windows Task Scheduler

Nếu bạn muốn máy tính tự động bật crawler đúng 05:00 sáng và tắt đúng 22:00 tối:
1. Nhấn phím `Windows`, tìm kiếm **Task Scheduler** và mở lên.
2. Chọn **Create Basic Task...**:
   * **Name:** `HUST_Bus_Crawler`
   * **Trigger:** Daily (Hàng ngày) lúc `05:00:00 AM`.
   * **Action:** Start a program.
   * **Program/script:** `python.exe` (hoặc đường dẫn đầy đủ đến Python).
   * **Add arguments:** `scripts\run_production_crawler.py`
   * **Start in:** `z:\Desktop\Bus_tracking`
3. Tại tab **Settings**, bạn có thể tích chọn: *"Stop the task if it runs longer than: 17 hours"* (để task tự tắt đúng 22:00).

---

## CÁCH 4: Treo 24/7 Trên VPS Cloud Miễn Phí (Không Cần Bật Máy Tính)

Nếu bạn không muốn cắm sạc laptop cả ngày ở nhà:
1. **Đăng ký VPS miễn phí:**
   * **Oracle Cloud Free Tier:** Tặng miễn phí vĩnh viễn (Always Free) VPS Linux 4 OCPU, 24GB RAM.
   * Hoặc **AWS Free Tier:** Miễn phí 1 năm gói EC2 t2.micro.
2. **Cài đặt và chạy trên VPS:**
   ```bash
   git clone <repo_cua_ban> bus_tracking
   cd bus_tracking
   # Chạy ngầm 24/7 bằng nohup
   nohup python3 scripts/run_production_crawler.py > crawler.log 2>&1 &
   ```
3. Máy chủ trên Cloud sẽ tự động cào dữ liệu 24/7/365 với đường truyền cáp quang ổn định, không bao giờ lo mất điện hay rớt mạng ở nhà. Khi cần train model Spark, bạn chỉ cần tải thư mục `data/raw/` về máy.

