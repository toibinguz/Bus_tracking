# Thư mục CLI Entrypoints & Vận hành (`scripts/`)

- **Vai trò:** Chỉ chứa **Thin CLI Entrypoints** gọi trực tiếp vào `module_1`, `module_2`, `module_3` và **Ops Runners** vận hành hạ tầng (GitHub Actions, Hugging Face, cụm HDFS/Spark). **Không** đặt nghiệp vụ cốt lõi trong thư mục này.

## Danh sách Script hiện có (34 file)

### 1. Module 1 — Thu thập & Tiền xử lý
| Script | Gọi tới | Mục đích |
| --- | --- | --- |
| `cloud_crawler_step.py` | `step_1_1/cloud_crawler_runner.py` | Entrypoint cho GitHub Actions `.github/workflows/crawl_bus.yml` |
| `run_production_crawler.py` | `step_1_1/local_production_crawler.py` | Chạy crawler cục bộ + Bronze spool |
| `daily_catalog_refresh.py` | `step_1_1/catalog_refresher.py` | Làm mới danh mục xe buýt đầu ngày |
| `sync_from_hf.py` | `step_1_1/dataset_sync.py` | Đồng bộ dữ liệu batch từ Hugging Face về `data/raw/` |
| `inspect_hf_storage_contract.py` | `hf_lake_sync` / HF API | Kiểm tra hợp đồng lưu trữ batch trên Hugging Face |
| `ingest_canonical_busmap_master.py` | `step_1_5/ingest_busmap_canonical.py` | Nạp GTFS chuẩn vào SQLite |
| `bulk_ingest_all_bus_pings.py` | `step_1_3/bulk_ping_ingester.py` | Nạp hàng loạt ping thô JSONL vào SQLite |
| `parallel_multi_route_projector.py` | `step_1_4/multi_route_projector.py` | Chiếu 1D Frenet song song đa nhân vào SQLite |
| `build_fact_route_tomtom_incidents.py` | `step_1_4/tomtom_incident_projector.py` | Chiếu sự cố TomTom lên lưới tuyến |

### 2. Module 2 — Lakehouse & Cụm HDFS / Spark
| Script | Mục đích |
| --- | --- |
| `audit_silver_lakehouse_purity.py` | Gọi `step_2_2/silver_lakehouse_auditor.py` kiểm toán Silver Parquet |
| `verify_canonical_architecture.py` | Kiểm tra cấu trúc bảng SQLite & Lakehouse sẵn sàng |
| `hdfs_demo.ps1`, `hdfs_provision_namespace.sh` | Bật/tắt cụm Docker HDFS (`docker-compose.hdfs.yml`) & cấp quyền namespace |
| `hdfs_ingest_runner.py`, `hdfs_import_history.py`, `verify_hdfs_history_import.py` | Nhập & đối chiếu hash dữ liệu lịch sử Hugging Face lên HDFS Bronze |
| `export_hdfs_history_reference.py`, `hdfs_build_history_snapshot.py` | Xuất reference GTFS & chạy Spark Silver P2 snapshot trên HDFS |
| `hdfs_history_server.py`, `hdfs_p3_validate.py`, `hdfs_p3b_scale.py` | API truy vấn tốc độ lịch sử (`:8090`) & kiểm chứng P3 |
| `eta_snapshot_pipeline.py`, `run_hdfs_eta_workflow.py` | Đóng gói, xác thực và kích hoạt release pointer từ HDFS Gold |

### 3. Module 3 — Baseline & Mô hình ETA
| Script | Gọi tới | Mục đích |
| --- | --- | --- |
| `build_baseline_travel_time_matrix.py` | `step_3_1/baseline_matrix_builder.py` | Xây dựng Baseline Matrix phân vị lịch sử |
| `build_gold_feature_store.py` | `step_3_2/feature_store_builder.py` | Xuất Gold Feature Store Parquet |
| `train_causal_eta.py` | `step_3_3/silver_replay_trainer.py` | Huấn luyện mô hình Residual XGBoost `causal-eta.v1` |
| `eta_history_baseline.py` | `step_3_1` / `step_2_4` | Chạy đánh giá baseline từ lịch sử local hoặc HDFS |

### 4. Script tham chiếu / phụ thuộc kiểm thử (`tests/`)
| Script | Được test tham chiếu |
| --- | --- |
| `analyze_eta_live.py`, `evaluate_eta_candidate.py` | `tests/module_3/test_eta_validation_protocol.py` |
| `experiment_eta_streaming.py`, `global_projection_reference.py` | `tests/module_3/test_eta_streaming_experiments.py` |
| `probe_eta_behavior.py` | `tests/module_3/test_eta_behavior_probes.py` |
| `route_projection_candidates.py` | `tests/module_1/test_route_projection_candidates.py` |
| `sync_hf_hdfs_session.py` | `tests/module_2/test_hf_bounded_session.py` |
