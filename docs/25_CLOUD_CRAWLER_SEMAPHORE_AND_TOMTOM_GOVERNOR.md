# 25. CƠ CHẾ ĐỒNG BỘ TRẠNG THÁI RUNNER VÀ ĐIỀU TIẾT HẠN MỨC TOMTOM (CLOUD SEMAPHORE & BUDGET GOVERNOR SPECIFICATION)

> **Mục tiêu tài liệu:** Đặc tả chi tiết cơ chế truyền trạng thái hạn ngạch giữa các GitHub Actions Runner tạm thời (Stateless Ephemeral VMs) thông qua Hugging Face Dataset API, và kiến trúc phân tách độc lập giữa TomTom Traffic Flow và Incident Details.

---

## 1. THÁCH THỨC VÀ BỐI CẢNH KIẾN TRÚC

GitHub Actions vận hành trên các máy ảo Ubuntu dùng 1 lần (Ephemeral Runners):
- Mỗi phiên chạy kéo dài đúng **9 phút**.
- Sau 9 phút, máy ảo bị hủy bỏ hoàn toàn $\implies$ Không thể lưu biến trạng thái vào RAM hay file local.
- **Yêu cầu:** Phiên thứ $N+1$ khi vừa thức dậy phải biết chính xác hôm nay các phiên $1, 2, \dots, N$ đã tiêu thụ bao nhiêu request TomTom để không vượt ngưỡng giới hạn tháng.

---

## 2. GIẢI PHÁP: HUGGING FACE CLOUD STATE SEMAPHORE

Thay vì sử dụng các dịch vụ Database hay Redis tốn phí, hệ thống biến chính **Hugging Face Dataset Tree API** thành **Cột cờ trạng thái tập trung (Central State Semaphore)**.

```text
 ┌────────────────────────────────────────────────────────┐
 │            HUGGING FACE DATASET CLOUD REPO             │
 │   Toibinguz/hust-bus-data/tree/main/raw_data/{DATE}/   │
 ├──────────────────────────┬─────────────────────────────┤
 │        /traffic/         │         /incidents/         │
 │   batch_053241.jsonl     │     batch_053241.jsonl      │
 │   batch_054204.jsonl     │     batch_054204.jsonl      │
 │   ...                    │     ...                     │
 └──────────────────────────┴─────────────────────────────┘
              ▲                               ▲
              │ Đếm số file                   │ Đếm số file
              │ (Flow Batches)                │ (Incident Batches)
 ┌────────────┴───────────────────────────────┴───────────┐
 │       RUNNER GITHUB ACTIONS (PHIÊN THỨ N+1 VỪA DẬY)    │
 │                                                        │
 │ 1. Query HF Tree API:                                  │
 │    - flow_count = len(/traffic/)                       │
 │    - inc_count  = len(/incidents/)                     │
 │                                                        │
 │ 2. Budget Governor Check:                              │
 │    - can_poll_flow = (flow_count < 31)                 │
 │    - can_poll_inc  = (inc_count  < 75)                 │
 │                                                        │
 │ 3. Tiến hành cào theo kỷ luật Pacing                   │
 │ 4. Đẩy batch mới lên -> Tự động tăng biến đếm          │
 └────────────────────────────────────────────────────────┘
```

### 2.1. Mã nguồn truy vấn cây thư mục Cloud (`core/hf_client.py`)
```python
def get_hf_today_batch_count(date_tag, category, token, dataset_id=HF_DATASET_ID):
    """Truy vấn số lượng batch (traffic, incidents, bus) đã tải lên Hugging Face hôm nay."""
    url = f"https://huggingface.co/api/datasets/{dataset_id}/tree/main/raw_data/{date_tag}/{category}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, list):
                return len(data)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return 0
    return 0
```

---

## 3. PHÂN TÁCH ĐỘC LẬP GIỮA FLOW VÀ INCIDENT DETAILS

Bảng hạn mức thực tế tài khoản TomTom:
- **Traffic Flow Segment Data API:** Trần tháng 20,000 req $\implies$ Ngân sách ngày: **600 req/ngày** ($31 \text{ đợt} \times 19 \text{ nút}$).
- **Traffic Incident Details API:** Trần tháng 2,500 req (mới dùng 70) $\implies$ Ngân sách ngày: **75 req/ngày** ($1 \text{ req / đợt BBox}$).

### 3.1. Kỷ luật Pacing của Traffic Flow (31 đợt/ngày)
| Khung giờ | Thời lượng | Chu kỳ quét | Số đợt tiêu thụ | Ghi chú kỷ luật |
|---|:---:|:---:|:---:|---|
| **Cao điểm sáng** (06:30 – 09:00) | 2.5h | **18 phút/lần** | **~8 đợt** | Bắt trọn ùn tắc giờ đi làm |
| **Thấp điểm trưa** (09:00 – 16:30) | 7.5h | **54 phút/lần** | **~8 đợt** | Cấm Dynamic Congestion quét 18p |
| **Cao điểm chiều** (16:30 – 19:30) | 3.0h | **18 phút/lần** | **~10 đợt** | Bảo lưu quota cho kẹt xe tan tầm |
| **Sáng sớm & Tối** (05:00-06:30, 19:30-22:00) | 4.0h | **54 phút/lần** | **~5 đợt** | Đo baseline đường thông |
| **TỔNG CỘNG** | **17.0h** | | **31 đợt** | **Phủ đều 100% đến 22:00 đêm** |

### 3.2. Kỷ luật Pacing của Incident Details (75 đợt/ngày)
- Do chỉ tốn đúng **1 request** cho cả Bounding Box Hà Nội và ngân sách dồi dào ($>2,400$ calls còn lại):
- Incident được quét **mỗi 18 phút/lần liên tục cả ngày** từ 05:00 đến 22:00 ($56 \text{ đợt/ngày} < 75 \text{ trần ngày}$).
- Đảm bảo dữ liệu sự cố ngập úng, tai nạn luôn tươi mới nhất cho mô hình ML.

---

## 4. TỔNG KẾT VẬN HÀNH

1. **Khóa đơn tiến trình:** `concurrency: group: hust-bus-crawler-relay` đảm bảo chỉ có duy nhất 1 runner chạy tại một thời điểm, triệt tiêu hoàn toàn race condition khi đọc/ghi Hugging Face.
2. **Kỷ luật ngân sách tự động:** Runner tự động ngắt Flow khi đạt 31 đợt và ngắt Incident khi đạt 75 đợt mà không làm gián đoạn chuỗi cào GPS xe buýt 24/7.
3. **Độ bền vững:** Toàn bộ hệ thống vận hành $0$ đồng trên hạ tầng kết hợp GitHub Actions + Hugging Face Dataset.
