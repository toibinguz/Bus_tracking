import os

docs = sorted([f for f in os.listdir("docs") if f.endswith(".md")])

for d in docs:
    path = os.path.join("docs", d)
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        head = [f.readline() for _ in range(5)]
    has_banner = any("DEPRECATED" in line or "CANONICAL" in line or "[!" in line for line in head)
    if has_banner:
        print(f"Already has banner: {d}")
