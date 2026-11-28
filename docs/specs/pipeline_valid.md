# Bổ sung & Chốt kiến trúc triển khai cho `pipeline-local-production.md`

## 1. Thống nhất mục tiêu & điều chỉnh cách triển khai
Đồng ý toàn bộ các bất biến nghiệp vụ, truy xuất nguồn gốc và tiêu chí nghiệm thu trong `docs/specs/pipeline-local-production.md` (khử trùng xuyên batch, cắt phiên xuyên 00:00, cửa sổ sự cố vắt qua biên ngày, `route_id_idx` theo toàn bộ danh mục baseline, một đường gọi duy nhất cho C++17/Python fallback, công bố nguyên tử `builds/{build_id}` + đổi `manifest.json`).

Tuy nhiên, để tránh over-engineering lớp `Executor` trừu tượng (khó bảo trì với `cloudpickle`/JVM của PySpark) nhưng vẫn đảm bảo **thống nhất tuyệt đối về mã lõi (không phải hợp đồng suông)**, kiến trúc triển khai chốt theo mô hình **Core SSOT thuần + 2 Adapter I/O mỏng**:

```text
[Tầng 1: CORE SSOT — 100% dùng chung cho Local & Docker]
  modules/lakehouse/pipeline/
  ├── spec.py            # PipelineSpec, giá trị mặc định nghiệp vụ, schema manifest, quy tắc validate
  ├── silver_core.py     # normalize_bus/incident, merge_bus, split_vehicle_sessions, project_vehicle_session (C++17 + fallback), filter_silver_row
  ├── incidents_core.py  # tính cửa sổ lookback sự cố + project_window_intervals
  ├── baseline_core.py   # compute_route_baseline (C++17 + fallback) + validate_tier_counts
  └── features_core.py   # build_route_feature_metadata, compute_route_features (C++17 + fallback) + validate_split_counts

[Tầng 2: I/O & DISTRIBUTION ADAPTERS — 0 dòng logic nghiệp vụ]
  modules/lakehouse/
  ├── local_adapter.py   # Local FS + pyarrow + bucket đĩa tạm theo route_id + ProcessPoolExecutor + atomic os.replace
  ├── spark_adapter.py   # HDFS + PySpark (repartition/cogroup/broadcast) + publish_gold (FileContext atomic rename)
  └── serving_sync.py    # Đồng bộ 1 chiều Gold Baseline (Local hoặc HDFS) -> SQLite 5 bảng (atomic os.replace)

[Tầng 3: THIN CLI WRAPPERS]
  scripts/run_local_batch_pipeline.py, scripts/hdfs_build_*.py, scripts/sync_gold_to_serving_db.py
```

## 2. Ràng buộc cứng cho Tầng Core SSOT (`modules/lakehouse/pipeline/`)
1. **Độc lập môi trường thực thi:** Toàn bộ `modules/lakehouse/pipeline/*.py` **chỉ được phép phụ thuộc** `stdlib + numpy + shapely + core_cpp` và tương thích **Python 3.8** (`from __future__ import annotations`), khớp trực tiếp với image `apache/spark:3.5.4` (không cài `pandas`/`pyarrow`, không đọc SQLite cục bộ).
2. **Không rò rỉ nghiệp vụ ra Adapter:** Mọi quyết định có thể làm thay đổi dữ liệu (lọc 48 tuyến chuẩn / `dt >= CANONICAL_START_DATE`, khử trùng `merge_bus`, ngưỡng `STALE_DELTA_T_MAX_SEC`, ánh xạ `route_id_idx` theo `baseline_codes`, chọn kernel C++17 + fallback Python, kiểm tra `tier_counts`/`split_counts`, dựng payload `manifest`) **bắt buộc nằm trong Core SSOT**.
3. **Adapter chỉ làm đúng 3 việc vật lý:**
   - Đọc dữ liệu từ nguồn vật lý (Local FS/Parquet hoặc HDFS/Parquet).
   - Gom nhóm và sắp xếp theo đúng khóa mà Core quy định:
     - Dedup bus: khóa `event_id` → `merge_bus`
     - Silver projection: nhóm `(route_id, vehicle_id)`, sắp `(observed_ms, event_id)` → cắt phiên xuyên 00:00 → `project_vehicle_session`
     - Incidents: nhóm `incident_id` (lấy cả các sự cố bắt đầu trước cửa sổ trong phạm vi `max(DEFAULT_TTL_SEC, MAX_BATCH_GAP_SEC)`) → `project_window_intervals`
     - Gold Baseline: nhóm `route_code`, lọc `dt <= fit_end_date` → `compute_route_baseline`
     - Gold Features: `cogroup` theo `route_code` giữa Silver telemetry và incident intervals + metadata từ `baseline_codes` đầy đủ → `compute_route_features`
   - Ghi Parquet vào `builds/{build_id}/data` và chuyển con trỏ `manifest.json` nguyên tử.

## 3. Thiết kế giới hạn RAM cho `local_adapter.py` (không cắt phiên ở 00:00)
Với dữ liệu local 40 ngày (~6.9 GB JSONL), để thỏa bất biến **khử trùng toàn cục + giữ nguyên chuyến qua nửa đêm** mà không OOM trên laptop:
- **Pass 1 (Streaming theo ngày → Bucket tạm theo `route_id`):** Đọc từng file raw JSONL, gọi `silver_core.normalize_bus`, ghi sự kiện chuẩn hóa ra file tạm trên đĩa (`data/staging/local_silver_buckets/route_<id>.jsonl`, mỗi tuyến ~100–150 MB).
- **Pass 2 (Song song theo tuyến bằng `ProcessPoolExecutor`):** Mỗi worker đọc trọn 1 file tuyến, khử trùng toàn cục theo `event_id` bằng `silver_core.merge_bus`, sắp theo `(vehicle_id, observed_ms, event_id)`, cắt phiên xuyên nửa đêm và chiếu qua `silver_core.project_vehicle_session` (C++17), rồi ghi Silver Parquet nguyên tử.
- Toàn bộ tệp tạm nằm trong `data/staging/` và được dọn sạch trong khối `finally`.

## 4. Quy tắc kiểm chứng tương đương (Parity Gate)
Sau khi triển khai, bắt buộc có test tự động chạy **cùng 1 bộ raw mẫu + reference + `PipelineSpec`** qua cả `local_adapter` và `spark_adapter` (hoặc Spark local mode / Docker cluster), bao phủ 4 ca biên:
1. Bản ghi bus trùng lặp xuyên batch khác ngày.
2. Xe chạy liên tục vắt qua mốc `00:00` (hai file ngày liền kề).
3. Sự cố TomTom bắt đầu trước đầu cửa sổ features nhưng còn hiệu lực bên trong cửa sổ.
4. Chạy lọc `--routes 02` nhưng `route_id_idx` vẫn khớp với chỉ số trong danh mục baseline đầy đủ.

Điều kiện đạt: khớp chính xác 100% số dòng, khóa, nhãn, split, `quality_tier`, `route_id_idx`, `engine` ghi trong manifest, và sai số số thực trong ngưỡng chốt trước (`<= 1e-5` cho tọa độ/Frenet, `<= 0.05s` cho thống kê baseline).