# 25. CƠ CHẾ SỔ CÁI HẠN NGẠCH TOMTOM CHÍNH XÁC & BỘ ĐIỀU TIẾT (EXACT INTEGER LEDGER & BUDGET GOVERNOR SPECIFICATION)

> **Mục tiêu tài liệu:** Đặc tả chi tiết cơ chế Sổ Cái Hạn Ngạch Số Nguyên Chính Xác (Exact Integer Quota Ledger) lưu trữ tại `data/metadata/tomtom_quota_tracker.json`, được đồng bộ tự động qua Git giữa các GitHub Actions Runner. Loại bỏ hoàn toàn việc ước lượng gián tiếp theo số file batch.

---

## 1. THÁCH THỨC VÀ BỐI CẢNH KIẾN TRÚC

GitHub Actions vận hành trên các máy ảo Ubuntu dùng 1 lần (Ephemeral Runners):
- Mỗi phiên chạy kéo dài đúng **9 phút**.
- Sau 9 phút, máy ảo bị hủy bỏ hoàn toàn $\implies$ Không thể lưu biến trạng thái vào RAM.
- **Vấn đề của cách làm cũ (Đếm file batch):**
  - Giả định mỗi file batch có 19 node ($31 \text{ đợt} \times 19 = 589$).
  - Nếu một đợt chỉ quét 5 hoặc 8 nút (ví dụ tập trung tuyến 31), việc đếm file sẽ làm sai lệch hoàn toàn hạn mức!
  - Không phản ánh số request thành công/thất bại thực tế.
- **Yêu cầu bắt buộc:** Phải đếm **chính xác từng request số nguyên (Integer Precision)** đã gửi đến TomTom API từ đầu tháng đến nay.

---

## 2. GIẢI PHÁP: SỔ CÁI HẠN NGẠCH ĐỒNG BỘ TỰ ĐỘNG (EXACT QUOTA LEDGER)

Sổ cái hạn ngạch được lưu trữ cố định tại:
`data/metadata/tomtom_quota_tracker.json`

Và được neo chính xác theo số liệu thực tế từ **Dashboard TomTom Developer Portal**:

```json
{
  "date": "2026-10-09",
  "month": "2026-10",
  "flow_daily_budget": 600,
  "flow_monthly_limit": 20000,
  "flow_used_today": 589,
  "flow_used_month": 1732,
  "flow_remaining_today": 11,
  "flow_remaining_month": 18268,
  "incident_daily_budget": 75,
  "incident_monthly_limit": 2500,
  "incident_used_today": 31,
  "incident_used_month": 70,
  "incident_remaining_today": 44,
  "incident_remaining_month": 2430,
  "last_updated": "2026-10-09 20:45:00"
}
```

### 2.1. Vòng đời đồng bộ giữa các Runner:
```text
 1. ĐẦU PHIÊN (00:01s):
    Runner checkout repo -> Đọc tomtom_quota_tracker.json:
    - flow_today = 589, flow_month = 1732
    - incident_today = 31, incident_month = 70
    (Nếu sang ngày mới 00:00 giờ Hà Nội -> flow_today tự động reset về 0).

 2. KIỂM TRA ĐIỀU KIỆN CHÍNH XÁC:
    num_nodes = len(HUST_BOTTLENECK_NODES)  # 19 nút
    can_poll_flow = (flow_today + num_nodes <= 600) and (flow_month + num_nodes <= 20000)
    can_poll_inc  = (incident_today + 1 <= 75) and (incident_month + 1 <= 2500)

 3. THỰC HIỆN GỌI & CỘNG DỒN CHÍNH XÁC:
    - Flow: traffic_records = execute_tomtom_flow_poll(...)
      delta_flow = len(traffic_records)  # Số request thực tế trả về
      flow_today += delta_flow
      flow_month += delta_flow
    - Incident: execute_tomtom_incident_poll(...)
      incident_today += 1
      incident_month += 1
    - Ghi cập nhật lại tomtom_quota_tracker.json.

 4. CUỐI PHIÊN (08:50s):
    Bước `Sync Updated Catalog to Git if Changed` trong workflow:
    - Tự động `git add data/metadata/`
    - Commit với cờ `[skip ci]` và push lên main.
    - Runner tiếp theo checkout main sẽ có ngay trạng thái chuẩn xác 100%!
```

---

## 3. PHÂN TÁCH ĐỘC LẬP GIỮA FLOW VÀ INCIDENT DETAILS

Bảng hạn mức thực tế tài khoản TomTom đã được đồng bộ chuẩn xác:
- **Traffic Flow Segment Data API:** Trần tháng 20,000 req $\implies$ Đã dùng **1,732** / Còn lại **18,268 requests**.
- **Traffic Incident Details API:** Trần tháng 2,500 req $\implies$ Đã dùng **70** / Còn lại **2,430 requests**.

### 3.1. Kỷ luật Pacing của Traffic Flow (Tối đa 600 req/ngày)
| Khung giờ | Thời lượng | Chu kỳ quét | Số request tiêu thụ | Ghi chú kỷ luật |
|---|:---:|:---:|:---:|---|
| **Cao điểm sáng** (06:30 – 09:00) | 2.5h | **18 phút/lần** | **~152 req** (8 đợt $\times 19$) | Bắt trọn ùn tắc giờ đi làm |
| **Thấp điểm trưa** (09:00 – 16:30) | 7.5h | **54 phút/lần** | **~152 req** (8 đợt $\times 19$) | Cấm Dynamic Congestion quét 18p |
| **Cao điểm chiều** (16:30 – 19:30) | 3.0h | **18 phút/lần** | **~190 req** (10 đợt $\times 19$) | Bảo lưu quota cho kẹt xe tan tầm |
| **Sáng sớm & Tối** (05:00-06:30, 19:30-22:00) | 4.0h | **54 phút/lần** | **~95 req** (5 đợt $\times 19$) | Đo baseline đường thông |
| **TỔNG CỘNG** | **17.0h** | | **~589 req / 600 trần** | **Phủ đều 100% đến 22:00 đêm** |

### 3.2. Kỷ luật Pacing của Incident Details (75 req/ngày)
- Do chỉ tốn đúng **1 request** cho cả Bounding Box Hà Nội và ngân sách dồi dào ($>2,400$ calls còn lại):
- Incident được quét **mỗi 18 phút/lần liên tục cả ngày** từ 05:00 đến 22:00 ($\approx 56 \text{ req/ngày} < 75 \text{ trần ngày}$).
- Đảm bảo dữ liệu sự cố ngập úng, tai nạn luôn tươi mới nhất cho mô hình ML.

---

## 4. TỔNG KẾT VẬN HÀNH

1. **Chuẩn xác tuyệt đối (Integer-level):** Đếm chính xác từng HTTP request gửi đi, không dựa vào ước lượng batch.
2. **Khóa đơn tiến trình:** `concurrency: group: hust-bus-crawler-relay` đảm bảo chỉ có duy nhất 1 runner chạy tại một thời điểm, triệt tiêu race condition khi ghi sổ cái Git.
3. **Tự động chuyển ngày theo múi giờ Hà Nội (UTC+7):** Khi sang ngày mới lúc 00:00 (17:00 UTC), biến đếm ngày tự động reset về 0 trong khi biến đếm tháng tiếp tục lũy kế chính xác.
