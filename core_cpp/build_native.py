"""Build the modular C++17 native kernel (.dll on Windows, .so on Linux/Docker)."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

NATIVE_DIR = Path(__file__).resolve().parent
CPP_SOURCES = (
    "bus_silver_projector.cpp",
    "bus_gold_baseline.cpp",
    "bus_causal_features.cpp",
)


def _find_compiler() -> str:
    candidates = [
        shutil.which("g++"),
        r"C:\msys64\ucrt64\bin\g++.exe",
        r"C:\msys64\mingw64\bin\g++.exe",
        shutil.which("clang++"),
    ]
    for cand in candidates:
        if cand and Path(cand).is_file():
            return str(cand)
    raise FileNotFoundError("No C++17 compiler (g++/clang++) found")


def build_native(output_path: Path | None = None) -> Path:
    compiler = _find_compiler()
    is_windows = os.name == "nt"
    if output_path is None:
        out_name = "bus_native_core.dll" if is_windows else "libbus_native_core.so"
        output_path = NATIVE_DIR / out_name
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    sources = [str(NATIVE_DIR / src) for src in CPP_SOURCES]
    cmd = [compiler, "-O3", "-std=c++17", "-shared"]
    if is_windows:
        cmd.extend(["-static-libgcc", "-static-libstdc++"])
    else:
        cmd.extend(["-fPIC", "-fvisibility=hidden"])
    cmd.extend(sources)
    cmd.extend(["-o", str(output_path)])

    env = os.environ.copy()
    compiler_dir = str(Path(compiler).parent)
    if is_windows and compiler_dir not in env.get("PATH", ""):
        env["PATH"] = compiler_dir + os.pathsep + env.get("PATH", "")

    print("Compiling:", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, env=env)
    print(f"Built native kernel: {output_path} ({output_path.stat().st_size:,} bytes)", flush=True)
    return output_path


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    build_native(out)
