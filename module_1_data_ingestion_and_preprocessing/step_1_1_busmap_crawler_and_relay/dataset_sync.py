"""
Sync tool: Download all accumulated bus, traffic, and incident data from Hugging Face Dataset
directly into canonical local hierarchy: data/raw/YYYY-MM-DD/{bus,incidents,traffic}/*.jsonl
Usage: py scripts/sync_from_hf.py
"""

import os
import sys
import glob
import shutil

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from config import HF_DATASET_ID, RAW_DATA_DIR, get_hf_token


def main():
    token = get_hf_token()
    if not token:
        print("[ERROR] Missing access_token_hf.txt!")
        return

    print("=" * 68)
    print("SYNCING CANONICAL TELEMETRY FROM HUGGING FACE DATASET TO data/raw/")
    print(f"Dataset: https://huggingface.co/datasets/{HF_DATASET_ID}")
    print("=" * 68)

    from huggingface_hub import snapshot_download

    os.makedirs(RAW_DATA_DIR, exist_ok=True)
    downloaded_path = snapshot_download(
        repo_id=HF_DATASET_ID,
        repo_type="dataset",
        local_dir=RAW_DATA_DIR,
        allow_patterns=["raw_data/*/*/*.jsonl"],
        token=token,
    )

    # Normalize HF's raw_data/YYYY-MM-DD/... subfolder into data/raw/YYYY-MM-DD/...
    hf_raw_subdir = os.path.join(RAW_DATA_DIR, "raw_data")
    moved_files = 0
    if os.path.exists(hf_raw_subdir):
        for chunk in glob.glob(os.path.join(hf_raw_subdir, "*", "*", "*.jsonl")):
            rel = os.path.relpath(chunk, hf_raw_subdir)
            dst = os.path.join(RAW_DATA_DIR, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.move(chunk, dst)
            moved_files += 1
        shutil.rmtree(hf_raw_subdir, ignore_errors=True)

    # Clean HF local cache metadata inside data/raw/.cache if created
    hf_cache = os.path.join(RAW_DATA_DIR, ".cache")
    if os.path.exists(hf_cache):
        shutil.rmtree(hf_cache, ignore_errors=True)

    print(f"[OK] Synced {moved_files} new/updated files into canonical {os.path.abspath(RAW_DATA_DIR)}")


if __name__ == "__main__":
    main()
