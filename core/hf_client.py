"""
Native Hugging Face Dataset Client (Zero-dependency via standard library HTTP & Commit API)
Quản lý đồng bộ batch dữ liệu, siêu dữ liệu (metadata), và theo dõi ngân sách TomTom thời gian thực trên Hugging Face.
"""

import os
import json
import base64
import ssl
import urllib.request
import urllib.parse
import urllib.error
from .config import (
    HF_DATASET_ID,
    TOMTOM_QUOTA_FILE,
    CONFIG_FILE,
    DAILY_HEALTH_FILE,
    MAX_TOMTOM_FLOW_DAILY,
    MAX_TOMTOM_FLOW_MONTHLY,
    MAX_TOMTOM_INCIDENT_DAILY,
    MAX_TOMTOM_INCIDENT_MONTHLY,
    get_hanoi_time,
    get_hf_token
)

ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

def get_hf_today_batch_count(date_tag, category, token, dataset_id=HF_DATASET_ID):
    """Truy vấn số lượng batch (traffic, incidents, bus) đã tải lên Hugging Face hôm nay."""
    if not token or not dataset_id:
        return 0
    url = f"https://huggingface.co/api/datasets/{dataset_id}/tree/main/raw_data/{date_tag}/{category}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, context=ssl_context, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, list):
                return len(data)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return 0
    except Exception:
        pass
    return 0

def get_hf_today_traffic_batch_count(date_tag, token, dataset_id=HF_DATASET_ID):
    """Wrapper tương thích ngược cho traffic flow."""
    return get_hf_today_batch_count(date_tag, "traffic", token, dataset_id)

def fetch_hf_tomtom_quota_state(token=None, dataset_id=HF_DATASET_ID):
    """
    Tải file metadata/tomtom_quota_tracker.json từ Hugging Face về làm phương án dự phòng
    khi runner mới chưa có sẵn file local hoặc bị mất lịch sử commit.
    """
    if not token:
        token = get_hf_token()
    if not token or not dataset_id:
        return None
    url = f"https://huggingface.co/datasets/{dataset_id}/raw/main/metadata/tomtom_quota_tracker.json"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, context=ssl_context, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, dict) and "flow_used_today" in data:
                return data
    except Exception:
        pass
    return None

def generate_hf_readme(quota_state=None):
    """Sinh nội dung README.md chuyên nghiệp cho Hugging Face Dataset Card với bảng số lượng request thời gian thực."""
    hn_time = get_hanoi_time()
    ts_str = hn_time.strftime("%Y-%m-%d %H:%M:%S")

    flow_today = 0
    flow_daily_budget = MAX_TOMTOM_FLOW_DAILY
    flow_remaining_today = MAX_TOMTOM_FLOW_DAILY
    flow_month = 0
    flow_monthly_limit = MAX_TOMTOM_FLOW_MONTHLY
    flow_remaining_month = MAX_TOMTOM_FLOW_MONTHLY

    inc_today = 0
    inc_daily_budget = MAX_TOMTOM_INCIDENT_DAILY
    inc_remaining_today = MAX_TOMTOM_INCIDENT_DAILY
    inc_month = 0
    inc_monthly_limit = MAX_TOMTOM_INCIDENT_MONTHLY
    inc_remaining_month = MAX_TOMTOM_INCIDENT_MONTHLY

    if os.path.exists(TOMTOM_QUOTA_FILE):
        try:
            with open(TOMTOM_QUOTA_FILE, "r", encoding="utf-8") as f:
                q = json.load(f)
                flow_today = q.get("flow_used_today", 0)
                flow_daily_budget = q.get("flow_daily_budget", MAX_TOMTOM_FLOW_DAILY)
                flow_remaining_today = q.get("flow_remaining_today", max(0, flow_daily_budget - flow_today))
                flow_month = q.get("flow_used_month", 0)
                flow_monthly_limit = q.get("flow_monthly_limit", MAX_TOMTOM_FLOW_MONTHLY)
                flow_remaining_month = q.get("flow_remaining_month", max(0, flow_monthly_limit - flow_month))

                inc_today = q.get("incident_used_today", 0)
                inc_daily_budget = q.get("incident_daily_budget", MAX_TOMTOM_INCIDENT_DAILY)
                inc_remaining_today = q.get("incident_remaining_today", max(0, inc_daily_budget - inc_today))
                inc_month = q.get("incident_used_month", 0)
                inc_monthly_limit = q.get("incident_monthly_limit", MAX_TOMTOM_INCIDENT_MONTHLY)
                inc_remaining_month = q.get("incident_remaining_month", max(0, inc_monthly_limit - inc_month))
                ts_str = q.get("last_updated", ts_str)
        except Exception:
            pass

    if quota_state:
        flow_today = quota_state.get("flow_today", flow_today)
        flow_month = quota_state.get("flow_month", flow_month)
        flow_remaining_today = max(0, flow_daily_budget - flow_today)
        flow_remaining_month = max(0, flow_monthly_limit - flow_month)
        inc_today = quota_state.get("incident_today", inc_today)
        inc_month = quota_state.get("incident_month", inc_month)
        inc_remaining_today = max(0, inc_daily_budget - inc_today)
        inc_remaining_month = max(0, inc_monthly_limit - inc_month)

    readme = f"""---
annotations_creators:
- machine-generated
language:
- vi
- en
license: mit
multilinguality:
- monolingual
size_categories:
- 10K<n<100K
source_datasets:
- original
task_categories:
- tabular
task_ids:
- time-series-forecasting
tags:
- bus-tracking
- traffic-flow
- eta-prediction
- hanoi
- hust
pretty_name: Hanoi Bus Corridor & Traffic Telemetry (HUST Cluster)
---

# 🚌 HUST Bus Corridor & Traffic Telemetry Dataset

Dataset phục vụ nghiên cứu và phát triển hệ thống **Dự đoán thời gian xe buýt đến trạm (Bus ETA Prediction)** cho 19 tuyến hành lang trọng điểm kết nối Đại học Bách Khoa Hà Nội (HUST), thu thập liên tục 24/7 kết hợp giữa dữ liệu GPS xe buýt và luồng giao thông TomTom.

---

## 🚦 Live API Quota & Request Ledger (Sổ Cái Số Lượng Request)

> 🕒 **Thời điểm cập nhật:** `{ts_str}` (Giờ Hà Nội - UTC+7)

| Dịch vụ API | Đã dùng hôm nay | Ngân sách ngày | Còn lại hôm nay | Đã dùng trong tháng | Hạn mức tháng | Còn lại tháng | Tần suất crawl |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **TomTom Traffic Flow** (`flowSegmentData`) | **{flow_today:,}** | {flow_daily_budget:,} | **{flow_remaining_today:,}** | **{flow_month:,}** | {flow_monthly_limit:,} | **{flow_remaining_month:,}** | Cao điểm: 18p / Thấp điểm: 54p |
| **TomTom Incident Details** (`incidentDetails`) | **{inc_today:,}** | {inc_daily_budget:,} | **{inc_remaining_today:,}** | **{inc_month:,}** | {inc_monthly_limit:,} | **{inc_remaining_month:,}** | Chu kỳ 18p toàn mạng lưới (BBox) |

---

## 🚌 Phạm Vi Thu Thập Xe Buýt (19 Tuyến - 220 Xe)

- **19 Tuyến buýt hành lang Bách Khoa:**
  `01, 03A, 08A, 18, 21A, 23, 26, 31, 32, 35A, 38, 44, 51, 52A, E01, E03, E04, E08, 101`
- **Tần suất định vị GPS:** Mỗi 60 giây / lượt qua cơ chế Micro-batching bảo vệ rate-limit.
- **Khung giờ chạy:** 05:00 - 22:00 hàng ngày (22:00 - 05:00 chuyển chế độ Standby).

---

## 📁 Cấu Trúc Thư Mục Dữ Liệu

```
hust-bus-data/
├── metadata/
│   ├── tomtom_quota_tracker.json    # Sổ cái hạn ngạch TomTom chính xác (Sync 2 chiều)
│   ├── hust_cluster_config.json     # Cấu hình 19 tuyến & 220 mã xe định danh
│   └── daily_catalog_health.json    # Báo cáo kiểm tra sức khỏe danh mục xe hàng ngày
├── raw_data/
│   └── YYYY-MM-DD/
│       ├── bus/                     # Batch GPS xe buýt đã tiền xử lý
│       ├── traffic/                 # Vận tốc thực tế tại 19 nút nghẽn
│       └── incidents/               # Tọa độ và mức độ ùn tắc sự cố
└── README.md
```
"""
    return readme

def sync_hf_metadata(token=None, dataset_id=HF_DATASET_ID, quota_state=None):
    """Đồng bộ ngay sổ cái hạn ngạch request (tomtom_quota_tracker.json) và README.md lên Hugging Face."""
    if not token:
        token = get_hf_token()
    if not token or not dataset_id:
        print("[INFO] Không có HF_TOKEN hoặc HF_DATASET_ID. Bỏ qua đồng bộ metadata lên HF.", flush=True)
        return False

    operations = []

    # 1. tomtom_quota_tracker.json
    if os.path.exists(TOMTOM_QUOTA_FILE):
        with open(TOMTOM_QUOTA_FILE, "rb") as f:
            q_bytes = f.read()
        if q_bytes:
            operations.append({
                "key": "file",
                "value": {
                    "path": "metadata/tomtom_quota_tracker.json",
                    "encoding": "base64",
                    "content": base64.b64encode(q_bytes).decode("ascii")
                }
            })

    # 2. hust_cluster_config.json
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "rb") as f:
            c_bytes = f.read()
        if c_bytes:
            operations.append({
                "key": "file",
                "value": {
                    "path": "metadata/hust_cluster_config.json",
                    "encoding": "base64",
                    "content": base64.b64encode(c_bytes).decode("ascii")
                }
            })

    # 3. daily_catalog_health.json
    if os.path.exists(DAILY_HEALTH_FILE):
        with open(DAILY_HEALTH_FILE, "rb") as f:
            h_bytes = f.read()
        if h_bytes:
            operations.append({
                "key": "file",
                "value": {
                    "path": "metadata/daily_catalog_health.json",
                    "encoding": "base64",
                    "content": base64.b64encode(h_bytes).decode("ascii")
                }
            })

    # 4. README.md với bảng số lượng request cập nhật
    readme_content = generate_hf_readme(quota_state=quota_state).encode("utf-8")
    operations.append({
        "key": "file",
        "value": {
            "path": "README.md",
            "encoding": "base64",
            "content": base64.b64encode(readme_content).decode("ascii")
        }
    })

    q_data = {}
    if os.path.exists(TOMTOM_QUOTA_FILE):
        try:
            with open(TOMTOM_QUOTA_FILE, "r", encoding="utf-8") as f:
                q_data = json.load(f)
        except Exception:
            pass

    f_today = q_data.get("flow_used_today", 0)
    f_month = q_data.get("flow_used_month", 0)
    i_today = q_data.get("incident_used_today", 0)
    i_month = q_data.get("incident_used_month", 0)
    summary_msg = f"sync(metadata): live request ledger ({f_today}/600 Flow, {i_today}/75 Incidents | Month: {f_month}/20k, {i_month}/2.5k)"

    commit_url = f"https://huggingface.co/api/datasets/{dataset_id}/commit/main"
    ndjson_lines = [
        json.dumps({"key": "header", "value": {"summary": summary_msg, "description": ""}}).encode("utf-8")
    ]
    for op in operations:
        ndjson_lines.append(json.dumps(op).encode("utf-8"))
    data = b"\n".join(ndjson_lines) + b"\n"

    req = urllib.request.Request(
        commit_url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/x-ndjson"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, context=ssl_context, timeout=30) as resp:
            if resp.getcode() == 200:
                print(f"[OK] Da dong bo thanh cong So Cai Request va Metadata len Hugging Face ({dataset_id})!", flush=True)
                return True
            else:
                print(f"[WARN] HF sync metadata tra ve HTTP {resp.getcode()}", flush=True)
                return False
    except Exception as e:
        print(f"[WARN] Loi sync metadata len HF Dataset: {e}", flush=True)
        return False

def upload_batches_to_hf_native(bus_chunk, traffic_chunk, incident_chunk, date_tag, time_tag, token, dataset_id=HF_DATASET_ID, quota_state=None):
    """
    Đẩy các file batch nén jsonl kèm metadata và bảng cập nhật số lượng request lên Hugging Face Dataset
    hoàn toàn bằng standard library qua Commit API.
    """
    if not token or not dataset_id:
        print("[INFO] Không có HF_TOKEN hoặc HF_DATASET_ID. Bỏ qua đồng bộ cloud.", flush=True)
        return False

    operations = []

    if bus_chunk and os.path.exists(bus_chunk):
        with open(bus_chunk, "rb") as f:
            b_bytes = f.read()
        if b_bytes:
            operations.append({
                "key": "file",
                "value": {
                    "path": f"raw_data/{date_tag}/bus/batch_{time_tag}.jsonl",
                    "encoding": "base64",
                    "content": base64.b64encode(b_bytes).decode("ascii")
                }
            })

    if traffic_chunk and os.path.exists(traffic_chunk):
        with open(traffic_chunk, "rb") as f:
            t_bytes = f.read()
        if t_bytes:
            operations.append({
                "key": "file",
                "value": {
                    "path": f"raw_data/{date_tag}/traffic/batch_{time_tag}.jsonl",
                    "encoding": "base64",
                    "content": base64.b64encode(t_bytes).decode("ascii")
                }
            })

    if incident_chunk and os.path.exists(incident_chunk):
        with open(incident_chunk, "rb") as f:
            i_bytes = f.read()
        if i_bytes:
            operations.append({
                "key": "file",
                "value": {
                    "path": f"raw_data/{date_tag}/incidents/batch_{time_tag}.jsonl",
                    "encoding": "base64",
                    "content": base64.b64encode(i_bytes).decode("ascii")
                }
            })

    # Đồng bộ tomtom_quota_tracker.json lên HF trong mỗi commit
    if os.path.exists(TOMTOM_QUOTA_FILE):
        with open(TOMTOM_QUOTA_FILE, "rb") as f:
            q_bytes = f.read()
        if q_bytes:
            operations.append({
                "key": "file",
                "value": {
                    "path": "metadata/tomtom_quota_tracker.json",
                    "encoding": "base64",
                    "content": base64.b64encode(q_bytes).decode("ascii")
                }
            })

    # Cập nhật README.md trên HF Dataset với bảng request mới nhất
    readme_content = generate_hf_readme(quota_state=quota_state).encode("utf-8")
    operations.append({
        "key": "file",
        "value": {
            "path": "README.md",
            "encoding": "base64",
            "content": base64.b64encode(readme_content).decode("ascii")
        }
    })

    if not operations:
        return False

    f_today = quota_state.get("flow_today", 0) if quota_state else 0
    f_month = quota_state.get("flow_month", 0) if quota_state else 0
    i_today = quota_state.get("incident_today", 0) if quota_state else 0
    i_month = quota_state.get("incident_month", 0) if quota_state else 0

    commit_url = f"https://huggingface.co/api/datasets/{dataset_id}/commit/main"
    summary_str = f"Relay Batch ({date_tag} {time_tag}): {len(operations)} files | Flow: {f_today}/{MAX_TOMTOM_FLOW_DAILY} (M: {f_month}) | Inc: {i_today}/{MAX_TOMTOM_INCIDENT_DAILY}"
    ndjson_lines = [
        json.dumps({"key": "header", "value": {"summary": summary_str, "description": ""}}).encode("utf-8")
    ]
    for op in operations:
        ndjson_lines.append(json.dumps(op).encode("utf-8"))
    data = b"\n".join(ndjson_lines) + b"\n"

    req = urllib.request.Request(
        commit_url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/x-ndjson"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, context=ssl_context, timeout=30) as resp:
            if resp.getcode() == 200:
                print(f"[OK] Da day thanh cong {len(operations)} files kem So Cai Request len HF Dataset: {dataset_id}", flush=True)
                return True
            else:
                print(f"[WARN] HF tra ve HTTP {resp.getcode()}", flush=True)
                return False
    except Exception as e:
        print(f"[WARN] Loi upload HF Dataset: {e}", flush=True)
        return False
