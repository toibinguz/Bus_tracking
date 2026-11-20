# Step 3.4: Serving & Đánh giá ETA Trực tuyến (`step_3_4_eta_serving_and_evaluation`)

- **Vai trò:** Tầng điều phối Speed View: lấy dữ liệu live BusMap & TimBus, đồng bộ sự cố TomTom live từ HF (`latest_incidents.json`), lọc/chiếu HMM, cập nhật `CausalFeatures` (40 biến gồm 4 biến TomTom), suy luận `ModelRuntime` (`causal-eta.v1`), áp dụng chính sách ETA (`eta_policy.py`) và trả DTO cho Web Demo.
- **Đầu vào:** BusMap Live API (`live_feed.py`), TimBus API (`TimBusClient`), Hugging Face `raw_data/latest_incidents.json`, `data/hanoi_bus_system.db`, `data/models/causal_eta_v1/`.
- **Đầu ra:** `RouteLiveResponse`, `RouteStationsResponse`, `RouteShapeResponse`, `ApproachingBusDTO`, `RouteIncidentDTO` (`dto.py`).

## Thành phần chính

| File / Symbol | Vai trò | Input -> Output |
| --- | --- | --- |
| `serving_service.py` (`BusMapServingService`, `MacroSpeedTracker`) | Orchestrator chính: đồng bộ live, trộn TimBus, chiếu sự cố TomTom (`RouteHMM` / `project_directed_point`, TTL `2700s`), giữ guard vượt trạm & điều phối ETA | `route_id`, `station_order` -> `ApproachingBusDTO` |
| `speed_poller.py` (`SpeedLayerPoller`, `is_operating_hours`) | Poller nền chu kỳ `45s` quét 48 tuyến BusMap + 2-worker TimBus + đồng bộ `latest_incidents.json` từ HF (`300s`) | Background -> làm ấm `CausalFeatures` & `/api/health` |
| `model_runtime.py` (`ModelRuntime`) | Nạp `causal-eta.v1`, kiểm tra tuyến đã biết (`_known_routes`), gọi `predict_p50_with_reason` (trả kèm `fallback_reason`) | 40-feature dict -> `(eta_sec, reason)` |
| `projection_tracker.py` (`RouteProjectionTracker`) | Chiếu và theo dõi quỹ đạo `RouteHMM` theo từng xe/tuyến | `BusVehicleDTO` -> `matched_projection` |
| `data_access.py` (`DataAccess`, `IncidentsProvider`) | Truy cập tuyến/trạm/baseline từ SQLite và sự cố TomTom từ Silver Parquet | `route_id` -> Metadata & Incidents |
| `live_feed.py` (`fetch_live_vehicles_for_route`, `parse_ping_epoch`) | Gọi BusMap live API (`fetch_route_buses_live_status`) kèm cache RAM và gắn `upstream_status` | `route_id` -> `RouteLiveResponse` |
| `eta_policy.py` (`compute_station_eta`, `BusState`) | Chính sách ổn định hiển thị ETA (P1–P10, hysteresis/proximity cap, `buffer_seconds`, `delay_seconds`) | State + Model ETA -> `SafeWindowDTO` |
| `dto.py`, `release_source.py`, `request_trace.py`, `frenet.py` | Hợp đồng Pydantic DTO công khai (`RouteIncidentDTO` + `polylines`), kiểm tra release artifact, ghi trace JSONL opt-in | Python objects -> JSON schema |

## Cách kiểm thử

```bash
python -m pytest tests/module_3/test_speed_poller_and_feedback.py tests/module_3/test_eta_validation_protocol.py tests/module_3/test_timbus_station_state_regressions.py --basetemp=runtime/pytest_tmp -q
```
