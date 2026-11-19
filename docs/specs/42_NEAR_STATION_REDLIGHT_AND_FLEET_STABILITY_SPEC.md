# Spec 42: Ổn định ETA khi dừng đèn đỏ gần trạm & Giai đoạn 2 cụm đội xe

## 1. Bối cảnh & Bằng chứng định lượng
- Tài liệu kiểm toán liên quan: [LIVE_DEMO_AUDIT_AND_FLEET_PROPOSAL_20261118.md](../LIVE_DEMO_AUDIT_AND_FLEET_PROPOSAL_20261118.md)
- Biểu đồ hội tụ thời gian thực tuyến `32`: [live_eta_convergence_20261118.png](../figures/ml_evaluation/live_eta_convergence_20261118.png)
- Trên mô hình `causal_eta_v1` (`15` ngày / `900` cây), đo độ nhạy khi hạ đồng thời `ego_speed_avg_3min_kmh` và `ego_speed_avg_5min_kmh` từ `18.0 -> 0.0 km/h`:

| Cự ly còn lại (`rem`) | `base` | `18 km/h` | `6 km/h` | `2 km/h` | `0 km/h` | Độ vọt (`18 -> 0`) |
|---|---:|---:|---:|---:|---:|---:|
| Xa (`4054.7m`) | 873.0s | 876.2s | 882.9s | 889.9s | 890.8s | `+14.6s` (`+1.7%`) |
| Trung (`1326.4m`) | 286.7s | 286.7s | 287.7s | 293.9s | 293.0s | `+6.3s` (`+2.2%`) |
| **Gần (`206.0m`)** | 44.0s | 38.8s | 39.6s | 51.6s | **120.1s** | **`+81.3s` (`+210%`)** |

## 2. Yêu cầu bắt buộc phải sửa

### 2.1. Hiện tượng vọt ETA khi dừng đèn đỏ ở cự ly gần trạm (`rem < 300m`)
- **Nguyên nhân gốc:**
  1. `CausalFeatures.speed()` trong `module_3_bus_eta_prediction/step_3_2_feature_store_extractor/causal_eta.py` gán thẳng `0.0 km/h` khi dịch chuyển `< STATIONARY_TOLERANCE_M (15.0m)`, tạo bước nhảy phi tuyến gắt ở nhánh `ego_speed == 0.0` (`51.6s -> 120.1s` tại `rem = 206m`).
  2. Mô hình thiếu trạng thái thời gian đã dừng tại chỗ (`dwell_elapsed`), nên mỗi nhịp xe đứng chờ đèn đỏ lại cộng thêm trọn vẹn `~+80s` khiến `arrival_time_epoch` trôi lùi liên tục rồi sập ngược `-80s` ngay khi đèn xanh bật lên.
  3. Tại cự ly gần (`rem < 300m`), độ lệch tuyệt đối `+80s` làm `ΔETA / ETA` tăng gấp ~3 lần.
- **Hướng xử lý cần thiết kế & kiểm chứng:**
  - Tách hoặc làm mượt ngưỡng `ego_speed == 0.0` ở cự ly gần trạm (không để cây quyết định nhảy bậc `> 2x` chỉ vì dịch chuyển `< 15m` khi dừng đèn đỏ ngắn hạn).
  - Bổ sung/tích hợp ngữ cảnh thời gian đã dừng tại chỗ (`dwell_elapsed`) hoặc giới hạn phần cộng thêm ở `rem < 300m` theo phân phối dừng đèn đỏ thực tế để `Predicted Arrival` không trôi lùi liên tục trong lúc chờ đèn.

### 2.2. Cụm `lead_bus` / `follow_bus` — Giai đoạn 2 (khi retrain bản tiếp theo)
- Giai đoạn 1 (`compute_proximity_capped_etas` trong `serving_service.py`) đã chặn nghịch lý `±150s` giữa hai xe cách nhau `<= 80–120m`, nhưng chưa xử lý 2 ca nhảy warm-up `lead_bus_speed_ratio: None -> ~0.008` (`+92.3s`, `+99.8s`).
- Khi retrain:
  1. Bổ sung biến tổng hợp tốc độ hành lang phía trước tới trạm đích (`0 < d <= target_s - s_ego`) song song với thông tin xe gần nhất.
  2. Đưa `lead_bus_speed_ratio` vào `MONOTONE_SPEED_FEATURES = -1` (hoặc đánh giá lại sau khi có biến hành lang).

### 2.3. Hạng mục mở giữ lại: Cold-start `30s` & quá hạn `90s`
- Giữ nguyên đánh đổi hiện tại giữa `MIN_SPEED_WINDOW = 30.0s` / `MAX_POSITION_AGE = 90.0s` và tính politeness với upstream; xử lý trong spec riêng nếu có thay đổi kiến trúc nguồn dữ liệu.

## 3. Tiêu chí nghiệm thu (Acceptance Criteria)
1. Khi xe dừng đèn đỏ ngắn hạn (`0 -> 60s`) ở cự ly `rem = 150–300m`, `eta_seconds` không được nhảy vọt `>= 2x` so với trạng thái đang chạy bình thường trước khi dừng, và không đẩy `arrival_time_epoch` trôi lùi liên tục theo từng nhịp poll.
2. Mọi thay đổi feature/model phải đánh giá lại trên toàn bộ tập `test` (`4,000,961` dòng), không làm suy giảm `MAE`, `MdAE`, `P90` tổng thể và `Horizon 1` so với bản `causal_eta_v1` (`15` ngày / `900` cây: `MAE=132.30s`, `MdAE=80.60s`, `P90=310.16s`).
