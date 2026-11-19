# Batch Layer Pipeline (Luồng Xử lý Lô & Huấn luyện)

- **Trạng thái:** Current
- **Phạm vi:** Đường ống xử lý dữ liệu lịch sử đi qua **HDFS (Bronze – Silver – Gold)**, hứng kết quả tổng hợp vào SQLite nền nhẹ và huấn luyện mô hình `causal-eta.v1`.
- **Nguồn sự thật (Code paths):** `config/system_config.py`, `module_1_data_ingestion_and_preprocessing/step_1_3_*`, `step_1_4_*`, `step_1_5_*`, `module_2_big_data_storage_and_lakehouse/step_2_4_hdfs_history/`, `module_3_bus_eta_prediction/step_3_1_*`, `step_3_2_*`, `step_3_3_*`.

## 1. Sơ đồ Luồng Dữ liệu (Data Flow)

```mermaid
flowchart TD
    subgraph IN["1. Nguồn dữ liệu & GTFS chuẩn"]
        HF["Hugging Face Raw Batches (bus, incidents)"]
        GTFS["data/ground_truth/busmap_canonical/"]
    end

    subgraph BR["2. HDFS Bronze & Chuẩn hóa đầu vào"]
        SAN["step_1_3: telemetry_sanitizer.py & contract.py"]
        HBR["HDFS Bronze (/bus-eta/v1/bronze/hf_raw)\n(hf_bronze.py, spool.py, receipt.py SHA-256)"]
        S15["step_1_5: ingest_busmap_canonical.py"]
    end

    subgraph SG["3. HDFS Silver & Gold"]
        P2["Spark P2 & step_1_4: p2_transform.py + projection_boundary.py\n(Frenet 1D, cross_track_m <= 35m, trip_segmenter)"]
        HSIL["HDFS Silver P2 Snapshots (Telemetry & Incidents)"]
        S31["step_3_1: baseline_matrix_builder.py"]
        HGOLD["HDFS Gold (agg_segment_travel_times & eta_snapshot.py)"]
        SQL["SQLite (hanoi_bus_system.db): GTFS tĩnh + Hứng Gold Baseline"]
    end

    subgraph ML["4. Trích xuất Đặc trưng & Huấn luyện ML"]
        DA["DataAccess (GTFS + Gold Baseline)"]
        CF["step_3_2: CausalFeatures (36 biến nhân quả)"]
        REP["step_3_3: TrainingReplay + silver_replay_trainer.py"]
        XGB["Residual XGBoost: residual = actual_eta - baseline_p50"]
        ART["data/models/causal_eta_v1/ (model.json + manifest.json)"]
    end

    HF --> SAN --> HBR
    GTFS --> S15 --> SQL
    SQL -->|"canonical_shapes & stations"| P2
    HBR --> P2 --> HSIL
    HSIL -->|"Train/Test Split"| S31 --> HGOLD
    HGOLD -->|"Hứng kết quả Gold"| SQL
    HGOLD -->|"baseline_eta_*"| DA
    SQL -->|"GTFS Metadata"| DA
    DA --> CF
    HSIL -->|"Silver Telemetry theo ngày/tuyến"| REP
    CF --> REP --> XGB --> ART
```

## 2. Sơ đồ Luồng Logic (Logic Flow)

```mermaid
flowchart TD
    IN["Raw Ping (vid, lat, lon, speed, dir, ts)"] --> BBOX{"Trong HANOI_BBOX?\n19.50<=lat<=22.50\n104.50<=lon<=107.50"}
    BBOX -->|"Sai"| OOB["Gắn OUT_OF_BOUNDS\n(KHÔNG cập nhật kinematic_cache)"]
    BBOX -->|"Đúng"| DT{"dt = ts - prev_ts > 0?"}
    DT -->|"Sai"| STALE["Gắn STALE_PING"]
    DT -->|"Đúng"| VCALC{"dist >= 250.0m &\nv_calc > 80.0 km/h?"}
    VCALC -->|"Đúng"| DRIFT["Gắn GPS_DRIFT_JUMP\n(KHÔNG cập nhật kinematic_cache)"]
    VCALC -->|"Sai"| DEPOT{"dist < 15.0m &\n(dir==0 hoặc route<=0)?"}
    DEPOT -->|"Đúng"| IDLE["Gắn IDLE_DEPOT"]
    DEPOT -->|"Sai"| ACT["Gắn ACTIVE_VALID\n& cập nhật kinematic_cache"]

    ACT --> SEG{"Kiểm tra ngắt chuyến:\ndt > 300s (không đủ nối detour 1800s)\nHOẶC lùi > 200m / terminal reset?"}
    SEG -->|"Có"| NEWTRIP["Tách Trip mới +\ntrim_terminal_stationary_ends()"]
    SEG -->|"Không"| SAME["Nối vào Trip hiện tại"]

    NEWTRIP & SAME --> FRENET["Chiếu 1D Frenet (ShapeProjectionModel)\n(lat, lon) -> (s_bus_m, cross_track_m)"]
    FRENET --> CORR{"cross_track_m <= 35.0m?"}
    CORR -->|"Sai"| DROP["Loại khỏi Silver Corridor"]
    CORR -->|"Đúng"| SILVER["Lưu HDFS Silver P2\n(khử trùng lặp canonical_event_id)"]

    SILVER --> BRACKET["Nội suy giao cắt trạm (Bracketed Crossing)\nLọc segment_tt <= 1800s & N >= 5"]
    BRACKET --> GOLD["Gold Baseline Matrix\n(p10, p50, p90, mean, std theo route/dir/seg/day_type/hour)"]

    SILVER -->|"Replay đơn điệu theo thời gian"| PREFIX["CausalFeatures (36 biến)\nchỉ dùng tiền tố quan sát quá khứ"]
    GOLD -->|"baseline_eta_p50_sec + prior"| PREFIX
    PREFIX --> RESID["Target = eta_actual - baseline_eta_p50_sec\nSample Weight cân bằng theo (route, journey, target)"]
    RESID --> XGB["Huấn luyện XGBRegressor (reg:absoluteerror)\nTemporal Split: Train / Validation / Test -> causal-eta.v1"]
```

## 3. Hợp đồng dữ liệu & Các bước thực thi

| Bước | Module / Symbol | Đầu vào -> Đầu ra | Ràng buộc chính (SSOT) |
| --- | --- | --- | --- |
| 0. Nạp GTFS chuẩn | `step_1_5_busmap_canonical_migration/ingest_busmap_canonical.py` | `busmap_canonical/*` -> `canonical_routes`, `canonical_shapes`, `canonical_stations` | Chiếu trạm lên `s_station_m` trong SQLite |
| 1. Nhập HDFS Bronze | `step_2_4_hdfs_history` (`hf_bronze.py`, `spool.py`, `receipt.py`, `contract.py`) | HF Raw + `telemetry_sanitizer.py` -> HDFS `/bus-eta/v1/bronze/hf_raw` | Bất biến, SHA-256, `HANOI_BBOX` 4 biên (`19.50..22.50`, `104.50..107.50`), `GPS_DRIFT_MIN_DIST_M = 250.0m`, `OUT_OF_BOUNDS` không ghi cache |
| 2. HDFS Silver P2 | `step_2_4` (`p2_transform.py`, `history_execution.py`) & `step_1_4` (`projection_boundary.py`, `route_matcher.py`) | HDFS Bronze -> HDFS Silver P2 | `RouteHMM(horizon=300.0)`, lọc `cross_track_m <= 35.0m`, `MAX_BACKWARD_RESET_M = 200.0m` |
| 3. HDFS Gold Baseline | `step_3_1_historical_baseline_model/baseline_matrix_builder.py` & `step_2_4/eta_snapshot.py` | HDFS Silver + `train_test_split_v1.json` -> HDFS Gold & SQLite baseline | `MIN_SAMPLES_FOR_BASELINE = 5`, `MAX_SEGMENT_TRAVEL_TIME_SEC = 1800.0` |
| 4. Huấn luyện ML | `step_3_3_machine_learning_models/silver_replay_trainer.py` | HDFS Silver + Gold Baseline + `CausalFeatures` -> `data/models/causal_eta_v1/` | 36 features nhân quả, residual XGBoost |
