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
        HMM["Speed Layer: RouteHMM (Viterbi nhân quả)\n(dùng ShapeProjectionModel từ route_matcher.py)"]
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
        CHK_BASE{"Tuyến có Baseline khả dụng?"}
        BASE["Fallback: baseline_eta_p50_sec"]
        OOS["Trả về: Tuyến nằm ngoài phạm vi dự báo ETA"]
        POL["eta_policy (P1-P10, proximity cap, SafeWindowDTO)"]
        API["FastAPI Web Demo (/api/station-eta, /api/live-buses)"]
    end

    BM & TB --> MERGE --> HMM --> GUARD --> CAUSAL
    SQL --> CAUSAL
    INC --> CAUSAL
    CAUSAL --> MR --> CHECK
    CHECK -->|"Có"| XGB --> POL
    CHECK -->|"Không"| CHK_BASE
    CHK_BASE -->|"Có"| BASE --> POL
    CHK_BASE -->|"Không"| OOS --> API
    POL --> API
```

## 2. Hợp đồng xử lý & Chính sách ổn định

| Thành phần | Trách nhiệm | Ghi chú thiết kế |
| --- | --- | --- |
| `live_feed.py` | Gọi BusMap API, cache RAM theo tuyến, parse thời gian ping (`parse_ping_epoch`) | Tránh gọi lặp liên tục khi nhiều client hỏi cùng tuyến |
| `TimBusClient` | Truy vấn GPS thời gian thực theo biển số/tuyến (`_sync_and_merge_timbus`) | Bù trễ và bổ sung tốc độ thực tế khi BusMap đứng nhịp |
| `RouteHMM` (Speed Layer) | Chiếu & lọc quỹ đạo nhân quả trên 1D Frenet (`s_m`, `cross_track_m`) theo Viterbi | Dùng chung `route_matcher.py` (Batch dùng `horizon=300.0`) |
| `BusMapServingService` | Duy trì `_passed_station_plates` (pass guard), `_tb_last_valid`, `_causal` | Đảm bảo xe đã qua trạm không bị hồi sinh bởi cache cũ |
| `CausalFeatures` | Cập nhật quan sát từng xe (`_observe_causal_snapshot`) và xuất 36 features | Dùng chung 100% logic với lúc train (`step_3_2/causal_eta.py`) |
| `ModelRuntime` | Nạp `data/models/causal_eta_v1/`, kiểm tra `_known_routes`, dự báo residual + baseline | Nếu ngoài `_known_routes` nhưng tuyến có baseline thì fallback baseline; nếu cả hai đều không có, trả thông báo ngoài phạm vi ETA |
| `eta_policy.py` | Ổn định hiển thị ETA (làm tròn, cửa sổ an toàn `SafeWindowDTO`, giới hạn gần trạm) | Tránh nhảy ETA bất thường khi xe dừng đèn đỏ sát trạm |

## 3. Giới hạn & Cơ chế Fallback

- `TimBusClient` phụ thuộc API ngoài `timbus.vn`; khi nguồn TimBus mất kết nối hoặc trễ, hệ thống tự fallback về BusMap thuần.
- `_observe_causal_snapshot` dùng `_causal_lock` để đảm bảo đồng bộ luồng khi cập nhật trạng thái đội xe.
- Giao diện web demo (`step_3_5_web_demo/static/`) giữ hợp đồng API chuẩn, không phụ thuộc chế độ hiển thị ở client.

## 4. Sơ đồ Logic Xử lý Thời gian thực (Hybrid Merge, RouteHMM, Pass Guard & ETA Policy)

```mermaid
flowchart TD
    REQ["Request GET /api/station-eta\n(route_id, direction, station_order)"] --> ORD0{"station_order == 0?"}
    ORD0 -->|"Đúng"| END0["Trả về: Trạm đầu bến\n(xuất bến theo nốt)"]
    ORD0 -->|"Sai"| FEAS{"_is_route_eta_feasible?\n(trong baseline_routes HOẶC _known_routes)"}
    FEAS -->|"Sai"| OOS["Trả về: Tuyến nằm ngoài phạm vi dự báo ETA"]
    FEAS -->|"Đúng"| FETCH["Lấy BusMap Live (RAM cache)\n+ TimBus Central API"]

    FETCH --> MERGE["Trộn theo biển số (_sync_and_merge_timbus)\nƯu tiên ping mới hơn + _tb_last_valid\n+ MacroSpeedTracker EMA"]
    MERGE --> HMM["RouteHMM (Viterbi nhân quả)\nEmission (cross_track Gaussian)\n+ Transition (hướng tiếp tuyến & tiến độ ds)"]
    HMM --> GUARD{"Pass Guard & Lọc hợp lệ:\ncross_track <= 35m, đúng hướng,\ns_now <= s_target, chưa nằm trong _passed_station_plates?"}
    GUARD -->|"Sai"| SKIP["Loại xe & ghi nhận đã qua trạm\n(chống hồi sinh từ cache cũ)"]
    GUARD -->|"Đúng"| CAUSAL["Khóa _causal_lock -> Cập nhật đội xe\nTrích 36 biến CausalFeatures + Silver Incidents"]

    CAUSAL --> KNOWN{"route_id_idx thuộc\n_known_routes của ModelRuntime?"}
    KNOWN -->|"Đúng"| ML["eta_p50 = max(5.0,\nbaseline_p50 + XGBoost_residual)"]
    KNOWN -->|"Sai"| BASE["eta_p50 = baseline_eta_p50_sec"]

    ML & BASE --> POL["eta_policy (P1-P10):\n1. compute_proximity_capped_etas\n2. Buffer LINEX: delta = kappa(d)*(alpha*sigma + beta*hb + gamma*eta)\n3. Lượng tử hóa SafeWindowDTO [optimistic, conservative]"]
    POL --> RESP["Trả về StationEtaResponse JSON"]
```
