# Bộ dữ liệu Chuẩn Địa lý & Danh bạ Tuyến/Trạm (`data/ground_truth`)

- **Vai trò:** Lưu trữ dữ liệu gốc BusMap Canonical làm nguồn sự thật duy nhất (SSOT) cho hình học tuyến, thứ tự trạm dừng và metadata tuyến.
- **Đầu vào:** Export từ BusMap Canonical (`busmap_canonical/`).
- **Đầu ra:** Bảng `canonical_routes`, `canonical_shapes`, `canonical_stations` trong `data/hanoi_bus_system.db` (qua `step_1_5_busmap_canonical_migration`).

## Danh sách file hiện có (`data/ground_truth/busmap_canonical/`)

| File | Vai trò |
| --- | --- |
| `hn.routes.json` | Danh mục tuyến xe buýt Hà Nội (`route_id`, `route_code`, tên tuyến). |
| `hn.routeinfo.json` | Chi tiết hành trình lượt đi/lượt về và danh sách trạm theo thứ tự. |
| `hn.stations.json` | Tọa độ, mã và tên trạm dừng. |
| `hanoi_bus_routes.geojson` | Hình học polyline tuyến dạng GeoJSON. |
| `hanoi_bus_stations.geojson` | Hình học điểm trạm dừng dạng GeoJSON. |
| `region_hn.json` | Thông tin vùng hành chính BusMap. |
| `hn_data.zip` | Gói nén dữ liệu gốc BusMap. |

## Cách nạp lại vào SQLite

```bash
python -m module_1_data_ingestion_and_preprocessing.step_1_5_busmap_canonical_migration.ingest_busmap_canonical
```
