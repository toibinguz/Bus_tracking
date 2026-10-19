"""
Runner 5.7: Master Ground-Truth Verification Pipeline
Orchestrates end-to-end ground truth route extraction, road network rebuilding,
perpendicular orthogonal projection verification, and sign-off report generation.
"""

import os
import sys
import argparse
import json
import logging

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Add workspace directory to sys.path
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(THIS_DIR)
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from module_1_telemetry_and_traffic_ingestion import (
    sync_bus_telemetry_from_hf,
    preprocess_telemetry_dataset,
    load_preprocessed_route_pings
)
from module_2_osm_ground_truth_and_road_network import (
    download_all_hanoi_bus_routes_uncut,
    parse_target_routes,
    download_road_network_overpass
)
from module_3_spatial_matching_and_trajectory_fusion import evaluate_route_telemetry
from module_4_traffic_analytics_and_visualization import generate_markdown_verification_report

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

DEFAULT_TARGET_ROUTES = []

def run_step_0(sample_batches=15):
    print("\n" + "=" * 70)
    print("🚀 BƯỚC 0: TIỀN XỬ LÝ & ĐỒNG BỘ TELEMETRY TỪ HUGGING FACE (MẪU KIỂM CHỨNG)")
    print(f"[*] Chế độ Cloud-First: Đồng bộ mẫu {sample_batches} batches về máy để kiểm chứng.")
    print("=" * 70)
    sync_result = sync_bus_telemetry_from_hf(max_batches=sample_batches)
    summary = preprocess_telemetry_dataset()
    return summary

def run_step_1(routes=None):
    print("\n" + "=" * 70)
    print("🚀 BƯỚC 1: TẢI DỮ LIỆU CÁC TUYẾN XE BUÝT TỪ OSM (UNCUT GEOJSON) & PARSER")
    print("=" * 70)
    dl_meta = download_all_hanoi_bus_routes_uncut()
    target_routes = routes or DEFAULT_TARGET_ROUTES
    parsed = parse_target_routes(
        raw_json_path="data/osm/raw/hanoi_bus_routes_raw.json",
        target_route_refs=target_routes,
        output_dir="data/osm/parsed_routes"
    )
    return dl_meta, parsed

def run_step_2():
    print("\n" + "=" * 70)
    print("🚀 BƯỚC 2: TÁI TẠO BẢN ĐỒ MẠNG LƯỚI ĐƯỜNG BỘ HÀ NỘI")
    print("=" * 70)
    net_meta = download_road_network_overpass()
    return net_meta

def run_step_3(routes=None):
    print("\n" + "=" * 70)
    print("🚀 BƯỚC 3: KIỂM CHỨNG ÁNH XẠ VUÔNG GÓC (ORTHOGONAL PROJECTION)")
    print("=" * 70)
    target_routes = routes or DEFAULT_TARGET_ROUTES
    
    cluster_cfg_path = "data/metadata/hust_cluster_config.json"
    ref_to_id = {}
    if os.path.exists(cluster_cfg_path):
        with open(cluster_cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        for r in cfg.get("routes", []):
            ref_to_id[str(r.get("route_no")).upper()] = r.get("route_id")

    verification_results = []
    for ref in target_routes:
        ref_clean = ref.upper()
        meta_path = f"data/osm/parsed_routes/route_{ref_clean}_metadata.json"
        if not os.path.exists(meta_path):
            alt_ref = ref_clean.lstrip("0") if ref_clean.startswith("0") else ("0" + ref_clean)
            meta_path = f"data/osm/parsed_routes/route_{alt_ref}_metadata.json"
            if os.path.exists(meta_path):
                ref_clean = alt_ref

        if not os.path.exists(meta_path):
            print(f"[!] Bỏ qua Tuyến {ref}: Chưa có metadata OSM tại {meta_path}")
            continue

        route_id = ref_to_id.get(ref_clean, None)
        if route_id is None:
            try:
                route_id = int(ref_clean)
            except ValueError:
                pass

        pings_data = load_preprocessed_route_pings(route_id) if route_id is not None else None
        if not pings_data:
            print(f"[!] Không tìm thấy dữ liệu telemetry cho Tuyến {ref} (route_id={route_id})")
            continue

        pings = pings_data.get("pings", [])
        print(f"[*] Đang chiếu vuông góc {len(pings)} pings của Tuyến {ref_clean}...")
        res = evaluate_route_telemetry(
            route_ref=ref_clean,
            route_metadata_path=meta_path,
            telemetry_pings=pings,
            output_dir="data/verification"
        )
        verification_results.append(res)

    return verification_results

def run_step_4(telemetry_summary, osm_dl_meta, road_net_meta, verification_results):
    print("\n" + "=" * 70)
    print("🚀 BƯỚC 4: LẬP BÁO CÁO NGHIỆM THU KIỂM CHỨNG CHO NGƯỜI DÙNG CHỐT")
    print("=" * 70)
    report_file = generate_markdown_verification_report(
        telemetry_summary=telemetry_summary,
        osm_download_meta=osm_dl_meta.get("metadata", {}),
        road_network_meta=road_net_meta.get("metadata", {}),
        verification_results=verification_results,
        output_report_path="docs/reports/27_GROUND_TRUTH_VERIFICATION_REPORT.md"
    )
    print(f"\n🎉 HOÀN TẤT BÁO CÁO TẠI: {report_file}")
    return report_file

def main():
    parser = argparse.ArgumentParser(description="Bus Tracking Ground-Truth Verification Pipeline")
    parser.add_argument("--step", type=int, choices=[0, 1, 2, 3, 4], help="Run a specific step (0, 1, 2, 3, 4)")
    parser.add_argument("--all", action="store_true", help="Run all steps 0 -> 4 end-to-end")
    parser.add_argument("--routes", type=str, default="", help="Comma-separated route refs (e.g. 31,32,26)")
    parser.add_argument("--sample-batches", type=int, default=15, help="Number of telemetry batches to sync (default: 15)")
    args = parser.parse_args()

    selected_routes = [r.strip() for r in args.routes.split(",") if r.strip()] if args.routes else DEFAULT_TARGET_ROUTES
    if not selected_routes and args.step in [1, 3, None]:
        print("[!] CHÚ Ý: Chưa có tuyến trọng tâm nào được chỉ định.")
        print("    Vui lòng truyền tham số --routes (ví dụ: --routes 08A,32,26) sau khi thảo luận thống nhất.")
        return

    if args.all or args.step is None:
        print("🎯 BẮT ĐẦU CHẠY TOÀN BỘ QUY TRÌNH 5 BƯỚC (BƯỚC 0 -> BƯỚC 4)")
        t_summary = run_step_0(sample_batches=args.sample_batches)
        dl_meta, parsed_routes = run_step_1(selected_routes)
        net_meta = run_step_2()
        v_results = run_step_3(selected_routes)
        report_path = run_step_4(t_summary, dl_meta, net_meta, v_results)
    elif args.step == 0:
        run_step_0(sample_batches=args.sample_batches)
    elif args.step == 1:
        run_step_1(selected_routes)
    elif args.step == 2:
        run_step_2()
    elif args.step == 3:
        run_step_3(selected_routes)
    elif args.step == 4:
        summary_path = "data/telemetry_sync/processed/telemetry_summary.json"
        t_summary = json.load(open(summary_path, encoding="utf-8")) if os.path.exists(summary_path) else {}
        dl_meta = {"metadata": {}}
        net_meta = {"metadata": {}}
        v_results = []
        for ref in selected_routes:
            vf = f"data/verification/verification_route_{ref}.json"
            if os.path.exists(vf):
                v_results.append(json.load(open(vf, encoding="utf-8")))
        run_step_4(t_summary, dl_meta, net_meta, v_results)

if __name__ == "__main__":
    main()
