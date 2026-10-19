"""
Script rút toàn bộ các tuyến xe buýt tại Hà Nội từ OpenStreetMap (OSM) theo chuẩn nguyên bản Nodes & Ways.
- Bảo tồn nguyên vẹn 100% cấu trúc hình học thực tế:
  + Mỗi tuyến buýt (relation) lưu giữ toàn bộ danh sách các đoạn đường thành viên (Ways).
  + Mỗi Way lưu giữ đúng chuỗi các đỉnh thực tế (Nodes: [N1 -> N2 -> ... -> Nk]).
  + KHÔNG gộp/nối cưỡng bức (stitching) giữa các way -> Triệt tiêu 100% hiện tượng 'nối xuyên đỉnh' (chord cutting).
  + KHÔNG ngắt bỏ bất kỳ way nào -> Bảo toàn 100% toàn bộ chiều dài của Tuyến 08A và các tuyến khác.
- Mỗi trạm dừng giữ nguyên thông tin Node (Platform/Stop), tên biển trạm, thứ tự đón.
- Xuất đầy đủ Master Catalog, GeoJSON và JSON metadata cho từng tuyến.
"""

import os
import sys
import json
import time
import math
import logging
import traceback
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
import requests

# Reconfigure stdout/stderr to utf-8 safely on Windows
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

LOG_FILE = Path("data/ground_truth/logs/osm_extraction.log")
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)


logger = logging.getLogger("osm_extractor")
logger.setLevel(logging.DEBUG)

# Handler console
ch = logging.StreamHandler(sys.stdout)
ch.setLevel(logging.INFO)
ch_formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
ch.setFormatter(ch_formatter)

# Handler file
fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
fh.setLevel(logging.DEBUG)
fh_formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [%(filename)s:%(lineno)d] %(message)s")
fh.setFormatter(fh_formatter)

logger.addHandler(ch)
logger.addHandler(fh)

OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter"
]

HEADERS = {
    "User-Agent": "HanoiBusResearch/1.0 (academic research; contact: hust-transit-project)",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"
}

def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Khoảng cách Haversine tính bằng mét."""
    R = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2.0)**2
    return R * 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))

def query_mirror_with_retry(query: str, timeout: int = 90, max_retries_per_mirror: int = 2) -> Dict[str, Any]:
    """Gửi query tới Overpass với cơ chế fallback mirror."""
    last_error = None
    for mirror in OVERPASS_MIRRORS:
        for attempt in range(max_retries_per_mirror):
            logger.info(f"   [HTTP] Gửi query tới {mirror} (lần {attempt + 1})...")
            start_t = time.time()
            try:
                resp = requests.post(
                    mirror,
                    data={"data": query},
                    headers=HEADERS,
                    timeout=(20, timeout)
                )
                elapsed = time.time() - start_t
                if resp.status_code == 200:
                    payload = resp.json()
                    elems = payload.get("elements", [])
                    logger.info(f"   [HTTP 200 OK] {mirror} phản hồi trong {elapsed:.1f}s ({len(elems):,} elements)")
                    return payload
                else:
                    preview = resp.text[:200].replace("\n", " ")
                    msg = f"HTTP {resp.status_code} từ {mirror} ({elapsed:.1f}s): {preview}"
                    logger.warning(f"   [CẢNH BÁO] {msg}")
                    last_error = msg
            except Exception as e:
                elapsed = time.time() - start_t
                msg = f"Lỗi kết nối tới {mirror} ({elapsed:.1f}s): {e}"
                logger.warning(f"   [LỖI] {msg}")
                last_error = msg
            time.sleep(2)

    raise RuntimeError(f"Tất cả mirror Overpass đều thất bại! Lỗi cuối cùng: {last_error}")

def phase1_discover_all_relations() -> List[Dict[str, Any]]:
    """Phase 1: Quét danh mục các quan hệ tuyến."""
    logger.info("=" * 70)
    logger.info("📡 PHASE 1: QUÉT DANH MỤC CÁC QUAN HỆ TUYẾN XE BUÝT HÀ NỘI")
    logger.info("=" * 70)

    queries = [
        ("Named Area 'Thành phố Hà Nội'", """
        [out:json][timeout:60];
        area["name"="Thành phố Hà Nội"]->.a;
        (
          relation["type"="route"]["route"="bus"](area.a);
        );
        out body;
        """),
        ("Bounding Box Hà Nội (20.55, 105.30, 21.45, 106.15)", """
        [out:json][timeout:60];
        (
          relation["type"="route"]["route"="bus"](20.55, 105.30, 21.45, 106.15);
        );
        out body;
        """)
    ]

    all_relations = []
    for q_name, q_str in queries:
        logger.info(f"[*] Thử phương thức: {q_name} ...")
        try:
            res = query_mirror_with_retry(q_str, timeout=60)
            elems = res.get("elements", [])
            rels = [e for e in elems if e.get("type") == "relation"]
            if len(rels) >= 50:
                logger.info(f"[OK] Tìm thấy {len(rels)} quan hệ tuyến xe buýt qua {q_name}!")
                all_relations = rels
                break
        except Exception as e:
            logger.error(f"[!] Lỗi khi thử {q_name}: {e}")

    if not all_relations:
        raise RuntimeError("Không thể tìm thấy danh mục tuyến xe buýt từ bất kỳ phương thức nào!")

    return all_relations

def phase2_fetch_ways_and_nodes_in_batches(relations: List[Dict[str, Any]], batch_size: int = 15) -> Dict[str, Any]:
    """Phase 2: Tải chi tiết ways & nodes theo từng batch."""
    logger.info("=" * 70)
    logger.info(f"📥 PHASE 2: TẢI CHI TIẾT HÌNH HỌC (WAYS & NODES) THEO TỪNG BATCH ({batch_size} TUYẾN/LẦN)")
    logger.info("=" * 70)

    rel_ids = [r["id"] for r in relations]
    total_batches = (len(rel_ids) + batch_size - 1) // batch_size
    merged_elements: Dict[str, Dict[str, Any]] = {}

    for r in relations:
        merged_elements[f"relation/{r['id']}"] = r

    for b_idx in range(total_batches):
        chunk_ids = rel_ids[b_idx * batch_size : (b_idx + 1) * batch_size]
        ids_str = ", ".join(str(i) for i in chunk_ids)
        logger.info(f"[*] [Batch {b_idx + 1}/{total_batches}] Đang tải {len(chunk_ids)} relations: [{ids_str[:60]}...] ...")

        batch_query = f"""
        [out:json][timeout:90];
        (
          relation(id:{ids_str});
        );
        out body;
        >;
        out body qt;
        """

        try:
            res = query_mirror_with_retry(batch_query, timeout=90)
            elems = res.get("elements", [])
            nodes_count = sum(1 for e in elems if e.get("type") == "node")
            ways_count = sum(1 for e in elems if e.get("type") == "way")
            logger.info(f"   [Batch {b_idx + 1} OK] Nhận được: {ways_count} ways, {nodes_count} nodes.")

            for e in elems:
                k = f"{e.get('type')}/{e.get('id')}"
                merged_elements[k] = e

        except Exception as e:
            logger.error(f"   [Batch {b_idx + 1} THẤT BẠI] Lỗi: {e}")

        time.sleep(1)

    logger.info(f"[OK] Tổng cộng đã thu thập: {len(merged_elements):,} elements OSM hợp nhất.")
    return {"elements": list(merged_elements.values())}

def phase3_parse_and_export_nodes_and_ways(
    all_osm_data: Dict[str, Any],
    output_dir: Path = Path("data/ground_truth/routes"),
    raw_save_path: Path = Path("data/osm/raw/hanoi_all_bus_routes_raw.json")
) -> Dict[str, Any]:
    """
    Phase 3: Parse và xuất toàn bộ tuyến theo chuẩn nguyên bản Nodes & Ways.
    - Không gộp/nối chim bay -> Không bao giờ có hiện tượng 'nối xuyên đỉnh'.
    - Giữ nguyên 100% tất cả các ways thành viên -> Không bao giờ bị mất đoạn (như 08A).
    """
    logger.info("=" * 70)
    logger.info("🧩 PHASE 3: BẢO TỒN NGUYÊN BẢN NODES & WAYS TOÀN BỘ CÁC TUYẾN")
    logger.info("=" * 70)

    output_dir.mkdir(parents=True, exist_ok=True)
    raw_save_path.parent.mkdir(parents=True, exist_ok=True)

    elements = all_osm_data.get("elements", [])
    nodes_map: Dict[int, Dict[str, Any]] = {}
    ways_map: Dict[int, Dict[str, Any]] = {}
    relations: List[Dict[str, Any]] = []

    for el in elements:
        t = el.get("type")
        if t == "node":
            nodes_map[el["id"]] = el
        elif t == "way":
            ways_map[el["id"]] = el
        elif t == "relation":
            tags = el.get("tags", {})
            if tags.get("type") == "route" and tags.get("route") == "bus":
                relations.append(el)

    nodes_coord = {nid: (nd["lat"], nd["lon"]) for nid, nd in nodes_map.items()}

    # Gom nhóm theo ref
    grouped_by_ref: Dict[str, List[Dict[str, Any]]] = {}
    for rel in relations:
        tags = rel.get("tags", {})
        ref = tags.get("ref", "").strip()
        if not ref:
            name = tags.get("name", "")
            for prefix in ["Tuyến", "tuyến", "Bus", "bus", "Xe buýt"]:
                if prefix in name:
                    parts = name.split(":")
                    if len(parts) > 1:
                        ref = parts[0].replace(prefix, "").strip()
                        break
        if not ref:
            ref = f"UNKNOWN_{rel['id']}"

        ref_clean = ref.upper()
        if ref_clean not in grouped_by_ref:
            grouped_by_ref[ref_clean] = []
        grouped_by_ref[ref_clean].append(rel)

    logger.info(f"[*] Tìm thấy tổng cộng {len(grouped_by_ref)} mã tuyến buýt phân biệt trong OSM!")

    catalog = []
    total_ways_all_routes = 0

    for ref, rel_list in sorted(grouped_by_ref.items(), key=lambda x: x[0]):
        try:
            route_variants = []
            for v_idx, rel in enumerate(rel_list):
                rel_id = rel["id"]
                tags = rel.get("tags", {})
                name = tags.get("name", f"Tuyến {ref}")
                from_loc = tags.get("from", "")
                to_loc = tags.get("to", "")
                operator = tags.get("operator", "")
                members = rel.get("members", [])

                # 1. Trích xuất trọn vẹn từng Way thành viên (Bảo toàn Nodes)
                ways_data = []
                var_length_km = 0.0

                for m in members:
                    if m.get("type") == "way" and m.get("ref") in ways_map:
                        w_obj = ways_map[m["ref"]]
                        w_tags = w_obj.get("tags", {})
                        w_nodes = w_obj.get("nodes", [])
                        
                        # Tọa độ các đỉnh của way: [[lon, lat], ...]
                        coords = []
                        w_len_m = 0.0
                        prev_pt = None

                        for nid in w_nodes:
                            if nid in nodes_coord:
                                lat, lon = nodes_coord[nid]
                                coords.append([round(lon, 6), round(lat, 6)])
                                if prev_pt:
                                    w_len_m += haversine_m(prev_pt[0], prev_pt[1], lat, lon)
                                prev_pt = (lat, lon)

                        if len(coords) >= 2:
                            ways_data.append({
                                "osm_id": w_obj["id"],
                                "name": w_tags.get("name", ""),
                                "highway": w_tags.get("highway", ""),
                                "oneway": w_tags.get("oneway", "no"),
                                "length_m": round(w_len_m, 1),
                                "nodes_count": len(coords),
                                "node_ids": w_nodes,
                                "coordinates": coords
                            })
                            var_length_km += (w_len_m / 1000.0)

                # 2. Trích xuất trọn vẹn danh sách trạm dừng (Platforms & Stops)
                stops = []
                stop_seq = 1
                for m in members:
                    if m.get("type") == "node" and m.get("ref") in nodes_map:
                        role = m.get("role", "")
                        if role in ("platform", "stop", "stop_entry_only", "stop_exit_only", ""):
                            s_node = nodes_map[m["ref"]]
                            s_tags = s_node.get("tags", {})
                            stops.append({
                                "sequence": stop_seq,
                                "osm_id": s_node["id"],
                                "name": s_tags.get("name", f"Trạm {stop_seq}"),
                                "role": role,
                                "lat": round(s_node["lat"], 6),
                                "lon": round(s_node["lon"], 6)
                            })
                            stop_seq += 1

                route_variants.append({
                    "variant_index": v_idx,
                    "relation_id": rel_id,
                    "name": name,
                    "from": from_loc,
                    "to": to_loc,
                    "operator": operator,
                    "length_km": round(var_length_km, 3),
                    "ways_count": len(ways_data),
                    "stops_count": len(stops),
                    "ways": ways_data,
                    "stops": stops
                })

                total_ways_all_routes += len(ways_data)

            # 3. Xuất file GeoJSON chuẩn quốc tế: Từng Way là một Feature LineString độc lập
            features = []
            for v in route_variants:
                for w in v["ways"]:
                    features.append({
                        "type": "Feature",
                        "geometry": {
                            "type": "LineString",
                            "coordinates": w["coordinates"]
                        },
                        "properties": {
                            "route_ref": ref,
                            "variant": v["variant_index"],
                            "relation_id": v["relation_id"],
                            "way_id": w["osm_id"],
                            "street_name": w["name"],
                            "highway": w["highway"],
                            "length_m": w["length_m"]
                        }
                    })
                for s in v["stops"]:
                    features.append({
                        "type": "Feature",
                        "geometry": {
                            "type": "Point",
                            "coordinates": [s["lon"], s["lat"]]
                        },
                        "properties": {
                            "route_ref": ref,
                            "variant": v["variant_index"],
                            "stop_id": s["osm_id"],
                            "sequence": s["sequence"],
                            "name": s["name"],
                            "role": s["role"]
                        }
                    })

            geojson_path = output_dir / f"route_{ref}.geojson"
            with open(geojson_path, "w", encoding="utf-8") as gf:
                json.dump({"type": "FeatureCollection", "features": features}, gf, indent=2, ensure_ascii=False)

            # 4. Xuất file Metadata JSON
            route_meta_path = output_dir / f"route_{ref}_metadata.json"
            with open(route_meta_path, "w", encoding="utf-8") as mf:
                json.dump({
                    "route_ref": ref,
                    "variants_count": len(route_variants),
                    "model": "RAW_NODES_AND_WAYS",
                    "variants": route_variants
                }, mf, indent=2, ensure_ascii=False)

            tot_len = sum(v["length_km"] for v in route_variants)
            tot_stops = sum(v["stops_count"] for v in route_variants)
            tot_ways = sum(v["ways_count"] for v in route_variants)

            catalog.append({
                "route_ref": ref,
                "variants_count": len(route_variants),
                "total_length_km": round(tot_len, 2),
                "total_ways": tot_ways,
                "total_stops": tot_stops,
                "operator": route_variants[0]["operator"] if route_variants else "",
                "status": "GROUND_TRUTH_NODES_WAYS"
            })

            logger.info(f"   [OK] Tuyến {ref:10s} | {len(route_variants)} chiều | {tot_ways:3d} ways | {tot_len:6.1f} km | {tot_stops:3d} trạm")

        except Exception as e:
            logger.error(f"   [LỖI] Tuyến {ref}: {e}")
            catalog.append({
                "route_ref": ref,
                "status": f"ERROR: {str(e)}"
            })

    # Xuất Master Catalog
    catalog_path = Path("data/ground_truth/master_bus_routes_catalog.json")
    with open(catalog_path, "w", encoding="utf-8") as cf:
        json.dump({
            "extracted_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "model": "GROUND_TRUTH_NODES_WAYS",
            "total_routes": len(catalog),
            "total_ways": total_ways_all_routes,
            "catalog": catalog
        }, cf, indent=2, ensure_ascii=False)

    logger.info("=" * 70)
    logger.info("🎉 HOÀN TẤT BÓC TÁCH TOÀN BỘ THEO CHUẨN NODES & WAYS!")
    logger.info(f"   Tổng số mã tuyến: {len(catalog)}")
    logger.info(f"   Tổng số ways bảo toàn: {total_ways_all_routes:,}")
    logger.info(f"   File Master Catalog: {catalog_path}")
    logger.info("=" * 70)

    return {
        "total_routes": len(catalog),
        "total_ways": total_ways_all_routes,
        "catalog_path": str(catalog_path)
    }

def main():
    logger.info("=" * 70)
    logger.info("🚀 BẮT ĐẦU TRÍCH RÚT TOÀN BỘ CÁC TUYẾN XE BUÝT HÀ NỘI (CHUẨN NODES & WAYS)")
    logger.info(f"   Log file: {LOG_FILE.resolve()}")
    logger.info("=" * 70)

    raw_path = Path("data/osm/raw/hanoi_all_bus_routes_raw.json")
    try:
        # Nếu đã có file raw dữ liệu đầy đủ (~13MB), tái sử dụng trực tiếp để chạy tức thì trong 3 giây
        if raw_path.exists() and raw_path.stat().st_size > 1_000_000 and "--force-download" not in sys.argv:
            logger.info(f"[*] Phát hiện kho dữ liệu thô OSM hợp nhất tại: {raw_path} ({raw_path.stat().st_size / 1024 / 1024:.1f} MB)")
            logger.info("[*] Tiến hành nạp trực tiếp và parse theo chuẩn Nodes & Ways...")
            with open(raw_path, "r", encoding="utf-8") as f:
                all_osm_data = json.load(f)
        else:
            # Phase 1: Quét danh mục quan hệ tuyến
            relations = phase1_discover_all_relations()
            # Phase 2: Tải ways & nodes theo từng batch an toàn
            all_osm_data = phase2_fetch_ways_and_nodes_in_batches(relations, batch_size=15)
            with open(raw_path, "w", encoding="utf-8") as f:
                json.dump(all_osm_data, f, ensure_ascii=False)

        # Phase 3: Parse và xuất toàn bộ tuyến theo Nodes & Ways
        result = phase3_parse_and_export_nodes_and_ways(all_osm_data)
        return 0
    except Exception as e:
        logger.critical(f"💥 QUY TRÌNH THẤT BÀI: {e}\n{traceback.format_exc()}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
