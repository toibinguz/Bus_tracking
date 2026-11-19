# Tài liệu Module Thu thập Dữ liệu (Crawler)

- **Trạng thái:** Current
- **Phạm vi:** Cloud Crawler 24/7 trên GitHub Actions, Local Crawler, TomTom Incidents, làm mới danh mục xe đầu ngày và đồng bộ lên Hugging Face Dataset.
- **Nguồn sự thật (Code paths):** `.github/workflows/crawl_bus.yml`, `scripts/cloud_crawler_step.py`, `module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/`, `config/system_config.py`.

## 1. Sơ đồ hoạt động Crawler 24/7

```mermaid
flowchart TD
    GHA["GitHub Actions (.github/workflows/crawl_bus.yml)"] -->|"9 phút/phiên, cron dự phòng 2h"| RUN["cloud_crawler_runner.py"]
    RUN -->|"05:00-07:00"| CAT["catalog_refresher.py (Làm mới & push data/metadata/)"]
    RUN -->|"05:00-22:00"| BUS["Micro-batch 15 xe (socket_client.py + device_pool.py)"]
    RUN -->|"~13.5 phút/lần"| TOM["incident_client.py (TomTom Incidents)"]
    BUS --> SAN["telemetry_sanitizer.py"]
    SAN --> HF["hf_lake_sync.py -> Hugging Face (Toibinguz/hust-bus-data)"]
    TOM --> HF
    RUN -->|"Self-Trigger Next Run"| GHA
```

## 2. Thành phần & Tham số SSOT

| Thành phần / Hằng số | Giá trị / Vai trò |
| --- | --- |
| Workflow `crawl_bus.yml` | `concurrency: hust-bus-crawler-relay` (`cancel-in-progress: false`), `timeout-minutes: 15`, tự gọi `dispatches` để nối phiên 24/7 |
| `SESSION_DURATION_SEC` | `540` giây (9 phút mỗi phiên); ngoài giờ `05:00–22:00` crawler ngủ đủ 540s để giữ nhịp relay mà không gọi API |
| `BUS_POLL_INTERVAL_SEC` / `BUS_MICRO_BATCH_SIZE` | `75s` mỗi vòng / `15` xe mỗi micro-batch |
| `socket_client.py` | Raw SSL socket HTTP/1.1, hỗ trợ `Transfer-Encoding: chunked`, DNS cache có `_IP_CACHE_LOCK`, thread timeout `4.2s` |
| `catalog_refresher.py` | Chỉ phân loại `"DEPOT"` khi ở ngoài hành trình hợp lệ và chỉ xóa xe khi `status == "ERROR"` |
| `incident_client.py` | Chỉ gọi TomTom Incidents (`MAX_TOMTOM_INCIDENT_DAILY = 85`, `MAX_TOMTOM_INCIDENT_MONTHLY = 2400`); TomTom Flow đã được gỡ bỏ |
| `hf_lake_sync.py` | Upload qua Hugging Face Commit API vào `raw_data/YYYY-MM-DD/{bus,incidents}/batch_HHMMSS.jsonl` |

## 3. Cách kiểm thử & Vận hành

```bash
# Chạy thử 1 vòng đầy đủ cục bộ (không đẩy Hugging Face, không gọi TomTom)
python scripts/cloud_crawler_step.py --test --no-tomtom

# Làm mới danh mục xe thủ công
python scripts/daily_catalog_refresh.py
```
