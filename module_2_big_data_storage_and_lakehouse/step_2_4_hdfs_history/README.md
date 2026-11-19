# Step 2.4: Đường ống Lịch sử trên HDFS (`step_2_4_hdfs_history`)

- **Vai trò:** Lưu trữ bất biến (immutable) và xử lý lịch sử theo kiến trúc Bronze -> Silver -> Gold trên cụm HDFS / Spark qua WebHDFS, tách biệt khỏi luồng live serving.
- **Đầu vào:** Sanitized crawler batches (`contract.py`), Hugging Face raw batches (`hf_bronze.py`), dữ liệu chuẩn tuyến.
- **Đầu ra:** HDFS Bronze objects (`webhdfs.py`, `spool.py`, `receipt.py`), Silver P2 runs (`p2_transform.py`, `history_execution.py`), Gold ETA snapshots (`eta_snapshot.py`, `history_query.py`).

## Thành phần chính

| File / Symbol | Vai trò | Input -> Output |
| --- | --- | --- |
| `contract.py` (`TelemetryEnvelope`, `envelope_from_sanitized_record`) | Định nghĩa phong bì dữ liệu chuẩn Module 1 -> HDFS Bronze (`canonical_event_id`) | Sanitized dict -> `TelemetryEnvelope` |
| `spool.py`, `receipt.py`, `webhdfs.py` | Spool JSONL theo giờ (`hour_partition`), băm SHA-256 (`receipt.py`) và upload bất biến qua WebHDFS | Closed window -> HDFS Bronze + receipt |
| `hf_bronze.py` (`DockerHdfs`, `receive_batch`) | Tải raw batch từ Hugging Face, staging và đẩy vào HDFS Bronze có ledger chống trùng | HF batch -> HDFS Bronze |
| `p2_transform.py`, `history_execution.py`, `history_snapshot.py` | Chuẩn hóa, khử trùng lặp và chiếu tuyến độc lập cho Spark/HDFS P2 Silver | Bronze envelopes -> Silver Parquet |
| `history_query.py`, `eta_snapshot.py`, `artifact_transport.py` | Đọc tốc độ tuyến lịch sử từ P2 Silver, đóng gói & đồng bộ snapshot/artifact qua `PrivateWebHdfs` | HDFS Silver/Gold -> Local verified cache |

## Cách kiểm thử

```bash
python -m pytest tests/test_hdfs_p1_bronze.py tests/test_hdfs_p2_silver.py --basetemp=runtime/pytest_tmp -q
```
