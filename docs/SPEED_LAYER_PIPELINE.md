# Speed Layer Pipeline (Speed Layer Poller — Thu thập & Làm ấm RAM)

- **Trạng thái:** Current
- **Phạm vi:** Tầng Speed Layer (`SpeedLayerPoller`) chạy nền theo chu kỳ `45s` chỉ làm nhiệm vụ **thu thập và lưu ấm trạng thái** vào RAM chung (`_tb_last_valid`, `OnlineFeatureExtractor`, `RouteHMM`, `CausalFeatures`) để chống cold-start. Toàn bộ bước lọc theo trạm, dự báo ML và tính ETA do [docs/SERVING_LAYER_PIPELINE.md](SERVING_LAYER_PIPELINE.md) đảm nhiệm.
- **Nguồn sự thật (Code paths):** `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/speed_poller.py`, `module_3_bus_eta_prediction/step_3_2_feature_store_extractor/causal_eta.py`, `module_1_data_ingestion_and_preprocessing/step_1_4_frenet_spatial_projection/route_matcher.py`, `experiments/timbus/timbus_tracker.py`.

## 1. Sơ đồ Luồng Dữ liệu (Data Flow)

```mermaid
flowchart TD
    subgraph UP["1. Nguồn trực tuyến"]
        BM["BusMap route_bus_gps\n(48 tuyến baseline x 2 chiều)"]
        TB["TimBus Central API\n(anchors[:1], 2 workers dàn trải)"]
    end

    subgraph POLLER["2. SpeedLayerPoller (speed_poller.py)"]
        P1["ingest_speed_layer_vehicles\n(cập nhật toàn tuyến)"]
        P2["ingest_speed_layer_timbus_hit\n(trám xe trễ/mất)"]
    end

    subgraph RAM["3. RAM chung (Single-Process --workers 1)"]
        EXT["OnlineFeatureExtractor + RouteHMM"]
        CF["CausalFeatures (36 biến, threading.RLock)"]
        TBV["_tb_last_valid (chia sẻ với Serving qua _tb_lock)"]
        HL["Health Snapshot (/api/health)"]
    end

    BM --> P1 --> EXT & CF
    TB --> P2 --> TBV & EXT & CF
    POLLER --> HL
```

## 2. Sơ đồ Luồng Logic (Logic Flow)

```mermaid
flowchart TD
    CLK["Vòng lặp chu kỳ 45s\n(app.py lifespan)"] --> HRS{"Trong giờ hoạt động?\n(04:45 - 22:30 giờ Hà Nội)"}
    HRS -->|"Ngoài giờ"| SLEEP["ĐÓNG hoàn toàn\n(không gọi BusMap/TimBus)"]
    HRS -->|"Trong giờ"| PH1["Phase 1: Gọi BusMap route_bus_gps\n48 tuyến x 2 chiều & lưu ấm RAM"]

    PH1 --> TRIG{"Trên tuyến TimBus:\nxe có age >= 60s hoặc mất giữa tuyến?\n(Bỏ qua xe Serving vừa focus < 45s\nvà xe đang trong cooldown)"}
    TRIG -->|"Không"| DONE["Ghi end_ts & cập nhật /api/health"]
    TRIG -->|"Có"| CB{"Circuit Breaker\nđang OPEN (90s)?"}
    CB -->|"Đúng"| DONE
    CB -->|"Sai"| PH2["Phase 2: TimBus Gap-Filler\n2 workers dàn trải (stagger 0.15s)"]

    PH2 --> CLS{"Phân loại 4 trạng thái"}
    CLS -->|"Hit hợp lệ"| REC["RECOVERED_LIVE\nLưu _tb_last_valid + CausalFeatures\ncooldown = 0s, reset error_streak"]
    CLS -->|"Miss + spd=0 +\n(ct>35m hoặc gần bến <=300m)"| PARK["TERMINAL_OR_DEPOT_PARKED\ncooldown = 180s"]
    CLS -->|"Miss + đang bám tuyến"| ONCOR["ON_CORRIDOR_GAP\ncooldown = 45s + ghi gap_routes_top"]
    CLS -->|"Timeout / Lỗi mạng"| ERR["UPSTREAM_ERROR\nerror_streak >= 3 -> mở Circuit 90s"]
    REC & PARK & ONCOR & ERR --> DONE
```

## 3. Thiết kế Đồng bộ & Ràng buộc Vận hành

| Thành phần | Trách nhiệm | Ghi chú thiết kế |
| --- | --- | --- |
| `SpeedLayerPoller` | Quét BusMap `route_query` mỗi `45s` + 2-worker TimBus gap-fill cho xe `age >= 60s` | Đóng hoàn toàn `22:30–04:45`; tắt được qua `DISABLE_SPEED_POLLER=1` khi chạy test |
| Chia sẻ `_tb_last_valid` | Đọc biển số Serving vừa focus `< 45s` để tránh gọi trùng; nạp hit mới lại cho Serving | Đồng bộ thread-safe qua `_tb_lock` |
| `CausalFeatures` | Bảo vệ trạng thái bằng `threading.RLock` + `_causal_lock` | Yêu cầu chạy `uvicorn --workers 1` để Speed và Serving dùng chung 1 RAM |
| Serving Layer (lọc & ETA) | Thực hiện toàn bộ lọc trạm, Pass Guard, `ModelRuntime` và `eta_policy` | Xem chi tiết tại [docs/SERVING_LAYER_PIPELINE.md](SERVING_LAYER_PIPELINE.md) |
