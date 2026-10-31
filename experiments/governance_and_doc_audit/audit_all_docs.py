import os
import re
import sys

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

docs = sorted([f for f in os.listdir("docs") if f.endswith(".md")])
print(f"Total docs found: {len(docs)}")

doc_inventory = []

for d in docs:
    path = os.path.join("docs", d)
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
        lines = [l.strip() for l in content.splitlines() if l.strip()]
        title = lines[0] if lines else "Untitled"
        subtitle = lines[1] if len(lines) > 1 else ""
        
        has_osm = bool(re.search(r"\bOSM\b|OpenStreetMap", content, re.IGNORECASE))
        has_timbus = bool(re.search(r"\bTimBus\b|TRAMOC", content, re.IGNORECASE))
        has_tomtom_flow = bool(re.search(r"\bflow\b|FlowSegmentData|19 điểm nghẽn", content, re.IGNORECASE))
        has_module_5 = bool(re.search(r"module_4|module_5", content, re.IGNORECASE))
        has_3_canonical = bool(re.search(r"3 module chính tắc|canonical 3-tier", content, re.IGNORECASE))
        has_travel_time_matrix = bool(re.search(r"ma trận thời gian|travel time matrix|agg_segment_travel_times", content, re.IGNORECASE))
        
        doc_inventory.append({
            "filename": d,
            "title": title,
            "lines_count": len(lines),
            "has_osm": has_osm,
            "has_timbus": has_timbus,
            "has_tomtom_flow": has_tomtom_flow,
            "has_module_5": has_module_5,
            "has_3_canonical": has_3_canonical,
            "has_travel_time_matrix": has_travel_time_matrix
        })

for item in doc_inventory:
    flags = []
    if item['has_osm']: flags.append("OSM")
    if item['has_timbus']: flags.append("TimBus")
    if item['has_tomtom_flow']: flags.append("TomTomFlow")
    if item['has_module_5']: flags.append("5-Modules")
    if item['has_3_canonical']: flags.append("3-Canonical")
    if item['has_travel_time_matrix']: flags.append("TravelTimeMatrix")
    flag_str = f"[{', '.join(flags)}]" if flags else ""
    print(f"{item['filename']:50s} | {flag_str}")
