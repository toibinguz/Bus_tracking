# Hướng Dẫn Thiết Lập GitHub Actions Crawler 24/7 (Hoàn Toàn Tự Động Trên Mây)

Hệ thống cho phép bạn **tắt máy tính, gập laptop bỏ vào balo đi học mà dữ liệu 52 xe buýt Bách Khoa và TomTom vẫn được thu thập liên tục 24/7 trên máy chủ của GitHub/Microsoft**, sau đó tự động lưu vào Hugging Face Dataset của bạn (`Toibinguz/hust-bus-data`).

Khi bạn mở laptop lên, chỉ cần chạy 1 lệnh là toàn bộ dữ liệu tự động tải về máy tính cá nhân.

---

## 1. Các Thành Phần Đã Được Chuẩn Bị Sẵn

Trong thư mục dự án của bạn đã có đầy đủ:
1. Workflow tự động chạy mỗi 10 phút: [`.github/workflows/crawl_bus.yml`](file:///z:/Desktop/Bus_tracking/.github/workflows/crawl_bus.yml)
2. Script cào dữ liệu trên mây: [`scripts/cloud_crawler_step.py`](file:///z:/Desktop/Bus_tracking/scripts/cloud_crawler_step.py)
3. Script đồng bộ dữ liệu về laptop: [`scripts/sync_from_hf.py`](file:///z:/Desktop/Bus_tracking/scripts/sync_from_hf.py)
4. Token Hugging Face của bạn: [`access_token_hf.txt`](file:///z:/Desktop/Bus_tracking/access_token_hf.txt)

---

## 2. Các Bước Kích Hoạt (Mất 2 Phút)

### BƯỚC 1: Tạo Repository mới trên GitHub
1. Vào [github.com](https://github.com/) ➔ Đăng nhập.
2. Bấm nút **New** (Tạo repo mới):
   * **Repository name:** `Bus_tracking`
   * **Visibility:** Chọn **Private** (Riêng tư).
3. Bấm **Create repository**.

---

### BƯỚC 2: Đẩy toàn bộ mã nguồn lên GitHub
Mở PowerShell tại thư mục `z:\Desktop\Bus_tracking`, chạy lần lượt các lệnh sau:
```bash
git init
git add .
git commit -m "feat: HUST bus 24x7 cloud crawler with GitHub Actions"
git branch -M main
git remote add origin https://github.com/<tai_khoan_cua_ban>/Bus_tracking.git
git push -u origin main
```
*(Thay `<tai_khoan_cua_ban>` bằng username GitHub của bạn).*

---

### BƯỚC 3: Cấu hình 3 biến bí mật (Secrets) trên GitHub
Để code trên mây có quyền đẩy dữ liệu sang Hugging Face và gọi TomTom:
1. Trên trang repo GitHub vừa tạo, bấm vào tab **Settings** (ở thanh menu trên cùng).
2. Ở thanh menu bên trái, tìm mục **Secrets and variables** ➔ Chọn **Actions**.
3. Bấm nút xanh **New repository secret**, lần lượt tạo 3 biến:
   * **Secret 1:**
     * Name: `HF_TOKEN`
     * Secret: `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`
   * **Secret 2:**
     * Name: `HF_DATASET_ID`
     * Secret: `Toibinguz/hust-bus-data`
   * **Secret 3:**
     * Name: `TOMTOM_KEY`
     * Secret: *(Mở file `Test_tomtom/TOMTOM_API_KEY.txt` copy key dán vào)*

---

### BƯỚC 4: Chạy thử và ngắm nhìn kết quả
1. Bấm vào tab **Actions** trên GitHub.
2. Ở cột bên trái, bấm vào **HUST Bus Cluster 24x7 Cloud Crawler**.
3. Nhìn sang bên phải, bấm vào nút **Run workflow** ➔ Bấm nút xanh **Run workflow**.
4. Chờ khoảng 20–30 giây, bạn sẽ thấy một dấu tích xanh lá cây **✅** xuất hiện.
5. Truy cập vào trang Dataset của bạn: [https://huggingface.co/datasets/Toibinguz/hust-bus-data](https://huggingface.co/datasets/Toibinguz/hust-bus-data)
   * Bạn sẽ thấy thư mục `raw_data/` xuất hiện với các file telemetry của 52 xe buýt Bách Khoa và 19 nút giao TomTom!

---

## 3. Cách Đồng Bộ Dữ Liệu Về Laptop Khi Mở Máy

Sau 1 ngày đi học hoặc cuối tuần bạn muốn lấy toàn bộ dữ liệu cào được về máy tính để chạy Apache Spark / Kafka:
Mở PowerShell trên máy tính và chạy:
```powershell
python scripts/sync_from_hf.py
```
Script sẽ tự động kết nối lên Hugging Face Dataset của bạn và tải toàn bộ các file `.jsonl` về thẳng thư mục `data/raw/` trên laptop!

