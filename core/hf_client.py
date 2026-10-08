"""
Native Hugging Face Dataset Client (Zero-dependency via standard library HTTP & Commit API)
"""

import os
import json
import base64
import ssl
import urllib.request
import urllib.parse
import urllib.error
from .config import HF_DATASET_ID

ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

def get_hf_today_traffic_batch_count(date_tag, token, dataset_id=HF_DATASET_ID):
    """Truy vấn số lượng batch traffic đã tải lên Hugging Face hôm nay để kiểm soát hạn mức ngày."""
    if not token or not dataset_id:
        return 0
    url = f"https://huggingface.co/api/datasets/{dataset_id}/tree/main/raw_data/{date_tag}/traffic"
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

def upload_batches_to_hf_native(bus_chunk, traffic_chunk, incident_chunk, date_tag, time_tag, token, dataset_id=HF_DATASET_ID):
    """Đẩy các file batch nén jsonl lên Hugging Face Dataset hoàn toàn bằng standard library qua Commit API."""
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

    if not operations:
        return False

    commit_url = f"https://huggingface.co/api/datasets/{dataset_id}/commit/main"
    ndjson_lines = [
        json.dumps({"key": "header", "value": {"summary": f"Relay Batch ({date_tag} {time_tag}): {len(operations)} files", "description": ""}}).encode("utf-8")
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
                print(f"[OK] Đã đẩy thành công {len(operations)} batches lên HF Dataset: {dataset_id}", flush=True)
                return True
            else:
                print(f"[WARN] HF trả về HTTP {resp.getcode()}", flush=True)
                return False
    except Exception as e:
        print(f"[WARN] Lỗi upload HF Dataset: {e}", flush=True)
        return False

