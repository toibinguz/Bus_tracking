import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8")

conn = sqlite3.connect("data/telemetry_audit_2026_10_17_18.db")
c = conn.cursor()

tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
print(f"Tổng số bảng trong cơ sở dữ liệu ({len(tables)} bảng):")
print("-" * 55)
for t in tables:
    cnt = c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
    print(f"  {t:<35}: {cnt:>10,} bản ghi")

conn.close()

