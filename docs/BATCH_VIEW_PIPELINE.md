# Batch View Pipeline (Luồng Xử lý Lô & Huấn luyện)

- **Trạng thái:** Current
- **Phạm vi:** Đường ống xử lý dữ liệu lịch sử đi qua **HDFS (Bronze – Silver – Gold)**, hứng kết quả tổng hợp vào SQLite nền nhẹ và huấn luyện mô hình `causal-eta.v1`.
- **Nguồn sự thật (Code paths):** `config/system_config.py`, `module_1_data_ingestion_and_preprocessing/step_1_3_*`, `step_1_4_*`, `step_1_5_*`, `module_2_big_data_storage_and_lakehouse/step_2_4_hdfs_history/`, `module_3_bus_eta_prediction/step_3_1_*`, `step_3_2_*`, `step_3_3_*`.

## 1. Sơ đồ luồng Batch View

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

## 2. Hợp đồng dữ liệu & Các bước thực thi

| Bước | Module / Symbol | Đầu vào -> Đầu ra | Ràng buộc chính (SSOT) |
| --- | --- | --- | --- |
| 0. Nạp GTFS chuẩn | `step_1_5_busmap_canonical_migration/ingest_busmap_canonical.py` | `busmap_canonical/*` -> `canonical_routes`, `canonical_shapes`, `canonical_stations` | Chiếu trạm lên `s_station_m` trong SQLite |
| 1. Nhập HDFS Bronze | `step_2_4_hdfs_history` (`hf_bronze.py`, `spool.py`, `receipt.py`, `contract.py`) | HF Raw + `telemetry_sanitizer.py` -> HDFS `/bus-eta/v1/bronze/hf_raw` | Bất biến, băm SHA-256, `HANOI_BBOX` 4 biên (`19.50..22.50`, `104.50..107.50`), `TERMINAL_STATIONARY_TOL_M = 50.0m` |
| 2. HDFS Silver P2 | `step_2_4` (`p2_transform.py`, `history_execution.py`) & `step_1_4` (`projection_boundary.py`, `route_matcher.py`) | HDFS Bronze -> HDFS Silver P2 | Lọc `cross_track_m <= 35.0m`, `MAX_BACKWARD_JITTER_M = 120.0m` |
| 3. HDFS Gold Baseline | `step_3_1_historical_baseline_model/baseline_matrix_builder.py` & `step_2_4/eta_snapshot.py` | HDFS Silver + `train_test_split_v1.json` -> HDFS Gold & SQLite baseline | `MIN_SAMPLES_FOR_BASELINE = 5`, `MAX_SEGMENT_TRAVEL_TIME_SEC = 1800.0` |
| 4. Huấn luyện ML | `step_3_3_machine_learning_models/silver_replay_trainer.py` | HDFS Silver + Gold Baseline + `CausalFeatures` -> `data/models/causal_eta_v1/` | 36 features nhân quả, residual XGBoost |
