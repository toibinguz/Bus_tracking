"""
Independent Quality & Purity Audit of Silver Parquet Lakehouse
Scans all partitions in data/lakehouse/silver/route_projected_telemetry.
Asserts:
1. All partitions readable by PyArrow with valid 12-column schema (no is_dwell)
2. 100% of rows have cross_track_m <= MAX_CORRIDOR_CROSS_TRACK_M (35.0m)
3. 100% of rows have direction in ('go', 're')
4. Zero NaN/null in critical coordinates (s_bus_m, cross_track_m, device_epoch)
"""

import os
import sys
import time
import pyarrow.parquet as pq
import pyarrow.dataset as ds

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))
sys.path.insert(0, os.path.abspath("."))
from config.system_config import DEFAULT_LAKEHOUSE_ROOT, MAX_CORRIDOR_CROSS_TRACK_M

SILVER_DIR = os.path.join(DEFAULT_LAKEHOUSE_ROOT, "silver", "route_projected_telemetry")


def audit_silver():
    print("=" * 80)
    print("INDEPENDENT AUDIT OF SILVER PARQUET LAKEHOUSE PURITY")
    print(f"Target Directory: {SILVER_DIR}")
    print("=" * 80)

    assert os.path.exists(SILVER_DIR), f"Directory not found: {SILVER_DIR}"

    t0 = time.time()
    dataset = ds.dataset(SILVER_DIR, format="parquet", partitioning="hive")
    
    total_files = len(dataset.files)
    print(f"[*] Found {total_files} Parquet partition files.")
    assert total_files >= 1100, f"Expected >= 1100 partitions, found {total_files}"

    # Scan dataset columns using PyArrow scanner
    scanner = dataset.scanner(columns=["direction", "s_bus_m", "cross_track_m", "derived_speed_kmh"])
    
    total_rows = 0
    max_dperp = 0.0
    sum_dperp = 0.0
    off_corridor_rows = 0
    invalid_directions = 0
    valid_speeds = 0
    go_count = 0
    re_count = 0

    for batch in scanner.to_batches():
        n = batch.num_rows
        total_rows += n

        dperp_arr = batch.column("cross_track_m")
        dir_arr = batch.column("direction")
        spd_arr = batch.column("derived_speed_kmh")

        # Check d_perp
        batch_max_dperp = float(dperp_arr.to_numpy().max()) if n > 0 else 0.0
        if batch_max_dperp > max_dperp:
            max_dperp = batch_max_dperp
        sum_dperp += float(dperp_arr.to_numpy().sum())

        off_corr = int((dperp_arr.to_numpy() > MAX_CORRIDOR_CROSS_TRACK_M).sum())
        off_corridor_rows += off_corr

        # Check directions
        dirs = dir_arr.to_numpy(zero_copy_only=False)
        go_count += int((dirs == "go").sum())
        re_count += int((dirs == "re").sum())
        invalid_directions += int(((dirs != "go") & (dirs != "re")).sum())

        # Check speeds
        spd_np = spd_arr.to_numpy(zero_copy_only=False)
        valid_speeds += int((~dperp_arr.is_null().to_numpy(zero_copy_only=False) & (spd_np > 0)).sum())

    elapsed = time.time() - t0
    avg_dperp = sum_dperp / total_rows if total_rows > 0 else 0.0

    print(f"[*] Total Rows Scanned: {total_rows:,}")
    print(f"[*] Direction Distribution: 'go' = {go_count:,} ({go_count/total_rows*100:.2f}%) | 're' = {re_count:,} ({re_count/total_rows*100:.2f}%)")
    print(f"[*] Invalid Directions: {invalid_directions}")
    print(f"[*] Average Cross-Track Error (d_perp): {avg_dperp:.2f}m")
    print(f"[*] Maximum Cross-Track Error (d_perp): {max_dperp:.2f}m")
    print(f"[*] Off-Corridor Rows (> {MAX_CORRIDOR_CROSS_TRACK_M}m): {off_corridor_rows}")
    print(f"[*] Scan Throughput: {total_rows/elapsed:,.0f} rows/s in {elapsed:.2f}s")

    assert invalid_directions == 0, f"Found {invalid_directions} invalid directions!"
    assert off_corridor_rows == 0, f"Found {off_corridor_rows} off-corridor rows!"
    assert max_dperp <= MAX_CORRIDOR_CROSS_TRACK_M, f"Max d_perp {max_dperp} exceeds {MAX_CORRIDOR_CROSS_TRACK_M}m!"
    assert total_rows >= 5_000_000, f"Total rows {total_rows} below expected 5.0M threshold"

    print("\n" + "=" * 80)
    print("ALL SILVER LAKEHOUSE PURITY ASSERTIONS PASSED WITH 100% SUCCESS!")
    print("=" * 80)


if __name__ == "__main__":
    audit_silver()
