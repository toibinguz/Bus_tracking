"""
Step 0: Telemetry Sync Module
Downloads bus telemetry batches from Hugging Face Dataset to local machine.
"""

import os
import sys
import glob
import logging
from typing import Dict, Any, List

from core.config import HF_DATASET_ID, get_hf_token

logger = logging.getLogger(__name__)

def sync_bus_telemetry_from_hf(
    target_dir: str = "data/telemetry_sync/raw_batches",
    pattern: str = "raw_data/*/bus/*.jsonl",
    max_workers: int = 4,
    max_batches: Optional[int] = None
) -> Dict[str, Any]:
    """
    Synchronizes bus telemetry jsonl batches from Hugging Face dataset.
    Follows cloud-first architecture: local machine only keeps verification samples,
    while the master dataset is stored on Hugging Face.
    """
    token = get_hf_token()
    if not token:
        raise ValueError("Missing Hugging Face token in access_token_hf.txt or HF_TOKEN env var!")

    os.makedirs(target_dir, exist_ok=True)
    temp_download_dir = "data/telemetry_sync/.temp_download"
    os.makedirs(temp_download_dir, exist_ok=True)

    print(f"[*] Connecting to Hugging Face Dataset: {HF_DATASET_ID}")
    print(f"[*] Downloading pattern: '{pattern}' ...")

    from huggingface_hub import snapshot_download
    downloaded_repo_path = snapshot_download(
        repo_id=HF_DATASET_ID,
        repo_type="dataset",
        allow_patterns=[pattern],
        local_dir=temp_download_dir,
        token=token,
        max_workers=max_workers
    )

    # Locate downloaded files and move to target_dir flattening or preserving hierarchy
    matched_files = glob.glob(os.path.join(temp_download_dir, "raw_data", "*", "bus", "*.jsonl"))
    if max_batches is not None and max_batches > 0:
        matched_files = matched_files[:max_batches]
    print(f"[*] Found {len(matched_files)} bus telemetry batch files selected for local verification.")

    import shutil
    synced_files: List[str] = []
    total_records = 0

    for file_path in matched_files:
        # Extract date from path (raw_data/<date>/bus/<file>)
        parts = os.path.normpath(file_path).split(os.sep)
        date_folder = "unknown"
        for i, p in enumerate(parts):
            if p == "bus" and i > 0:
                date_folder = parts[i - 1]
                break

        dest_date_dir = os.path.join(target_dir, date_folder)
        os.makedirs(dest_date_dir, exist_ok=True)
        dest_file = os.path.join(dest_date_dir, os.path.basename(file_path))

        # Check if already exists with same size
        if not os.path.exists(dest_file) or os.path.getsize(dest_file) != os.path.getsize(file_path):
            shutil.copy2(file_path, dest_file)

        synced_files.append(dest_file)

    # Count total records across synced files
    for sf in synced_files:
        with open(sf, "r", encoding="utf-8", errors="ignore") as f:
            total_records += sum(1 for _ in f)

    result = {
        "status": "SUCCESS",
        "total_files": len(synced_files),
        "total_records": total_records,
        "target_dir": os.path.abspath(target_dir),
        "dates_covered": list(set(os.path.basename(os.path.dirname(f)) for f in synced_files))
    }
    print(f"[OK] Step 0 (Sync): {result['total_files']} files synced, {result['total_records']:,} records across {result['dates_covered']}.")
    return result

if __name__ == "__main__":
    sync_bus_telemetry_from_hf()

