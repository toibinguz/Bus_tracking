"""Hardware resource inspection, priority throttling, and OOM/thermal guards for heavy batch & training jobs."""

from __future__ import annotations

import gc
import math
import os
import shutil
import subprocess
import time
from typing import Any, Dict, Optional

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None  # type: ignore[assignment]


def _query_gpu() -> Optional[Dict[str, Any]]:
    """Query primary NVIDIA GPU metrics via nvidia-smi without failing on CPU-only hosts."""
    try:
        proc = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.free,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return None
        first_line = proc.stdout.strip().splitlines()[0]
        parts = [p.strip() for p in first_line.split(",")]
        if len(parts) < 4:
            return None
        return {
            "name": parts[0],
            "vram_total_mb": int(float(parts[1])),
            "vram_free_mb": int(float(parts[2])),
            "temp_c": int(float(parts[3])),
        }
    except Exception:
        return None


def inspect_hardware(path: str = ".") -> Dict[str, Any]:
    """Return current CPU, RAM, Disk, and GPU status."""
    cpu_logical = os.cpu_count() or 2
    if psutil is not None:
        cpu_physical = psutil.cpu_count(logical=False) or cpu_logical
        vm = psutil.virtual_memory()
        ram_total_gb = vm.total / 1e9
        ram_avail_gb = vm.available / 1e9
    else:  # pragma: no cover
        cpu_physical = max(1, cpu_logical // 2)
        ram_total_gb = 0.0
        ram_avail_gb = 0.0
    disk_free_gb = shutil.disk_usage(path).free / 1e9
    return {
        "cpu_physical": int(cpu_physical),
        "cpu_logical": int(cpu_logical),
        "ram_total_gb": round(ram_total_gb, 2),
        "ram_avail_gb": round(ram_avail_gb, 2),
        "disk_free_gb": round(disk_free_gb, 2),
        "gpu": _query_gpu(),
    }


def set_process_below_normal_priority() -> None:
    """Lower process scheduling priority so heavy batch jobs do not freeze desktop UI responsiveness."""
    if psutil is None:
        return
    try:
        proc = psutil.Process(os.getpid())
        if os.name == "nt":
            proc.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
        else:  # pragma: no cover
            proc.nice(10)
    except Exception:
        pass


def recommended_xgb_threads() -> int:
    """Cap XGBoost CPU threads to leave cores responsive for OS and background services."""
    phys = (psutil.cpu_count(logical=False) if psutil is not None else None) or os.cpu_count() or 4
    return min(4, max(2, int(phys) // 2))


def recommend_workers(
    requested: int,
    per_worker_ram_gb: float = 0.8,
    min_free_ram_gb: float = 2.0,
    max_cpu_frac: float = 0.6,
) -> int:
    """Compute a safe worker count bounded by physical cores and available RAM headroom."""
    req = max(1, int(requested))
    hw = inspect_hardware()
    cpu_cap = max(1, int(math.floor(hw["cpu_physical"] * max_cpu_frac)))
    if hw["ram_avail_gb"] > 0.0:
        ram_budget = max(0.0, hw["ram_avail_gb"] - min_free_ram_gb)
        ram_cap = max(1, int(ram_budget // max(0.1, per_worker_ram_gb)))
    else:  # pragma: no cover
        ram_cap = cpu_cap
    chosen = max(1, min(req, cpu_cap, ram_cap))
    if chosen < req:
        print(
            f"[HW-GUARD] Capped workers {req} -> {chosen} "
            f"(avail_ram={hw['ram_avail_gb']:.2f}GB, phys_cpu={hw['cpu_physical']}, "
            f"est_per_worker={per_worker_ram_gb:.1f}GB)",
            flush=True,
        )
    return chosen


def check_memory_pressure(
    min_free_ram_gb: float = 1.5,
    abort_ram_gb: float = 0.85,
    label: str = "",
) -> float:
    """Check available RAM; trigger GC on warning and abort cleanly before swap freeze."""
    if psutil is None:  # pragma: no cover
        return -1.0
    avail_gb = psutil.virtual_memory().available / 1e9
    ctx = f" [{label}]" if label else ""
    if avail_gb < min_free_ram_gb:
        gc.collect()
        avail_gb = psutil.virtual_memory().available / 1e9
        print(f"[HW-WARN] Low free RAM: {avail_gb:.2f} GB{ctx} — ran gc.collect().", flush=True)
    if avail_gb < abort_ram_gb:
        raise MemoryError(
            f"[HW-ABORT] Available RAM dropped to {avail_gb:.2f} GB (< {abort_ram_gb:.2f} GB){ctx}; "
            "aborting cleanly to prevent OS freeze."
        )
    return avail_gb


def check_gpu_thermal_and_vram(
    min_free_vram_mb: int = 2200,
    warn_temp_c: int = 82,
    pause_temp_c: int = 88,
    max_wait_sec: int = 60,
) -> Dict[str, Any]:
    """Verify GPU thermal headroom and free VRAM before CUDA training; recommend CPU fallback if constrained."""
    gpu = _query_gpu()
    if gpu is None:
        print("[HW-WARN] No NVIDIA GPU detected via nvidia-smi; falling back to CPU.", flush=True)
        return {"use_cuda": False, "reason": "no_gpu", "overheated": False, "gpu": None}

    waited = 0
    while gpu["temp_c"] >= pause_temp_c and waited < max_wait_sec:
        print(
            f"[HW-WARN] GPU temperature {gpu['temp_c']}C >= {pause_temp_c}C — cooling pause ({waited}/{max_wait_sec}s)...",
            flush=True,
        )
        time.sleep(5)
        waited += 5
        gpu = _query_gpu() or gpu

    if gpu["temp_c"] >= pause_temp_c:
        print(
            f"[HW-WARN] GPU remained overheated at {gpu['temp_c']}C after {waited}s — aborting CUDA use.",
            flush=True,
        )
        return {"use_cuda": False, "reason": f"gpu_overheat_{gpu['temp_c']}C", "overheated": True, "gpu": gpu}

    if gpu["temp_c"] >= warn_temp_c:
        print(f"[HW-WARN] GPU temperature elevated: {gpu['temp_c']}C (warn >= {warn_temp_c}C).", flush=True)

    if gpu["vram_free_mb"] < min_free_vram_mb:
        print(
            f"[HW-WARN] GPU free VRAM {gpu['vram_free_mb']} MiB < {min_free_vram_mb} MiB — falling back to CPU.",
            flush=True,
        )
        return {"use_cuda": False, "reason": f"low_vram_{gpu['vram_free_mb']}mb", "overheated": False, "gpu": gpu}

    return {"use_cuda": True, "reason": "ok", "overheated": False, "gpu": gpu}
