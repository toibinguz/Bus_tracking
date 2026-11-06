"""
High-Speed Dataset Sync Tool from Hugging Face
Pull all historical telemetry, traffic flow, and incident batches into local storage.
"""

import os
import sys
import time
from huggingface_hub import snapshot_download

# Force UTF-8 stdout
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Ensure project root is in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from config import HF_DATASET_ID, get_hf_token

def main():
    token = get_hf_token()
    if not token:
        print("[ERROR] Hugging Face access token not found!")
        sys.exit(1)

    repo_id = HF_DATASET_ID
    target_dir = os.path.join(BASE_DIR, "data", "temp_hf_sync")
    os.makedirs(target_dir, exist_ok=True)

    print("=" * 70)
    print(f"🚀 INITIATING FULL HIGH-SPEED REPOSITORY PULL FROM HUGGING FACE")
    print(f"📦 Repository: {repo_id}")
    print(f"📂 Target Directory: {target_dir}")
    print(f"⚡ Max Workers: 32 Parallel Download Workers")
    print("=" * 70)

    start_time = time.time()
    try:
        downloaded_dir = snapshot_download(
            repo_id=repo_id,
            repo_type="dataset",
            local_dir=target_dir,
            token=token,
            max_workers=32
        )
        elapsed = time.time() - start_time
        print(f"\n✅ Snapshot download completed in {elapsed:.2f}s ({elapsed/60:.2f} mins)!")
    except Exception as e:
        print(f"\n❌ Error during snapshot_download: {e}")
        sys.exit(1)

    # Statistical verification of downloaded files
    total_files = 0
    total_size = 0
    bus_files = 0
    traffic_files = 0
    incident_files = 0
    date_breakdown = {}

    for root, dirs, files in os.walk(target_dir):
        if ".cache" in root or ".git" in root:
            continue
        for f in files:
            fp = os.path.join(root, f)
            total_files += 1
            sz = os.path.getsize(fp)
            total_size += sz
            rel = os.path.relpath(fp, target_dir)
            parts = rel.split(os.sep)
            if len(parts) >= 2 and parts[0] == "raw_data":
                date_tag = parts[1]
                if date_tag not in date_breakdown:
                    date_breakdown[date_tag] = {"bus": 0, "traffic": 0, "incidents": 0, "size": 0}
                date_breakdown[date_tag]["size"] += sz

                if "bus" in parts:
                    bus_files += 1
                    date_breakdown[date_tag]["bus"] += 1
                elif "traffic" in parts:
                    traffic_files += 1
                    date_breakdown[date_tag]["traffic"] += 1
                elif "incidents" in parts:
                    incident_files += 1
                    date_breakdown[date_tag]["incidents"] += 1

    print("\n" + "=" * 70)
    print("📊 DATASET INVENTORY VERIFICATION REPORT")
    print("=" * 70)
    print(f"📁 Total Files on Disk: {total_files:,}")
    print(f"💾 Total Disk Footprint: {total_size / (1024*1024):.2f} MB ({total_size / (1024*1024*1024):.2f} GB)")
    print(f"🚌 Bus Telemetry Batches: {bus_files:,}")
    print(f"🚗 Traffic Flow Batches: {traffic_files:,}")
    print(f"⚠️ Incident Batches: {incident_files:,}")
    print(f"📅 Dates Synchronized: {len(date_breakdown)}")
    print("-" * 70)
    print(f"{'Date':<14} | {'Bus Files':<10} | {'Traffic':<10} | {'Incidents':<10} | {'Size (MB)':<10}")
    print("-" * 70)
    for d, counts in sorted(date_breakdown.items()):
        print(f"{d:<14} | {counts['bus']:<10} | {counts['traffic']:<10} | {counts['incidents']:<10} | {counts['size']/(1024*1024):<10.2f}")
    print("=" * 70)

if __name__ == "__main__":
    main()

