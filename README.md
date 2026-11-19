# Hệ thống Theo dõi Xe buýt Hà Nội, Lưu trữ Lakehouse & Dự báo ETA

- **Phiên bản kiến trúc:** Kiến trúc Lambda (Batch View + Speed View)
- **Đầu vào:** BusMap API, TimBus Central API (`experiments/timbus/`), TomTom Incidents API, dữ liệu GTFS chuẩn (`data/ground_truth/busmap_canonical/`)
- **Đầu ra:** SQLite (`data/hanoi_bus_system.db`), Medallion Lakehouse Parquet (`data/lakehouse/`), HDFS (`step_2_4_hdfs_history/`), mô hình `causal-eta.v1` (`data/models/causal_eta_v1/`), Web Demo FastAPI (`step_3_5_web_demo/`)

## Sơ đồ kiến trúc tổng quan

```mermaid
flowchart LR
    A["BusMap / TimBus / TomTom Incidents"] --> B["Module 1: Crawler & Preprocessing"]
    B -->|"Batch JSONL (HF / data/raw)"| C["Module 2: SQLite + Parquet Lakehouse + HDFS"]
    C -->|"Silver / Gold Parquet"| D["Module 3: Baseline + CausalFeatures + XGBoost"]
    A -->|"Live Feed + HMM Projection"| E["Speed View: BusMapServingService + ModelRuntime"]
    D -->|"causal-eta.v1"| E
    E --> F["Web Demo FastAPI (/api/station-eta, /api/live-buses)"]
```

## Cấu trúc thư mục & Tài liệu chi tiết

| Thành phần | Tài liệu |
| --- | --- |
| Luồng Batch View | [docs/BATCH_VIEW_PIPELINE.md](docs/BATCH_VIEW_PIPELINE.md) |
| Luồng Speed View (Live) | [docs/SPEED_VIEW_PIPELINE.md](docs/SPEED_VIEW_PIPELINE.md) |
| Thu thập dữ liệu (Crawler) | [docs/CRAWLER.md](docs/CRAWLER.md) |
| Tiền xử lý & Chiếu Frenet/HMM | [docs/PREPROCESSING.md](docs/PREPROCESSING.md) |
| Lưu trữ HDFS & Lakehouse (B-S-G) | [docs/HDFS_LAKEHOUSE.md](docs/HDFS_LAKEHOUSE.md), [docs/HDFS_RUNBOOK.md](docs/HDFS_RUNBOOK.md) |
| Mô hình dự báo ETA | [docs/ETA_MODEL.md](docs/ETA_MODEL.md) |
| Web Demo & Tích hợp TimBus | [docs/DEMO_APP.md](docs/DEMO_APP.md), [experiments/timbus/README.md](experiments/timbus/README.md) |
| Module 1, 2, 3 | [Module 1](module_1_data_ingestion_and_preprocessing/README.md), [Module 2](module_2_big_data_storage_and_lakehouse/README.md), [Module 3](module_3_bus_eta_prediction/README.md) |
| CLI Entrypoints & Ops Runners | [scripts/README.md](scripts/README.md) |
| Đề xuất học thuật | [academic_proposal/](academic_proposal/) |

## Tham số SSOT (`config/system_config.py`)

- `DEFAULT_DB_PATH = "data/hanoi_bus_system.db"`, `DEFAULT_LAKEHOUSE_ROOT = "data/lakehouse"`
- `HANOI_BBOX`: `19.50..22.50` lat, `104.50..107.50` lon (bao phủ vùng liên tỉnh miền Bắc)
- `MAX_CORRIDOR_CROSS_TRACK_M = 35.0`, `TERMINAL_STATIONARY_TOL_M = 50.0`
- `SESSION_DURATION_SEC = 540` (phiên cloud crawler 9 phút), `BUS_POLL_INTERVAL_SEC = 75`

## Cách chạy & Kiểm thử

```bash
# Chạy Web Demo (FastAPI)
uvicorn module_3_bus_eta_prediction.step_3_5_web_demo.app:app --host 0.0.0.0 --port 8000

# Thử nghiệm Cloud Crawler cục bộ (1 vòng, không đẩy Hugging Face)
python scripts/cloud_crawler_step.py --test --no-tomtom

# Chạy toàn bộ bộ kiểm thử
python -m pytest tests/ --basetemp=runtime/pytest_tmp -q
```
