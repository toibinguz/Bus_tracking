# Step 1.5: Di trú Dữ liệu Chuẩn Tuyến & Trạm (`step_1_5_busmap_canonical_migration`)

- **Vai trò:** Khởi tạo schema và nạp dữ liệu chuẩn tuyến, hình học polyline và danh bạ trạm từ `data/ground_truth/busmap_canonical/` vào SQLite.
- **Đầu vào:** `hn.routes.json`, `hn.routeinfo.json`, `hn.stations.json`, `hanoi_bus_routes.geojson` trong `data/ground_truth/busmap_canonical/`.
- **Đầu ra:** Các bảng `canonical_routes`, `canonical_shapes`, `canonical_stations` trong `data/hanoi_bus_system.db`.

## Thành phần chính

| File / Symbol | Vai trò | Input -> Output |
| --- | --- | --- |
| `ingest_busmap_canonical.py` (`init_canonical_schema`, `ingest_routes_and_shapes`, `ingest_stations`, `project_station_to_shape`) | Tạo bảng canonical, nạp hình học tuyến và chiếu từng trạm lên tọa độ `s_station_m` | `busmap_canonical/*` -> SQLite canonical tables |

## Cách chạy

```bash
python -m module_1_data_ingestion_and_preprocessing.step_1_5_busmap_canonical_migration.ingest_busmap_canonical
```
