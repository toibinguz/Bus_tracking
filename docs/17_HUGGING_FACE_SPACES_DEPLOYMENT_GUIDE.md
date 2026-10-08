# Hướng Dẫn Triển Khai Crawler 24/7 Trên Hugging Face Spaces (100% Miễn Phí, Không Thẻ)

Hugging Face (HF) cung cấp dịch vụ **Spaces** (2 vCPU, 16GB RAM miễn phí 100%, không cần thẻ tín dụng). Tuy nhiên, để vận hành một hệ thống crawler dữ liệu Big Data chuẩn xác trên HF Spaces mà **không bị mất dữ liệu và không bị tắt ngấm**, bạn cần hiểu rõ cơ chế và làm đúng theo hướng dẫn dưới đây.

---

## 1. Bản Chất Kỹ Thuật Trên Hugging Face Spaces (Cần Biết)

1. **Vấn đề Ổ cứng tạm thời (Ephemeral Storage):**
   * Ổ cứng của Spaces miễn phí là tạm thời. Nếu Space bị khởi động lại, các file `.jsonl` trên ổ cứng local của Space sẽ bị xóa sạch.
   * **Giải pháp chuẩn:** Chúng ta tạo song song 1 **Hugging Face Dataset** (cũng miễn phí 100%). Cứ mỗi 30–60 phút, script crawler sẽ tự động đẩy (upload) file `.jsonl` sang Dataset. Dữ liệu trên Dataset là vĩnh viễn!
2. **Vấn đề Ngủ đông (Sleep Mode sau 15–48 phút không có người xem):**
   * **Giải pháp:** Space sẽ chạy một giao diện Web Gradio đơn giản (hiển thị bảng log 52 xe buýt). Chúng ta dùng dịch vụ **UptimeRobot** (miễn phí, không thẻ) để "ping" vào link web của Space mỗi 5 phút. Space sẽ luôn thức 24/7!

---

## 2. Quy Trình 4 Bước Triển Khai Thực Tế

### BƯỚC 1: Tạo Nơi Lưu Dữ Liệu Vĩnh Viễn (HF Dataset)
1. Truy cập: [huggingface.co](https://huggingface.co/) ➔ Đăng ký tài khoản (nếu chưa có).
2. Bấm vào Avatar góc trên bên phải ➔ Chọn **New Dataset**.
3. Đặt tên: `hust-bus-data` (ví dụ: `username/hust-bus-data`).
4. Chọn chế độ: **Private** (Riêng tư - chỉ bạn xem được).
5. Bấm **Create Dataset**.

### BƯỚC 2: Tạo Access Token Để Cho Phép Code Ghi Dữ Liệu
1. Vào Avatar góc trên bên phải ➔ **Settings** ➔ **Access Tokens** (hoặc link `https://huggingface.co/settings/tokens`).
2. Bấm **Create new token**:
   * Name: `crawler_token`
   * Type: **Write** (Bắt buộc chọn Write để code được phép ghi file).
3. Copy chuỗi Token này (dạng `hf_...`).

### BƯỚC 3: Tạo Hugging Face Space Chạy Crawler
1. Vào lại trang chủ HF ➔ Bấm Avatar ➔ Chọn **New Space**.
2. Thiết lập:
   * **Space name:** `hust-bus-crawler`
   * **License:** `mit`
   * **Select the Space SDK:** Chọn **Gradio**
   * **Space hardware:** Chọn **CPU basic · 2 vCPU · 16 GB · Free**
   * **Visibility:** Public hoặc Private tùy bạn.
3. Bấm **Create Space**.
4. Cấu hình biến môi trường bí mật (Secrets):
   * Vào tab **Settings** của Space vừa tạo ➔ Cuộn xuống mục **Variables and secrets**.
   * Bấm **New secret**:
     * Secret 1: Name = `HF_TOKEN`, Value = *(Dán token `hf_...` ở Bước 2)*.
     * Secret 2: Name = `HF_DATASET_ID`, Value = *(Tên dataset ở Bước 1, ví dụ `username/hust-bus-data`)*.
     * Secret 3: Name = `TOMTOM_KEY`, Value = *(Dán API Key TomTom của bạn)*.

### BƯỚC 4: Tải Bộ Code Lên Space
Tại tab **Files** của Space, bấm **Add file ➔ Upload files** và tải lên các file trong thư mục `hf_space_deployment/`:
* `app.py` (Script chính: chạy crawler ngầm + đẩy data lên Dataset + giao diện Gradio).
* `requirements.txt` (Khai báo thư viện `huggingface_hub`, `gradio`).
* `hust_cluster_config.json` (Cấu hình 52 xe buýt).

Sau khi tải xong, bấm **Commit changes**. Hugging Face sẽ tự động build và chạy Space trong vòng 1 phút!

---

## 3. Chống Ngủ Bằng UptimeRobot (Giữ Space Chạy 24/7)
1. Truy cập: [uptimerobot.com](https://uptimerobot.com/) ➔ Đăng ký tài khoản miễn phí (không cần thẻ).
2. Bấm **Add New Monitor**:
   * **Monitor Type:** `HTTP(s)`
   * **Friendly Name:** `HUST Bus Space Keep-Alive`
   * **URL (or IP):** Điền đường link web public của Space của bạn (Ví dụ: `https://username-hust-bus-crawler.hf.space`).
   * **Monitoring Interval:** `5 minutes`.
3. Bấm **Create Monitor**.
* 👉 *Cứ mỗi 5 phút, UptimeRobot sẽ "gõ cửa" trang web một lần. Space sẽ nhận diện có lượt truy cập và KHÔNG BAO GIỜ bị rơi vào trạng thái ngủ đông!*

---

## 4. Tải Dữ Liệu Đã Thu Thập Về Máy Tính
Sau vài ngày hoặc vài tuần, bạn muốn lấy toàn bộ file `.jsonl` về máy để chạy Spark:
* **Cách 1 (Tải từ trình duyệt):** Vào trang Dataset `huggingface.co/datasets/username/hust-bus-data` ➔ Tab **Files** ➔ Bấm tải từng file.
* **Cách 2 (Bằng Python 1 dòng lệnh):**
  ```python
  from huggingface_hub import snapshot_download
  snapshot_download(repo_id="username/hust-bus-data", repo_type="dataset", local_dir="data/crawled_dataset")
  ```

