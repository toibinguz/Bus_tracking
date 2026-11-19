# Step 3.4: Serving & Đánh giá ETA Trực tuyến (`step_3_4_eta_serving_and_evaluation`)

- **Vai trò:** Tầng điều phối Speed View: lấy dữ liệu live BusMap & TimBus, lọc/chiếu HMM, cập nhật `CausalFeatures` (36 biến), suy luận `ModelRuntime` (`causal-eta.v1`), áp dụng chính sách ETA (`eta_policy.py`) và trả DTO cho Web Demo.
- **Đầu vào:** BusMap Live API (`live_feed.py`), TimBus API (`TimBusClient`), `data/hanoi_bus_system.db`, `data/lakehouse/silver/fact_route_tomtom_incidents/`, `data/models/causal_eta_v1/`.
- **Đầu ra:** `RouteLiveResponse`, `RouteStationsResponse`, `RouteShapeResponse`, `ApproachingBusDTO` (`dto.py`).

## Thành phần chính

| File / Symbol | Vai trò | Input -> Output |
| --- | --- | --- |
| `serving_service.py` (`BusMapServingService`, `MacroSpeedTracker`) | Orchestrator chính: đồng bộ live, trộn TimBus, giữ guard vượt trạm & điều phối dự báo ETA | `route_id`, `station_order` -> `ApproachingBusDTO` |
| `model_runtime.py` (`ModelRuntime`) | Nạp `causal-eta.v1`, kiểm tra tuyến đã biết (`_known_routes`), gọi `predict_p50` (trả `None` để fallback baseline nếu ngoài domain) | 36-feature dict -> `eta_sec` / `None` |
| `data_access.py` (`DataAccess`, `IncidentsProvider`) | Truy cập tuyến/trạm/baseline từ SQLite và sự cố TomTom từ Silver Parquet | `route_id` -> Metadata & Incidents |
| `live_feed.py` (`fetch_live_vehicles_for_route`, `parse_ping_epoch`) | Gọi BusMap live API kèm cache RAM theo `route_id` | `route_id` -> `List[BusVehicleDTO]` |
| `eta_policy.py` (`compute_station_eta`, `BusState`) | Chính sách ổn định hiển thị ETA (P1–P10, hysteresis/proximity cap) | State + Model ETA -> `SafeWindowDTO` |
| `dto.py`, `busmap_service.py` | Hợp đồng Pydantic DTO công khai cho API FastAPI | Python objects -> JSON schema |
| `online_features.py`, `release_source.py`, `request_trace.py`, `frenet.py` | Trích đặc trưng online cũ, kiểm tra release artifact, ghi trace JSONL opt-in | — |

## Cách kiểm thử

```bash
python -m pytest tests/test_eta_validation_protocol.py tests/test_timbus_station_state_regressions.py --basetemp=runtime/pytest_tmp -q
```
