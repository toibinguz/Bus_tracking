"""
Sync tool: Download canonical bus and incident data from Hugging Face Dataset
directly into canonical local hierarchy: data/raw/YYYY-MM-DD/{bus,incidents}/*.jsonl
Usage: python scripts/sync_from_hf.py [--from-date 2026-10-08] [--to-date 2026-11-19] [--categories bus incidents] [--prune-extra]
"""

import argparse
from datetime import date, timedelta
import glob
import os
from pathlib import Path
import shutil
import sys

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from config import (
    CANONICAL_START_DATE,
    HF_DATASET_ID,
    RAW_DATA_DIR,
    TEST_SPLIT_END_DATE,
    get_hf_token,
)


def _date_range(from_date: str, to_date: str) -> list[str]:
    start = date.fromisoformat(from_date)
    end = date.fromisoformat(to_date)
    if start > end:
        raise ValueError(f"from_date ({from_date}) must be <= to_date ({to_date})")
    days = []
    cur = start
    while cur <= end:
        days.append(cur.isoformat())
        cur += timedelta(days=1)
    return days


def _prune_extra_local(output_dir: Path, valid_dates: set[str], valid_categories: set[str]) -> int:
    removed = 0
    if not output_dir.exists():
        return 0
    for day_dir in list(output_dir.iterdir()):
        if not day_dir.is_dir():
            continue
        if day_dir.name.startswith("."):
            continue
        if day_dir.name not in valid_dates:
            shutil.rmtree(day_dir)
            removed += 1
            continue
        for cat_dir in list(day_dir.iterdir()):
            if cat_dir.is_dir() and cat_dir.name not in valid_categories:
                shutil.rmtree(cat_dir)
                removed += 1
    return removed


def sync_from_hf(
    *,
    from_date: str = CANONICAL_START_DATE,
    to_date: str = TEST_SPLIT_END_DATE,
    categories: list[str] | tuple[str, ...] = ("bus", "incidents"),
    output_dir: str | Path = RAW_DATA_DIR,
    prune_extra: bool = False,
) -> dict:
    token = get_hf_token()
    if not token:
        raise RuntimeError("Missing access_token_hf.txt!")

    days = _date_range(from_date, to_date)
    cats = tuple(dict.fromkeys(str(c).strip() for c in categories if str(c).strip()))
    if not cats:
        raise ValueError("at least one category is required")

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    allow_patterns = [f"raw_data/{d}/{c}/*.jsonl" for d in days for c in cats]

    print("=" * 68, flush=True)
    print(f"SYNCING CANONICAL TELEMETRY FROM HF -> {out_path}", flush=True)
    print(f"Dataset: https://huggingface.co/datasets/{HF_DATASET_ID}", flush=True)
    print(f"Window : {from_date} .. {to_date} ({len(days)} days) | Categories: {list(cats)}", flush=True)
    print("=" * 68, flush=True)

    from huggingface_hub import snapshot_download

    snapshot_download(
        repo_id=HF_DATASET_ID,
        repo_type="dataset",
        local_dir=str(out_path),
        allow_patterns=allow_patterns,
        token=token,
    )

    hf_raw_subdir = out_path / "raw_data"
    moved_files = 0
    if hf_raw_subdir.exists():
        for chunk in glob.glob(os.path.join(str(hf_raw_subdir), "*", "*", "*.jsonl")):
            rel = os.path.relpath(chunk, str(hf_raw_subdir))
            dst = out_path / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.replace(chunk, dst)
            moved_files += 1
        shutil.rmtree(hf_raw_subdir, ignore_errors=True)

    hf_cache = out_path / ".cache"
    if hf_cache.exists():
        shutil.rmtree(hf_cache, ignore_errors=True)

    pruned = _prune_extra_local(out_path, set(days), set(cats)) if prune_extra else 0
    local_files = sum(
        1 for d in days for c in cats for _ in (out_path / d / c).glob("*.jsonl") if (out_path / d / c).is_dir()
    )
    print(
        f"[OK] Synced {moved_files} files | Local canonical files: {local_files} | Pruned extras: {pruned}",
        flush=True,
    )
    return {
        "from_date": from_date,
        "to_date": to_date,
        "categories": list(cats),
        "moved_files": moved_files,
        "local_files": local_files,
        "pruned_extras": pruned,
        "output_dir": str(out_path.resolve()),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-date", default=CANONICAL_START_DATE)
    parser.add_argument("--to-date", default=TEST_SPLIT_END_DATE)
    parser.add_argument("--categories", nargs="+", default=["bus", "incidents"])
    parser.add_argument("--output-dir", default=RAW_DATA_DIR)
    parser.add_argument("--prune-extra", action="store_true")
    args = parser.parse_args(argv)
    sync_from_hf(
        from_date=args.from_date,
        to_date=args.to_date,
        categories=args.categories,
        output_dir=args.output_dir,
        prune_extra=args.prune_extra,
    )


if __name__ == "__main__":
    main()
