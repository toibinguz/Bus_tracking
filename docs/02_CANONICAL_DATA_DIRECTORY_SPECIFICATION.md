# ĐẶC TẢ CẤU TRÚC THƯ MỤC DỮ LIỆU & QUẢN TRỊ LAKEHOUSE (CANONICAL DATA GOVERNANCE)
> **Reconciliation note (2026-11-10):** This document defines the target data contract. Ignored `data/raw/` and `data/lakehouse/` paths are runtime-managed; tracked canonical inputs are `data/ground_truth/`, `data/metadata/`, and `data/models/`. Counts in this document are snapshots.

> **Mã tài liệu**: `docs/02_CANONICAL_DATA_DIRECTORY_SPECIFICATION.md`
> **Căn cứ pháp lý**: Tuân thủ vô điều kiện **Điều 3** (Phân định ranh giới), **Điều 4** (Nguồn chân lý dữ liệu), và **Điều 8** (Nghiệm thu trung thực & minh bạch nợ kỹ thuật) của [AGENTS.md](../AGENTS.md).
> **Ngày ban hành**: 07/11/2026
> **Trạng thái**: CHÍNH THỨC ÁP DỤNG (Frozen Canonical Standard)

---

## I. MỤC TIÊU VÀ BỐI CẢNH LỊCH SỬ

### 1. Vấn đề lịch sử cần giải quyết triệt để
Trước ngày 07/11/2026, thư mục `data/` bị phân mảnh và tích lũy nợ kỹ thuật nghiêm trọng với 3 thư mục cùng đại diện cho dữ liệu thô:
1. `data/telemetry_sync`: Tàn dư thử nghiệm ngày 19/10/2026 (320 MB) chứa trùng lặp 2 ngày dữ liệu.
2. `data/temp_hf_sync`: Thư mục tải về từ Hugging Face (3.9 GB) nhưng bị gắn mác tạm thời (`temp_`), khiến các script sau này đọc trực tiếp vào folder tạm.
3. `data/raw`: Vỏ rỗng chỉ chứa 3 file rời rạc (0.72 MB).
4. **Cấu trúc Weekly SLA phức tạp**: Sinh ra thư mục `data/lakehouse/gold/kinematic_horizon_samples` (1.37 GB, 947 files) cho mô hình "Two-Stage Decoupled Features" không cần thiết, gây phình to ổ đĩa và rắc rối kỹ thuật.

### 2. Quyết định tái cấu trúc & Đơn giản hóa
* **Thu hồi toàn diện**: Di chuyển toàn bộ dữ liệu thô chuẩn xác (28 ngày từ 08/10 đến 07/11) về đúng chính danh `data/raw/`.
* **Xóa bỏ vĩnh viễn**: Xóa bỏ `data/telemetry_sync`, `data/temp_hf_sync`, và kho Stage 1 `kinematic_horizon_samples`.
* **Loại bỏ cấu trúc Weekly SLA**: Tối giản hóa pipeline, chuyển dịch sang Unified Feature Store toàn mạng, loại bỏ bảng benchmark phụ trong CSDL (`weekly_retraining_sla_benchmark`, `storage_benchmark_comparison`).

---

## II. CÂY THƯ MỤC DỮ LIỆU CHUẨN MỰC (CANONICAL DIRECTORY TREE)

Toàn bộ hệ thống từ nay CHỈ ĐƯỢC PHÉP tồn tại 6 thành phần bất biến trong thư mục `data/`:

```
data/
├── ground_truth/                      # [Single Source of Truth] Master Canonical Ground Truth (BusMap)
│   ├── busmap_canonical/             # 176 routes, 13.301 stations, 118.563 shape points
│   └── README.md
│
├── raw/                               # [Raw Ingestion Layer] Dữ liệu JSONL thô cào từ Cloud / Hugging Face
│   ├── 2026-10-08/                    # Thư mục ngày chuẩn ISO (YYYY-MM-DD)
│   │   ├── bus/                       # batch_*.jsonl (GPS telemetry)
│   │   ├── traffic/                   # batch_*.jsonl (Flow speed)
│   │   └── incidents/                 # batch_*.jsonl (TomTom incidents)
│   ├── ...
│   └── 2026-11-07/                    # Cập nhật liên tục đến hiện tại (28 ngày)
│
├── lakehouse/                         # [Medallion Lakehouse - Columnar Parquet]
│   ├── bronze/                        # Parquet snapshot thô từ SQLite (immutable)
│   ├── silver/                        # On-corridor projected telemetry (d_perp <= 35m)
│   │   └── route_projected_telemetry/ # Hive Partitioning: route_code=XX/direction=YY/dt=ZZ
│   └── gold/                          # Feature Store & Ma trận Baseline chuẩn hóa
│       ├── agg_segment_travel_times/  # Prior matrix parquet
│       └── eta_feature_store/         # Unified feature matrix (train/ & test/)
│
├── metadata/                          # Metadata vận hành (tomtom_quota_tracker, hust_cluster_config)
├── splits/                            # Đóng băng tập Train/Test chống rò rỉ (train_test_split_v1.json)
└── hanoi_bus_system.db                # CSDL SQLite vận hành tinh gọn (Indexed Tables & Views)
```

---

## III. NGUYÊN TẮC QUẢN TRỊ & BẢO VỆ (GOVERNANCE GUARDRAILS)

1. **Tuyệt đối cấm tạo thư mục tạm trong `data/`**:
   - Nghiêm cấm tạo các folder như `data/temp_*`, `data/*_sync`, `data/raw_batches`, `data/telemetry_*`.
   - File `.gitignore` đã được cấu hình chặn tự động các mẫu thư mục này.
2. **Tập trung hóa hằng số đường dẫn**:
   - Mọi mã nguồn bắt buộc phải import đường dẫn từ `config/system_config.py`:
     ```python
     from config.system_config import RAW_DATA_DIR, DEFAULT_DB_PATH, DEFAULT_LAKEHOUSE_ROOT
     ```
   - Nghiêm cấm hardcode các chuỗi đường dẫn tương đối rải rác trong scripts.
3. **Quy tắc phân vùng Medallion Lakehouse**:
   - Tầng Silver bắt buộc phải lọc sạch hành lang $d_\perp \le 35\text{m}$.
   - Tầng Gold chứa trực tiếp các đặc trưng huấn luyện của toàn mạng lưới hoặc theo hành lang, không phân mảnh thành Stage 1/Stage 2 cồng kềnh.
