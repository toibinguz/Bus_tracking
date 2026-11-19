# Tài liệu Web Demo App & Tích hợp TimBus (`DEMO_APP`)

- **Trạng thái:** Current
- **Phạm vi:** Ứng dụng FastAPI phục vụ bản đồ trực tuyến, các REST endpoints, 2 chế độ trình bày trên client (`Hành khách` / `Debug`) và luồng trộn GPS TimBus.
- **Nguồn sự thật (Code paths):** `module_3_bus_eta_prediction/step_3_5_web_demo/` (`app.py`, `static/index.html`, `static/app.js`), `step_3_4_eta_serving_and_evaluation/` (`serving_service.py`, `eta_policy.py`, `dto.py`), `experiments/timbus/timbus_tracker.py`.

## 1. API Endpoints (`step_3_5_web_demo/app.py`)

| Endpoint | Mục đích |
| --- | --- |
| `GET /` | Trang chủ bản đồ (`static/index.html`) |
| `GET /api/health` | Trạng thái server, runtime model và release pointer (nếu bật) |
| `GET /api/routes` | Danh sách tuyến xe buýt |
| `GET /api/live-buses` | Vị trí & trạng thái xe đang hoạt động theo tuyến |
| `GET /api/route-shape`, `GET /api/route-stations` | Hình học polyline và danh sách trạm lượt đi/lượt về |
| `GET /api/station-eta` | Danh sách xe đang tiến tới trạm kèm `SafeWindowDTO` và ETA dự báo |

## 2. Chế độ hiển thị & Chính sách ổn định ETA

- **Hợp đồng 1 nguồn dự báo:** API `/api/station-eta` không nhận tham số `mode`; việc chuyển đổi giữa chế độ `Hành khách` (`value="passenger"`) và `Debug` (`value="debug"`) chỉ thay đổi cách trình bày ở phía client.
- **Ổn định hiển thị (`eta_policy.py`):** Áp dụng các rule P1–P10 và proximity cap để tránh ETA nhảy số bất thường khi xe dừng đèn đỏ gần trạm.
- **Trộn nguồn TimBus (`_sync_and_merge_timbus`):** Hợp nhất tốc độ/vị trí từ TimBus Central API vào luồng BusMap, kèm pass guard `_passed_station_plates` để xe đã đi qua trạm không bị hồi sinh bởi cache cũ.

## 3. Cách chạy & Kiểm thử

```bash
uvicorn module_3_bus_eta_prediction.step_3_5_web_demo.app:app --host 0.0.0.0 --port 8000
python -m pytest tests/module_3/test_spec24_conservative_eta_blackbox.py tests/module_3/test_timbus_station_state_regressions.py --basetemp=runtime/pytest_tmp -q
```
