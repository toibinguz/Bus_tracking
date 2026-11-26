"""
Giai đoạn 1 — Quét Tĩnh AST (Hardcode, Magic Numbers, Silent Except, Dead SSOT Constants).

Chỉ đọc (Read-Only) 74 file Python production trong:
  - config/
  - module_1_data_ingestion_and_preprocessing/
  - module_2_big_data_storage_and_lakehouse/
  - module_3_bus_eta_prediction/

Xuất evidence ra:
  - docs/evidence/codebase_audit_20261126/01_static_hygiene.json
  - docs/evidence/codebase_audit_20261126/01_static_hygiene.md
"""

from __future__ import annotations

import ast
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "docs" / "evidence" / "codebase_audit_20261126"
SCAN_DIRS = (
    "config",
    "module_1_data_ingestion_and_preprocessing",
    "module_2_big_data_storage_and_lakehouse",
    "module_3_bus_eta_prediction",
)
SYSTEM_CONFIG_REL = "config/system_config.py"
TZ_HANOI = timezone(timedelta(hours=7))

DOMAIN_THRESHOLDS = {
    -0.2,
    0.04,
    0.15,
    0.35,
    0.4,
    0.5,
    0.6,
    5.0,
    10.0,
    15.0,
    20.0,
    30.0,
    35.0,
    45.0,
    60.0,
    75.0,
    80.0,
    90.0,
    120.0,
    150.0,
    180.0,
    200.0,
    250.0,
    300.0,
    540.0,
    750.0,
    900.0,
    1800.0,
    2700.0,
    25000.0,
}
TRIVIAL_CONSTANTS = {0, 1, -1, 2, 100, 3.6}
DOMAIN_ENUM_STRINGS = {"go", "re", "UN_TAC", "THONG_THOANG", "BINH_THUONG"}
PATH_PREFIXES = ("data/", "experiments/", "runtime/", "http://", "https://")
LOG_OR_RAISE_FUNCS = {"debug", "info", "warning", "warn", "error", "exception", "critical", "print", "write"}


def collect_production_files() -> list[Path]:
    files: list[Path] = []
    for d in SCAN_DIRS:
        base = ROOT / d
        if base.exists():
            files.extend(sorted(p for p in base.rglob("*.py") if "__pycache__" not in p.parts))
    return files


def extract_number(node: ast.AST) -> float | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return float(node.value)
    if (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, ast.USub)
        and isinstance(node.operand, ast.Constant)
        and isinstance(node.operand.value, (int, float))
        and not isinstance(node.operand.value, bool)
    ):
        return -float(node.operand.value)
    return None


def _has_logging_or_status_effect(stmts: list[ast.stmt]) -> bool:
    for node in ast.walk(ast.Module(body=stmts, type_ignores=[])):
        if isinstance(node, ast.Raise):
            return True
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in LOG_OR_RAISE_FUNCS:
                return True
            if isinstance(node.func, ast.Attribute) and node.func.attr in LOG_OR_RAISE_FUNCS:
                return True
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                src = ast.unparse(tgt).lower()
                if any(k in src for k in ("status", "error", "err", "reason", "fallback", "streak", "circuit")):
                    return True
    return False


def _is_silent_stmt(stmt: ast.stmt) -> bool:
    if isinstance(stmt, (ast.Pass, ast.Continue, ast.Break)):
        return True
    if isinstance(stmt, ast.Return):
        val = stmt.value
        if val is None:
            return True
        if isinstance(val, ast.Constant) and val.value in (None, "", 0, 0.0, False):
            return True
        if isinstance(val, (ast.List, ast.Dict, ast.Tuple, ast.Set)) and len(val.elts if hasattr(val, "elts") else val.keys) == 0:
            return True
    return False


def scan_file(rel_path: str, source: str) -> dict[str, Any]:
    tree = ast.parse(source, filename=rel_path)
    lines = source.splitlines()
    s1_magic: list[dict[str, Any]] = []
    s2_strings: list[dict[str, Any]] = []
    s3_silent: list[dict[str, Any]] = []

    is_ssot = rel_path == SYSTEM_CONFIG_REL

    # Track parent nodes for Compare / BinOp / Assign context
    for node in ast.walk(tree):
        # S1: Magic numbers in Compare or BinOp outside system_config.py
        if not is_ssot and isinstance(node, (ast.Compare, ast.BinOp)):
            children = [node.left, *node.comparators] if isinstance(node, ast.Compare) else [node.left, node.right]
            context_kind = "Compare" if isinstance(node, ast.Compare) else "BinOp"
            for child in children:
                num = extract_number(child)
                if num is None:
                    continue
                if num in TRIVIAL_CONSTANTS and context_kind != "Compare":
                    continue
                if context_kind == "Compare" and num in {0.0, 1.0, -1.0, 2.0, 100.0}:
                    continue
                if num in DOMAIN_THRESHOLDS:
                    lineno = getattr(child, "lineno", getattr(node, "lineno", 0))
                    snippet = lines[lineno - 1].strip() if 1 <= lineno <= len(lines) else ""
                    # Avoid double noise on pure loop/datetime/format trivial arithmetic
                    if context_kind == "BinOp" and num in {60.0} and ("epoch" not in snippet and "eta" not in snippet and "age" not in snippet and "ttl" not in snippet.lower()):
                        continue
                    s1_magic.append(
                        {
                            "file": rel_path,
                            "line": lineno,
                            "value": num,
                            "context": context_kind,
                            "snippet": snippet[:160],
                        }
                    )

        # S2: Hardcoded paths / URLs / repeated domain enum strings outside SSOT
        if not is_ssot and isinstance(node, ast.Constant) and isinstance(node.value, str):
            val = node.value
            lineno = getattr(node, "lineno", 0)
            snippet = lines[lineno - 1].strip() if 1 <= lineno <= len(lines) else ""
            if any(val.startswith(p) for p in PATH_PREFIXES):
                s2_strings.append({"file": rel_path, "line": lineno, "kind": "path_or_url", "value": val[:120], "snippet": snippet[:160]})
            elif val in DOMAIN_ENUM_STRINGS:
                s2_strings.append({"file": rel_path, "line": lineno, "kind": "domain_enum", "value": val, "snippet": snippet[:160]})

        # S3: Silent except handlers
        if isinstance(node, ast.ExceptHandler):
            exc_name = ast.unparse(node.type) if node.type is not None else "BARE_EXCEPT"
            is_broad = node.type is None or "Exception" in exc_name or "BaseException" in exc_name
            if not is_broad:
                continue
            body = node.body
            if all(_is_silent_stmt(st) for st in body) and not _has_logging_or_status_effect(body):
                lineno = getattr(node, "lineno", 0)
                handler_src = " ; ".join(ast.unparse(st) for st in body)
                snippet = lines[lineno - 1].strip() if 1 <= lineno <= len(lines) else ""
                s3_silent.append(
                    {
                        "file": rel_path,
                        "line": lineno,
                        "exc_type": exc_name,
                        "body": handler_src[:120],
                        "snippet": snippet[:160],
                    }
                )

    # Deduplicate (file, line, value)
    seen_s1 = set()
    dedup_s1 = []
    for x in s1_magic:
        k = (x["file"], x["line"], x["value"])
        if k not in seen_s1:
            seen_s1.add(k)
            dedup_s1.append(x)

    return {"s1": dedup_s1, "s2": s2_strings, "s3": s3_silent}


def audit_unused_ssot_constants(prod_files: list[Path]) -> dict[str, Any]:
    ssot_path = ROOT / SYSTEM_CONFIG_REL
    ssot_src = ssot_path.read_text(encoding="utf-8")
    tree = ast.parse(ssot_src, filename=SYSTEM_CONFIG_REL)
    constants: list[tuple[str, int]] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and re.fullmatch(r"[A-Z][A-Z0-9_]+", tgt.id):
                    constants.append((tgt.id, node.lineno))

    other_prod_src = "\n".join(
        p.read_text(encoding="utf-8") for p in prod_files if p.relative_to(ROOT).as_posix() != SYSTEM_CONFIG_REL
    )
    scripts_src = "\n".join(
        p.read_text(encoding="utf-8", errors="ignore")
        for p in sorted((ROOT / "scripts").rglob("*.py"))
        if "audit" not in p.parts
    )
    tests_src = "\n".join(
        p.read_text(encoding="utf-8", errors="ignore")
        for p in sorted((ROOT / "tests").rglob("*.py"))
    )

    unused_in_prod: list[dict[str, Any]] = []
    unused_everywhere: list[dict[str, Any]] = []
    for name, lineno in constants:
        pat = re.compile(rf"\b{re.escape(name)}\b")
        in_prod = bool(pat.search(other_prod_src))
        in_scripts = bool(pat.search(scripts_src))
        in_tests = bool(pat.search(tests_src))
        if not in_prod:
            item = {"name": name, "line": lineno, "in_scripts": in_scripts, "in_tests": in_tests}
            unused_in_prod.append(item)
            if not in_scripts and not in_tests:
                unused_everywhere.append(item)

    return {
        "total_ssot_constants": len(constants),
        "unused_in_prod_count": len(unused_in_prod),
        "unused_everywhere_count": len(unused_everywhere),
        "unused_in_prod": unused_in_prod,
        "unused_everywhere": unused_everywhere,
    }


def run_self_test() -> dict[str, bool]:
    sample = '''
def bad_fn(x, d):
    if d > 35.0:
        path = "data/fake.db"
    try:
        return x / 0
    except Exception:
        return None
'''
    res = scan_file("synthetic_test.py", sample)
    ok_s1 = any(x["value"] == 35.0 and x["context"] == "Compare" for x in res["s1"])
    ok_s2 = any(x["value"] == "data/fake.db" for x in res["s2"])
    ok_s3 = len(res["s3"]) == 1 and res["s3"][0]["exc_type"] == "Exception"
    assert ok_s1 and ok_s2 and ok_s3, f"Self-test failed: {res}"
    return {"s1_detected": ok_s1, "s2_detected": ok_s2, "s3_detected": ok_s3}


def render_markdown(report: dict[str, Any]) -> str:
    s1 = report["S1_magic_numbers"]
    s2 = report["S2_hardcoded_strings"]
    s3 = report["S3_silent_excepts"]
    s4 = report["S4_ssot_constants"]
    lines = [
        "# Giai đoạn 1 — Evidence Quét Tĩnh AST (Static Hygiene)",
        "",
        f"- **Thời điểm chạy:** `{report['generated_at']}`",
        f"- **Số file production đã parse AST:** `{report['files_scanned']}` (lỗi cú pháp: `{report['parse_errors']}`).",
        f"- **Self-test detector tổng hợp:** `{report['self_test']}`.",
        "",
        "| Hạng mục | Tổng số phát hiện |",
        "| :--- | ---: |",
        f"| S1. Magic numbers ngưỡng miền ngoài `config/system_config.py` | `{len(s1)}` |",
        f"| S2. Chuỗi đường dẫn / URL / enum domain hardcode ngoài SSOT | `{len(s2)}` |",
        f"| S3. Khối `except Exception` / bare `except` nuốt lỗi im lặng | `{len(s3)}` |",
        f"| S4. Hằng số `config/system_config.py` chưa dùng trong production (`module_1..3`) | `{s4['unused_in_prod_count']} / {s4['total_ssot_constants']}` |",
        f"| S4b. Hằng số `config/system_config.py` chưa dùng ở cả `module_*`, `scripts/` và `tests/` | `{s4['unused_everywhere_count']} / {s4['total_ssot_constants']}` |",
        "",
        "---",
        "",
        "## S1. Magic Numbers ngoài `config/system_config.py`",
        "",
        "| File | Dòng | Giá trị | Ngữ cảnh | Đoạn mã |",
        "| :--- | ---: | ---: | :---: | :--- |",
    ]
    for x in s1:
        snip = x["snippet"].replace("|", "\\|")
        lines.append(f"| `{x['file']}` | `{x['line']}` | `{x['value']}` | `{x['context']}` | `{snip}` |")

    lines.extend(
        [
            "",
            "---",
            "",
            "## S2. Chuỗi Đường dẫn, URL và Enum Domain ngoài SSOT",
            "",
            "| File | Dòng | Loại | Giá trị | Đoạn mã |",
            "| :--- | ---: | :--- | :--- | :--- |",
        ]
    )
    for x in s2:
        snip = x["snippet"].replace("|", "\\|")
        lines.append(f"| `{x['file']}` | `{x['line']}` | `{x['kind']}` | `{x['value']}` | `{snip}` |")

    lines.extend(
        [
            "",
            "---",
            "",
            "## S3. Khối `except` Nuốt lỗi Im lặng (Silent Exception Handlers)",
            "",
            "| File | Dòng | Kiểu ngoại lệ | Thân xử lý | Ngữ cảnh |",
            "| :--- | ---: | :--- | :--- | :--- |",
        ]
    )
    for x in s3:
        snip = x["snippet"].replace("|", "\\|")
        body = x["body"].replace("|", "\\|")
        lines.append(f"| `{x['file']}` | `{x['line']}` | `{x['exc_type']}` | `{body}` | `{snip}` |")

    lines.extend(
        [
            "",
            "---",
            "",
            "## S4. Hằng số `config/system_config.py` Không dùng trong Production (`module_1..3`)",
            "",
            "| Tên hằng số | Dòng | Dùng trong `scripts/`? | Dùng trong `tests/`? |",
            "| :--- | ---: | :---: | :---: |",
        ]
    )
    for x in s4["unused_in_prod"]:
        lines.append(f"| `{x['name']}` | `{x['line']}` | `{x['in_scripts']}` | `{x['in_tests']}` |")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    self_test = run_self_test()
    prod_files = collect_production_files()
    all_s1: list[dict[str, Any]] = []
    all_s2: list[dict[str, Any]] = []
    all_s3: list[dict[str, Any]] = []
    parse_errors = 0

    for p in prod_files:
        rel = p.relative_to(ROOT).as_posix()
        try:
            src = p.read_text(encoding="utf-8")
            out = scan_file(rel, src)
            all_s1.extend(out["s1"])
            all_s2.extend(out["s2"])
            all_s3.extend(out["s3"])
        except SyntaxError:
            parse_errors += 1

    s4 = audit_unused_ssot_constants(prod_files)

    report = {
        "generated_at": datetime.now(TZ_HANOI).strftime("%Y-%m-%d %H:%M:%S%z"),
        "files_scanned": len(prod_files),
        "parse_errors": parse_errors,
        "self_test": self_test,
        "S1_magic_numbers": all_s1,
        "S2_hardcoded_strings": all_s2,
        "S3_silent_excepts": all_s3,
        "S4_ssot_constants": s4,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUT_DIR / "01_static_hygiene.json"
    md_path = OUT_DIR / "01_static_hygiene.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    print(f"Scanned {len(prod_files)} files (parse_errors={parse_errors}); S1={len(all_s1)}, S2={len(all_s2)}, S3={len(all_s3)}, S4_unused_prod={s4['unused_in_prod_count']}, S4_unused_everywhere={s4['unused_everywhere_count']}")


if __name__ == "__main__":
    main()
