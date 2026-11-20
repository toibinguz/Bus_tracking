# Step 3.5: Web Demo FastAPI (`step_3_5_web_demo`)

- **Vai trò:** Cung cấp REST API, quản lý vòng đời `SpeedLayerPoller` (`lifespan`) và phục vụ 2 giao diện bản đồ Esri vệ tinh tách biệt: Trang Hành khách (`/`) và Trang Debug Console (`/debug`).
- **Đầu vào:** `BusMapServingService` & `SpeedLayerPoller` (`step_3_4_eta_serving_and_evaluation`).
- **Đầu ra:** Giao diện Hành khách (`index.html`, `passenger.css`, `passenger.js`), giao diện Debug (`debug.html`, `debug.css`, `debug.js`), tiện ích dùng chung (`bus_core.js`) và các endpoint JSON.

## Thành phần chính

| File / Endpoint | Vai trò |
| --- | --- |
| `app.py` | Khởi tạo FastAPI + `lifespan` (`SpeedLayerPoller`, tắt khi `DISABLE_SPEED_POLLER=1`), mount `/static` |
| `GET /`, `GET /debug` | Trả trang Hành khách (`index.html`) và trang Debug Console 4 tab (`debug.html` — gồm tab **Sự cố TomTom** vẽ LineString & popup) |
| `GET /api/health`, `GET /api/v1/health` | Trạng thái `healthy`/`degraded`, `model_available`, và snapshot `poller` |
| `GET /api/routes` | Danh sách tuyến xe buýt khả dụng |
| `GET /api/live-vehicles` | Vị trí & telemetry xe đang chạy kèm `upstream_status`, `timbus_status`, `busmap_updated_at` |
| `GET /api/route-shape`, `GET /api/route-stations` | Hình học polyline tuyến và danh sách trạm theo lượt đi/về |
| `GET /api/station-eta` | Danh sách xe đang tới trạm kèm `SafeWindowDTO`, `fallback_reason` và trạng thái upstream |

## Cách chạy & Kiểm thử

```bash
# Chạy ngầm trước demo hoặc chạy trực tiếp (bắt buộc --workers 1)
scripts\start_demo_bg.bat
python -m uvicorn module_3_bus_eta_prediction.step_3_5_web_demo.app:app --host 127.0.0.1 --port 8000 --workers 1

python -m pytest tests/module_3/test_speed_poller_and_feedback.py tests/module_3/test_spec24_conservative_eta_blackbox.py --basetemp=runtime/pytest_tmp -q
```
