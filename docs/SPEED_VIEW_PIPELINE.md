# Speed View Pipeline (Luồng Thời gian thực & Serving ETA)

- **Trạng thái:** Current
- **Phạm vi:** Luồng lấy dữ liệu trực tuyến từ BusMap + TimBus + sự cố TomTom, khớp tuyến nhân quả (`RouteHMM`), trích xuất 36 biến `CausalFeatures`, dự báo `ModelRuntime` (`causal-eta.v1`) và phục vụ API.
- **Nguồn sự thật (Code paths):** `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/` (`serving_service.py`, `live_feed.py`, `data_access.py`, `model_runtime.py`, `eta_policy.py`, `dto.py`), `module_1_data_ingestion_and_preprocessing/step_1_4_frenet_spatial_projection/route_matcher.py`, `experiments/timbus/timbus_tracker.py`.

## 1. Sơ đồ luồng Speed View

```mermaid
flowchart TD
    subgraph LIVE["1. Nguồn dữ liệu trực tuyến"]
        BM["BusMap Live API (live_feed.py, cache RAM)"]
        TB["TimBus Central API (TimBusClient)"]
    end

    subgraph MATCH["2. Hợp nhất, Chiếu tuyến & Guard"]
        MERGE["BusMapServingService._sync_and_merge_timbus"]
        HMM["step_1_4: ShapeProjectionModel + RouteHMM (Viterbi nhân quả)"]
        GUARD["Pass Guard (_passed_station_plates) & _tb_last_valid"]
    end

    subgraph FEAT["3. Trạng thái Đội xe & Đặc trưng"]
        CAUSAL["CausalFeatures (36 biến, bảo vệ bởi _causal_lock)"]
        SQL["SQLite (GTFS tĩnh + Gold Baseline)"]
        INC["Silver TomTom Incidents (IncidentsProvider)"]
    end

    subgraph PRED["4. Suy luận ETA & Chính sách ổn định"]
        MR["ModelRuntime.predict_p50 (causal-eta.v1)"]
        CHECK{"route_id_idx thuộc _known_routes?"}
        XGB["max(5.0, baseline_p50 + residual_XGBoost)"]
        BASE["Fallback: baseline_eta_p50_sec"]
        POL["eta_policy (P1-P10, proximity cap, SafeWindowDTO)"]
        API["FastAPI Web Demo (/api/station-eta, /api/live-buses)"]
    end

    BM & TB --> MERGE --> HMM --> GUARD --> CAUSAL
    SQL --> CAUSAL
    INC --> CAUSAL
    CAUSAL --> MR --> CHECK
    CHECK -->|"Có"| XGB --> POL
    CHECK -->|"Không"| BASE --> POL
    POL --> API
```

## 2. Hợp đồng xử lý & Chính sách ổn định

| Thành phần | Trách nhiệm | Ghi chú thiết kế |
| --- | --- | --- |
| `live_feed.py` | Gọi BusMap API, cache RAM theo tuyến, parse thời gian ping (`parse_ping_epoch`) | Tránh gọi lặp liên tục khi nhiều client hỏi cùng tuyến |
| `TimBusClient` | Truy vấn GPS thời gian thực theo biển số/tuyến (`_sync_and_merge_timbus`) | Bù trễ và bổ sung tốc độ thực tế khi BusMap đứng nhịp |
| `route_matcher.py` (`RouteHMM`) | Chiếu tọa độ GPS lên 1D Frenet (`s_m`, `cross_track_m`) theo Viterbi nhân quả | Không I/O, dùng chung giữa replay và serving |
| `BusMapServingService` | Duy trì `_passed_station_plates` (pass guard), `_tb_last_valid`, `_causal` | Đảm bảo xe đã qua trạm không bị hồi sinh bởi cache cũ |
| `CausalFeatures` | Cập nhật quan sát từng xe (`_observe_causal_snapshot`) và xuất 36 features | Dùng chung 100% logic với lúc train (`step_3_2/causal_eta.py`) |
| `ModelRuntime` | Nạp `data/models/causal_eta_v1/`, kiểm tra `_known_routes`, dự báo residual + baseline | Trả `None` để fallback baseline nếu tuyến ngoài miền train |
| `eta_policy.py` | Ổn định hiển thị ETA (làm tròn, cửa sổ an toàn `SafeWindowDTO`, giới hạn gần trạm) | Tránh nhảy ETA bất thường khi xe dừng đèn đỏ sát trạm |

## 3. Giới hạn & Cơ chế Fallback

- `TimBusClient` phụ thuộc API ngoài `timbus.vn`; khi nguồn TimBus mất kết nối hoặc trễ, hệ thống tự fallback về BusMap thuần.
- `_observe_causal_snapshot` dùng `_causal_lock` để đảm bảo đồng bộ luồng khi cập nhật trạng thái đội xe.
- Giao diện web demo (`step_3_5_web_demo/static/`) giữ hợp đồng API chuẩn, không phụ thuộc chế độ hiển thị ở client.
