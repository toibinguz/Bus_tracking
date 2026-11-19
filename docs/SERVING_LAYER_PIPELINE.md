# Serving Layer Pipeline (Luồng Dữ liệu & Logic Phục vụ ETA)

- **Trạng thái:** Current
- **Phạm vi:** Tầng phục vụ request thời gian thực (`BusMapServingService`): tiếp nhận trạng thái đã làm ấm từ Speed Layer, gọi BusMap route-query trực tiếp + TimBus Focus `5s`, lọc/chiếu tuyến, suy luận `ModelRuntime` (`causal-eta.v1`), áp dụng `eta_policy` và trả DTO phản hồi tường minh.
- **Nguồn sự thật (Code paths):** `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/` (`serving_service.py`, `live_feed.py`, `data_access.py`, `model_runtime.py`, `eta_policy.py`, `dto.py`, `request_trace.py`), `experiments/timbus/timbus_tracker.py`.
- **Liên quan:** [docs/SPEED_LAYER_PIPELINE.md](SPEED_LAYER_PIPELINE.md) (Speed Layer Poller), [docs/DEMO_APP.md](DEMO_APP.md) (Web UI & API).

## 1. Sơ đồ Luồng Dữ liệu (Data Flow)

```mermaid
flowchart TD
    subgraph SRC["1. Nguồn đầu vào Live, RAM & Tĩnh"]
        BM["BusMap route_bus_gps (live_feed.py, cache 15s)"]
        TB["TimBus Central API (TimBusClient Focus 5s)"]
        RAM["RAM chung từ Speed Layer (_tb_last_valid, CausalFeatures, RouteHMM)"]
        SQL["SQLite (GTFS tĩnh + Gold Baseline)"]
        INC["Silver TomTom Incidents (Parquet)"]
        MOD["data/models/causal_eta_v1/ (model.json + manifest.json)"]
    end

    subgraph PROC["2. Xử lý trong BusMapServingService"]
        DTO_RAW["BusVehicleDTO (+ busmap_updated_at)"]
        FEAT["Vector 36 CausalFeatures + Baseline p10/p50/p90"]
        ETA["ApproachingBusDTO + SafeWindowDTO (P10/P50/P90, B, Delay)"]
    end

    subgraph OUT["3. Đầu ra API & Trace"]
        RES_LIVE["RouteLiveResponse (/api/live-vehicles)"]
        RES_ETA["StationEtaResponse (/api/station-eta)"]
        TRC["trace.jsonl (ETA_TRACE_DIR opt-in)"]
    end

    BM & TB --> DTO_RAW
    RAM <-->|"Đọc/cập nhật qua Lock"| DTO_RAW
    DTO_RAW --> RES_LIVE
    DTO_RAW & SQL & INC --> FEAT
    FEAT & MOD --> ETA
    ETA --> RES_ETA & TRC
```

## 2. Sơ đồ Luồng Logic (Logic Flow — `/api/station-eta`)

```mermaid
flowchart TD
    REQ["GET /api/station-eta\n(route_id, direction, station_order)"] --> ORD0{"station_order == 0?"}
    ORD0 -->|"Đúng"| END0["Trả về: Trạm đầu bến\n(xuất bến theo nốt)"]
    ORD0 -->|"Sai"| FEAS{"_is_route_eta_feasible?\n(trong baseline_routes HOẶC _known_routes)"}
    FEAS -->|"Sai"| OOS["Trả về: Ngoài phạm vi dự báo ETA"]
    FEAS -->|"Đúng"| FETCH["live_feed.fetch_live_vehicles_for_route"]

    FETCH --> UPERR{"upstream_status ==\n'upstream_error'?"}
    UPERR -->|"Đúng"| ERR["Trả StationEtaResponse\nupstream_status='upstream_error'"]
    UPERR -->|"Sai"| TBCHK{"Tuyến hỗ trợ TimBus?"}
    TBCHK -->|"Có"| MERGE["_sync_route_both_directions\nTrộn biển số + _tb_last_valid + MacroSpeedTracker"]
    TBCHK -->|"Không"| HMM
    MERGE --> HMM["RouteHMM (_prepare_vehicle)\nChiếu 1D Frenet & kiểm tra hướng"]

    HMM --> GUARD{"Lọc xe & Pass Guard:\ncross_track <= 35m, đúng chiều,\ns_now <= s_target, chưa trong _passed_station_plates?"}
    GUARD -->|"Sai"| SKIP["Loại xe khỏi kết quả trạm\n& ghi _passed_station_plates"]
    GUARD -->|"Đúng"| CAUSAL["Đọc 36 CausalFeatures (RLock + _causal_lock)"]

    CAUSAL --> MLCHK{"ModelRuntime.predict_p50_with_reason\n== 'ok'?"}
    MLCHK -->|"Đúng"| ML["eta_p50 = max(5.0, baseline_p50 + residual)"]
    MLCHK -->|"Sai"| BASE["Fallback: baseline_eta_p50_sec\n+ gắn fallback_reason tường minh"]

    ML & BASE --> POL["eta_policy (P1-P10):\n1. compute_proximity_capped_etas\n2. Buffer LINEX (B) & Delay\n3. Lượng tử hóa SafeWindowDTO"]
    POL --> RESP["Trả StationEtaResponse JSON"]
```

## 3. Hợp đồng Thành phần & Phản hồi Tường minh

| Thành phần | Trách nhiệm | Ghi chú thiết kế |
| --- | --- | --- |
| `live_feed.py` | Gọi `fetch_route_buses_live_status`, lọc `HANOI_BBOX`, parse `lastUpdateTime` | Trả `upstream_status` (`ok \| empty \| upstream_error`) và không cache phản hồi lỗi |
| `TimBusClient` | `query_central_vehicles_with_status` trả `(results, ok_count, error_count, last_error)` | Phân biệt miss thường với lỗi mạng/timeout (`timbus_status`: `ok \| partial_error \| upstream_error \| unsupported`) |
| `serving_service.py` | Duy trì `_tb_last_valid`, `_passed_station_plates`, `MacroSpeedTracker` và lọc theo trạm | Lưu `busmap_updated_at` gốc song song với thời gian query TimBus (`updated_at` / `ping_time`) |
| `ModelRuntime` | Nạp `causal-eta.v1`, gọi `predict_p50_with_reason` | Trả kèm `fallback_reason` (`ok \| cold_start_causal \| model_unavailable \| unknown_route \| predict_error`) |
| `eta_policy.py` | Áp dụng P1–P10, proximity cap, tính `buffer_seconds` (đệm) và `delay_seconds` (trễ) | Xuất `SafeWindowDTO` gồm mốc lạc quan (`eta_core - B`), P50 và bảo thủ (`eta_core + B`) |
| `data_access.py` | Đọc GTFS/Baseline SQLite và sự cố TomTom Silver Parquet | Hỗ trợ release pointer qua `release_source.py` |

## 4. Kiểm thử

```bash
python -m pytest tests/module_3/test_speed_poller_and_feedback.py tests/module_3/test_timbus_hybrid_serving.py tests/module_3/test_timbus_station_state_regressions.py --basetemp=runtime/pytest_tmp -q
```
