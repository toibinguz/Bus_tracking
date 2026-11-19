# Thử nghiệm & Tích hợp TimBus (`experiments/timbus`)

- **Vai trò:** Client truy vấn nguồn GPS thời gian thực TimBus (`TimBusClient`) và bộ script đối chiếu/kiểm chứng độ phủ, độ trễ với BusMap.
- **Đầu vào:** TimBus Central API (`timbus.vn`), danh sách biển số/tuyến từ `data/hanoi_bus_system.db`.
- **Đầu ra:** `BusRecord` phục vụ hợp nhất nguồn live trong `BusMapServingService` (`step_3_4_eta_serving_and_evaluation`), và báo cáo kiểm chứng cục bộ.

## Thành phần chính

| File / Symbol | Vai trò | Input -> Output |
| --- | --- | --- |
| `timbus_tracker.py` (`TimBusClient`, `BusRecord`) | Client HTTP lấy tọa độ/vận tốc xe trực tuyến theo tuyến hoặc toàn cụm | `route_id` / `plates` -> `Dict[str, BusRecord]` |
| `reproduce_all_experiments.py` | Tái lập kiểm chứng codec, chênh lệch static DB và parity tuyến 32 | Live API + DB -> JSON/Console summary |
| `scripts/audit_timbus_coverage_and_anchors.py` | Kiểm tra độ phủ trạm neo (anchor stations) theo tuyến | DB + TimBus -> Báo cáo độ phủ |
| `scripts/build_timbus_anchor_db.py` | Xây dựng bảng/mapping trạm neo TimBus | Canonical DB -> Anchor mapping |
| `scripts/clean_route32_reverification.py` | Kiểm chứng riêng luồng trộn dữ liệu trên tuyến 32 | Live BusMap + TimBus -> Parity log |

## Cách chạy kiểm chứng

```bash
python experiments/timbus/timbus_tracker.py
python experiments/timbus/reproduce_all_experiments.py
```
