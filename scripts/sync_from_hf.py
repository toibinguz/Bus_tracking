"""
Sync tool: Download all accumulated bus and traffic data from Hugging Face Dataset
to local laptop storage.
Usage: python scripts/sync_from_hf.py
"""

import os
import sys
import glob
import json
import urllib.request
from datetime import datetime

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

DATASET_ID = "Toibinguz/hust-bus-data"
TOKEN_FILE = "access_token_hf.txt"
LOCAL_RAW_DIR = "data/raw"

def get_hf_token():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    return os.environ.get("HF_TOKEN", "")

def main():
    token = get_hf_token()
    if not token:
        print("[ERROR] Chua tim thay access_token_hf.txt!")
        return

    print("=" * 60)
    print("🔄 DONG BO DU LIEU TU HUGGING FACE DATASET VE LAPTOP")
    print(f"📦 Dataset: https://huggingface.co/datasets/{DATASET_ID}")
    print("=" * 60)

    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("[INFO] Dang cai dat thu vien huggingface_hub...")
        os.system(f"{sys.executable} -m pip install huggingface_hub -q")
        from huggingface_hub import snapshot_download

    temp_sync_dir = "data/temp_hf_sync"
    os.makedirs(temp_sync_dir, exist_ok=True)
    os.makedirs(os.path.join(LOCAL_RAW_DIR, "bus"), exist_ok=True)
    os.makedirs(os.path.join(LOCAL_RAW_DIR, "traffic"), exist_ok=True)

    print("[*] Dang tai cac file moi nhat tu Cloud ve...")
    downloaded_path = snapshot_download(
        repo_id=DATASET_ID,
        repo_type="dataset",
        local_dir=temp_sync_dir,
        token=token
    )
    print(f"[OK] Da tai ve thu muc tam: {downloaded_path}")

    # Merge chunks by date into local data/raw
    all_chunks = glob.glob(os.path.join(temp_sync_dir, "raw_data", "**", "*.jsonl"), recursive=True)
    print(f"[*] Tim thay tong cong {len(all_chunks)} chunks du lieu tren Cloud.")

    total_records = 0
    copied_files = 0
    import shutil
    for chunk in all_chunks:
        if "\\bus\\" in chunk or "/bus/" in chunk:
            category = "bus"
        elif "\\incidents\\" in chunk or "/incidents/" in chunk:
            category = "incidents"
        else:
            category = "traffic"
        
        target_dir = os.path.join(LOCAL_RAW_DIR, category)
        os.makedirs(target_dir, exist_ok=True)
        target_file = os.path.join(target_dir, os.path.basename(chunk))
        
        # Count lines
        with open(chunk, "r", encoding="utf-8") as f:
            lines_count = sum(1 for _ in f)
        total_records += lines_count

        # Copy or overwrite if updated
        shutil.copy2(chunk, target_file)
        copied_files += 1

    print(f"\n🎉 Dong bo thanh cong {copied_files} files voi {total_records:,} records ve may tinh cua ban!")
    print(f"📂 Vi tri luu tru: {os.path.abspath(LOCAL_RAW_DIR)}")

if __name__ == "__main__":
    main()

