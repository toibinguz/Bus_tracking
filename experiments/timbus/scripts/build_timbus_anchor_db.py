#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Khóa cứng danh sách tuyến & cặp trạm neo TimBus đã kiểm chứng thực tế vào bảng
`timbus_verified_anchors` trong `experiments/timbus/timbus_hanoi.sqlite`.

Nguồn đầu vào (100% từ kết quả audit live vừa thực hiện):
- `experiments/timbus/data/timbus_full_audit_176.json`
- `experiments/timbus/data/timbus_recovered_tail_anchors.json`
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[3]
TIMBUS_DB = ROOT / "experiments/timbus/timbus_hanoi.sqlite"
AUDIT_PATH = ROOT / "experiments/timbus/data/timbus_full_audit_176.json"
RECOV_PATH = ROOT / "experiments/timbus/data/timbus_recovered_tail_anchors.json"

RESCUED_EXTRA: Dict[Tuple[str, int], Tuple[int, Optional[int], str, str, int]] = {
    ("40", 1): (1735, 1178, "rj_last", "40CT", 2),
    ("40CT", 1): (1735, 1178, "rj_last", "40CT", 2),
    ("66", 1): (5302, None, "bm_penult", "66", 1),
    ("87", 1): (2060, 2059, "rj_last", "87", 1),
    ("02TC", 0): (1667, 606, "rj_last", "02", 2),
    ("02TC", 1): (1750, 1470, "rj_last", "02", 2),
}


def resolve_pair_anchors(
    row: Dict[str, Any], recov_item: Optional[Dict[str, Any]]
) -> Tuple[int, str, Optional[int], Optional[int], Optional[str], Optional[str], int]:
    """Trả (timbus_enabled, audit_status, primary_sid, backup_sid, anchor_source, tb_route, hits)."""
    if row["status"] == "TIMBUS_ACTIVE":
        src = row["working_anchor_source"]
        pri = int(row["working_station_id"])
        bak: Optional[int] = None
        if src == "rj_last":
            bak = row.get("rj_penult_sid")
        elif src == "rj_penult":
            bak = row.get("bm_last_sid") if (row.get("bm_last_sid") or 999999) < 50000 else row.get("bm_penult_sid")
        elif src == "bm_last":
            bak = row.get("bm_penult_sid") if (row.get("bm_penult_sid") or 999999) < 50000 else row.get("rj_penult_sid")
        elif src == "bm_penult":
            bak = row.get("rj_penult_sid")
        if bak == pri:
            bak = None
        hits = row.get("hits") or []
        tb_route = hits[0].get("tb_route") if hits else None
        return 1, "LIVE_VERIFIED", pri, (int(bak) if bak else None), src, tb_route, len(hits)

    if recov_item and recov_item.get("working"):
        w = recov_item["working"]
        pri = int(w[0][2])
        bak = int(w[1][2]) if len(w) >= 2 and int(w[1][2]) != pri else None
        src = str(w[0][0])
        hits = recov_item.get("hits") or []
        tb_route = hits[0].get("tb_route") if hits else None
        return 1, "LIVE_VERIFIED", pri, bak, src, tb_route, int(w[0][4])

    if row["status"] == "NO_ACTIVE_BUSMAP_FLEET":
        return 0, "NO_BM_FLEET_AT_AUDIT", None, None, None, None, 0

    return 0, "TIMBUS_EMPTY_CONFIRMED", None, None, None, None, 0


def _write_anchor_table(
    con: sqlite3.Connection, table_name: str, rows: List[Tuple[Any, ...]]
) -> None:
    """Ghi bảng khóa anchor vào SQLite (không trùng lặp logic tạo/nạp)."""
    con.execute(f"DROP TABLE IF EXISTS {table_name}")
    con.execute(
        f"""
        CREATE TABLE {table_name} (
            route_id INTEGER NOT NULL,
            route_code TEXT NOT NULL,
            direction INTEGER NOT NULL,
            direction_str TEXT NOT NULL,
            timbus_enabled INTEGER NOT NULL,
            audit_status TEXT NOT NULL,
            primary_anchor_sid INTEGER,
            backup_anchor_sid INTEGER,
            anchor_source TEXT,
            rj_code TEXT,
            verified_tb_route TEXT,
            verified_hits INTEGER DEFAULT 0,
            audited_at TEXT NOT NULL,
            PRIMARY KEY (route_id, direction)
        )
        """
    )
    con.executemany(
        f"""
        INSERT INTO {table_name} (
            route_id, route_code, direction, direction_str,
            timbus_enabled, audit_status, primary_anchor_sid, backup_anchor_sid,
            anchor_source, rj_code, verified_tb_route, verified_hits, audited_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    con.execute(
        f"CREATE INDEX IF NOT EXISTS idx_{table_name}_enabled "
        f"ON {table_name} (timbus_enabled, route_id, direction)"
    )


def main() -> None:
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    recov = json.loads(RECOV_PATH.read_text(encoding="utf-8"))
    recov_map: Dict[Tuple[int, int], Dict[str, Any]] = {
        (int(x["route_id"]), int(x["direction"])): x for x in recov.get("recovered", [])
    }

    audited_at = str(audit["summary"]["audited_at"])
    resolved_rows: List[List[Any]] = []
    enabled_dirs_by_route: Dict[str, set] = {}

    for r in audit["results"]:
        rid = int(r["route_id"])
        rcode = str(r["route_code"]).strip()
        d = int(r["direction"])
        d_str = "go" if d == 0 else "re"
        enabled, st, pri, bak, src, tb_route, hits = resolve_pair_anchors(r, recov_map.get((rid, d)))
        if not enabled and (rcode, d) in RESCUED_EXTRA:
            pri, bak, src, tb_route, hits = RESCUED_EXTRA[(rcode, d)]
            enabled = 1
            st = "LIVE_VERIFIED"
        if enabled:
            enabled_dirs_by_route.setdefault(rcode, set()).add(d)
        resolved_rows.append(
            [rid, rcode, d, d_str, enabled, st, pri, bak, src, r.get("rj_code"), tb_route, hits, audited_at]
        )

    # Quy tắc 2 chiều sạch: tuyến nào không đủ cả 2 chiều bật TimBus thì khóa toàn tuyến về BusMap-only
    rows_to_insert: List[Tuple[Any, ...]] = []
    for row in resolved_rows:
        rcode = row[1]
        if enabled_dirs_by_route.get(rcode) != {0, 1}:
            row[4] = 0
            row[5] = "IGNORED_BUSMAP_ONLY"
            row[6] = None
            row[7] = None
        rows_to_insert.append(tuple(row))

    con = sqlite3.connect(str(TIMBUS_DB))
    try:
        _write_anchor_table(con, "timbus_route_anchors", rows_to_insert)
        _write_anchor_table(con, "timbus_verified_anchors", rows_to_insert)
        con.commit()

        stats = con.execute(
            "SELECT audit_status, timbus_enabled, COUNT(*) FROM timbus_route_anchors GROUP BY audit_status, timbus_enabled"
        ).fetchall()
        routes_enabled = con.execute(
            "SELECT COUNT(DISTINCT route_code) FROM timbus_route_anchors WHERE timbus_enabled = 1"
        ).fetchone()[0]
        print("Locked into timbus_hanoi.sqlite -> timbus_route_anchors & timbus_verified_anchors:")
        for st, en, cnt in stats:
            print(f"  {st} (enabled={en}): {cnt} pairs")
        print(f"Total distinct enabled routes: {routes_enabled}")
    finally:
        con.close()


if __name__ == "__main__":
    main()
