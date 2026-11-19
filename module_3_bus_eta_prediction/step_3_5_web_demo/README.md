# Step 3.5: Web Demo FastAPI (`step_3_5_web_demo`)

- **Vai trò:** Cung cấp REST API và giao diện bản đồ trực quan theo dõi xe buýt thời gian thực cùng ETA tới trạm (2 chế độ hiển thị: `Hành khách` và `Debug`).
- **Đầu vào:** `BusMapServingService` (`step_3_4_eta_serving_and_evaluation`).
- **Đầu ra:** Giao diện web (`static/index.html`, `app.js`, `style.css`) và các endpoint JSON.

## Thành phần chính

| File / Endpoint | Vai trò |
| --- | --- |
| `app.py` | Khởi tạo ứng dụng FastAPI, mount `/static`, gắn các route API |
| `GET /`, `GET /api/health` | Trả trang chủ `static/index.html` và trạng thái sống server |
| `GET /api/routes` | Danh sách tuyến xe buýt khả dụng |
| `GET /api/live-buses` | Vị trí & trạng thái xe buýt đang chạy trên tuyến |
| `GET /api/route-shape`, `GET /api/route-stations` | Hình học polyline tuyến và danh sách trạm theo lượt đi/về |
| `GET /api/station-eta` | Danh sách xe đang tới trạm kèm ETA dự báo (`SafeWindowDTO`) |

## Cách chạy & Kiểm thử

```bash
uvicorn module_3_bus_eta_prediction.step_3_5_web_demo.app:app --host 0.0.0.0 --port 8000
python -m pytest tests/module_3/test_spec24_conservative_eta_blackbox.py --basetemp=runtime/pytest_tmp -q
```
