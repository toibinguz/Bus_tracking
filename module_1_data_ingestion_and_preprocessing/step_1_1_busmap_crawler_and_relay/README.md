# Step 1.1: BusMap Crawler, TomTom Incidents & Hugging Face Relay

- **Vai trò:** Thu thập GPS xe buýt định kỳ 24/7 trên GitHub Actions hoặc máy local, lấy sự cố giao thông TomTom Incidents và đồng bộ batch lên Hugging Face.
- **Đầu vào:** `data/metadata/hust_cluster_config.json`, BusMap API, TomTom Incidents API (`TOMTOM_KEY`).
- **Đầu ra:** Batch JSONL (`raw_data/YYYY-MM-DD/{bus,incidents}/batch_HHMMSS.jsonl`) trên Hugging Face & `data/raw/`.

## Thành phần chính

| File / Symbol | Vai trò | Input -> Output |
| --- | --- | --- |
| `cloud_crawler_runner.py` (`main`) | Vòng lặp 9 phút trên GitHub Actions, cào micro-batch và gọi upload HF | `hust_cluster_config.json` -> Batch JSONL -> HF |
| `local_production_crawler.py` (`main`) | Crawler chạy cục bộ, hỗ trợ ghi JSONL + đẩy Bronze HDFS spool | `hust_cluster_config.json` -> `data/raw/` |
| `socket_client.py` (`get_busmap_ip`, `fetch_single_bus_raw`, `_decode_http_body`) | Raw SSL socket HTTP/1.1 client (hỗ trợ `Transfer-Encoding: chunked`, lock DNS cache) | `vehicle_id` -> Raw JSON dict |
| `device_pool.py` (`get_current_progressive_pool_size`, `get_busmap_device_id`) | Quản lý bể device ID lũy tiến tránh rate-limit | `vehicle_id` -> `device_id` |
| `incident_client.py` (`execute_tomtom_incident_poll`, `load_tomtom_quota_state`) | Poll TomTom Incidents có kiểm soát quota ngày/tháng (đã bỏ TomTom Flow) | `TOMTOM_KEY` -> Incident JSONL |
| `catalog_refresher.py` (`run_daily_catalog_refresh`, `audit_vehicle`) | Làm mới danh mục xe đầu ngày (`05:00–07:00`), chỉ prune xe `ERROR` | Route IDs -> `hust_cluster_config.json` |
| `hf_lake_sync.py` (`upload_batches_to_hf_native`, `push_latest_incidents_to_hf`, `fetch_latest_incidents_from_hf`) | Upload/tải batch và đồng bộ snapshot live `raw_data/latest_incidents.json` qua Hugging Face Commit API | Local JSONL <-> HF Dataset |
| `hdfs_bronze_adapter.py`, `local_partition_writer.py`, `dataset_sync.py` | Adapter đẩy Bronze spool, ghi phân vùng local, đồng bộ toàn bộ từ HF | Batches -> Local disk / HDFS spool |

## Tham số SSOT (`config/system_config.py`)

- `SESSION_DURATION_SEC = 540`, `BUS_POLL_INTERVAL_SEC = 75`, `BUS_MICRO_BATCH_SIZE = 15`
- `SOCKET_TIMEOUT_SEC = 2.5`, `SOCKET_RETRY_TIMEOUT_SEC = 1.2` (thread future timeout `4.2s`)
- `OPERATING_HOUR_START = 5`, `OPERATING_HOUR_END = 22`
- `MAX_TOMTOM_INCIDENT_DAILY = 80`, `MAX_TOMTOM_INCIDENT_MONTHLY = 2500`

## Cách chạy & Kiểm thử

```bash
python -m module_1_data_ingestion_and_preprocessing.step_1_1_busmap_crawler_and_relay.cloud_crawler_runner --test --no-tomtom
python -m pytest tests/module_1/test_crawler_hdfs_spool.py --basetemp=runtime/pytest_tmp -q
```
