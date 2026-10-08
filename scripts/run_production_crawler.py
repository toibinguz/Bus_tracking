"""
Production Multi-Tier Crawler for HUST Corridor Cluster (Termux Android & Local Laptop)
Author: Antigravity Big Data Architecture Team
Modular architecture importing from core package.
"""

import os
import sys
import json
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import (
    CONFIG_FILE, BUS_OUTPUT_DIR, TRAFFIC_OUTPUT_DIR, INCIDENT_OUTPUT_DIR,
    MAX_TOMTOM_FLOW_DAILY, MAX_TOMTOM_FLOW_MONTHLY,
    MAX_TOMTOM_INCIDENT_DAILY, MAX_TOMTOM_INCIDENT_MONTHLY,
    BUS_POLL_INTERVAL_SEC, HF_SYNC_INTERVAL_SEC,
    BUS_MICRO_BATCH_SIZE, BUS_MICRO_BATCH_DELAY_SEC,
    TOMTOM_PEAK_INTERVAL_SEC, TOMTOM_OFFPEAK_INTERVAL_SEC,
    TOMTOM_FLOW_THROTTLE_SEC, WATCHDOG_MIN_RESPONSE_RATE,
    HUST_BOTTLENECK_NODES,
    is_operating_hours, is_peak_hours,
    get_tomtom_api_key, get_hf_token
)
from core.bus_client import (
    fetch_single_bus_raw, sanitize_and_validate_telemetry, load_cluster_config
)
from core.traffic_client import (
    fetch_tomtom_flow, fetch_tomtom_incidents,
    load_tomtom_quota_state, save_tomtom_quota_state,
    render_tomtom_cli_bar, TOMTOM_CIRCUIT_OPEN
)
from core.congestion import evaluate_hotspot_congestion
from core.hf_client import upload_batches_to_hf_native

def main():
    run_24x7 = "--24x7" in sys.argv or "--always" in sys.argv
    single_test = "--test" in sys.argv

    os.makedirs(BUS_OUTPUT_DIR, exist_ok=True)
    os.makedirs(TRAFFIC_OUTPUT_DIR, exist_ok=True)
    os.makedirs(INCIDENT_OUTPUT_DIR, exist_ok=True)
    os.makedirs("data/metadata", exist_ok=True)

    if not os.path.exists(CONFIG_FILE):
        print(f"[ERROR] Chưa tìm thấy file cấu hình: {CONFIG_FILE}", flush=True)
        return

    config = load_cluster_config(CONFIG_FILE)
    target_vehicles = config.get("vehicles", [])
    target_route_ids = set(config.get("target_route_ids", []))
    v_ids = [v["id"] for v in target_vehicles if "id" in v]
    tomtom_key = get_tomtom_api_key()
    hf_token = get_hf_token()

    quota_state = load_tomtom_quota_state()
    current_day = datetime.now().day
    current_month = datetime.now().month
    last_tomtom_poll = 0
    last_hf_sync = time.time()
    kinematic_cache = {}
    round_no = 1
    is_congested = False
    recent_incidents = []

    print("=" * 75, flush=True)
    print("🚀 HỆ THỐNG CRAWLER 24/7 - MẠNG LƯỚI HÀNH LANG BÁCH KHOA (MODULAR CORE)", flush=True)
    print(f"📍 Quy mô theo dõi: {len(target_route_ids)} tuyến hành lang ({len(v_ids)} xe buýt probe)", flush=True)
    print(f"🌊 Cơ chế Pacing: Trải đều micro-batches (~4 req/s liên tục, phẳng tải CPU)", flush=True)
    print(f"🚦 Điểm nghẽn TomTom: {len(HUST_BOTTLENECK_NODES)} nút giao + 1 Incident BBox hành lang", flush=True)
    print(f"📊 Hạn mức TomTom: Flow {MAX_TOMTOM_FLOW_DAILY}/ngày (tháng 20k) | Incident {MAX_TOMTOM_INCIDENT_DAILY}/ngày (tháng 2.5k)", flush=True)
    print(f"⏰ Khung giờ hoạt động: {'24/7 (Bắt buộc)' if run_24x7 else '05:00 - 22:00 (Tự động ngủ ban đêm)'}", flush=True)
    print(f"🔑 TomTom API Key: {'Đã nạp' if tomtom_key else 'Thiếu key'}", flush=True)
    print(f"☁️ Cloud Sync (Hugging Face): {'Đã kích hoạt (Mỗi 10 phút)' if hf_token else 'Tắt (Lưu 100% trong máy)'}", flush=True)
    print("=" * 75, flush=True)

    while True:
        try:
            now = datetime.now()
            # Reset counter on new day or month
            if now.month != current_month:
                quota_state["flow_month"] = 0
                quota_state["incident_month"] = 0
                quota_state["flow_today"] = 0
                quota_state["incident_today"] = 0
                current_month = now.month
                current_day = now.day
                save_tomtom_quota_state(quota_state)
            elif now.day != current_day:
                quota_state["flow_today"] = 0
                quota_state["incident_today"] = 0
                current_day = now.day
                save_tomtom_quota_state(quota_state)

            # Check operating hours
            if not is_operating_hours(now, run_24x7):
                print(f"[{now.strftime('%H:%M:%S')}] 🌙 Ngoài khung giờ xe buýt (22:00 - 05:00). Hệ thống nghỉ ngơi...", flush=True)
                time.sleep(300)
                continue

            round_start = time.time()
            date_str = now.strftime("%Y-%m-%d")
            hour_str = now.strftime("%H")
            bus_out_file = os.path.join(BUS_OUTPUT_DIR, f"bus_telemetry_{date_str}_{hour_str}.jsonl")
            traffic_out_file = os.path.join(TRAFFIC_OUTPUT_DIR, f"tomtom_flow_{date_str}.jsonl")
            incident_out_file = os.path.join(INCIDENT_OUTPUT_DIR, f"tomtom_incidents_{date_str}.jsonl")

            # 1. CRAWL BUSES VỚI PACING
            bus_records = []
            active_count = 0
            depot_count = 0
            stale_count = 0

            micro_batches = [v_ids[i:i + BUS_MICRO_BATCH_SIZE] for i in range(0, len(v_ids), BUS_MICRO_BATCH_SIZE)]
            micro_delay = 0.05 if single_test else BUS_MICRO_BATCH_DELAY_SEC

            for batch in micro_batches:
                with ThreadPoolExecutor(max_workers=BUS_MICRO_BATCH_SIZE) as executor:
                    futures = {executor.submit(fetch_single_bus_raw, vid): vid for vid in batch}
                    for fut in futures:
                        vid = futures[fut]
                        raw_res = fut.result()
                        if raw_res:
                            clean_rec = sanitize_and_validate_telemetry(
                                raw_res, vid, target_route_ids, kinematic_cache, now.isoformat()
                            )
                            if clean_rec:
                                bus_records.append(clean_rec)
                                status = clean_rec["quality_status"]
                                if status == "ACTIVE_VALID": active_count += 1
                                elif status == "IDLE_DEPOT": depot_count += 1
                                elif status == "STALE_PING": stale_count += 1
                time.sleep(micro_delay)

            if bus_records:
                with open(bus_out_file, "a", encoding="utf-8") as f:
                    for rec in bus_records:
                        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

            total_vids = len(v_ids)
            resp_rate = (len(bus_records) / total_vids) if total_vids > 0 else 0
            if resp_rate < WATCHDOG_MIN_RESPONSE_RATE:
                print(f"   ⚠️ [WATCHDOG] Cảnh báo: Tỷ lệ xe phản hồi thấp ({len(bus_records)}/{total_vids} = {resp_rate*100:.1f}%).", flush=True)

            # 2. ĐÁNH GIÁ ÙN TẮC & ĐIỀU CHỈNH CHU KỲ TOMTOM ĐỘNG
            congestion_eval = evaluate_hotspot_congestion(bus_records, HUST_BOTTLENECK_NODES, recent_incidents=recent_incidents)
            prev_congested = is_congested
            is_congested = congestion_eval["is_congested"]

            is_peak = is_peak_hours(now)
            tomtom_interval = TOMTOM_PEAK_INTERVAL_SEC if (is_peak or is_congested) else TOMTOM_OFFPEAK_INTERVAL_SEC
            next_tomtom_in = max(0, tomtom_interval - (time.time() - last_tomtom_poll))

            if is_congested and not prev_congested:
                print(f"   🚨 [DYN-CONGESTION] Phát hiện ùn tắc tại {len(congestion_eval['congested_nodes'])} nút: {congestion_eval['congested_nodes']}. Rút ngắn chu kỳ TomTom xuống {TOMTOM_PEAK_INTERVAL_SEC//60} phút!", flush=True)

            # 3. CRAWL TOMTOM
            if tomtom_key and not TOMTOM_CIRCUIT_OPEN and (time.time() - last_tomtom_poll >= tomtom_interval or (single_test and round_no == 1)):
                can_flow = (quota_state["flow_today"] + len(HUST_BOTTLENECK_NODES) <= MAX_TOMTOM_FLOW_DAILY) and (quota_state["flow_month"] + len(HUST_BOTTLENECK_NODES) <= MAX_TOMTOM_FLOW_MONTHLY)
                can_incident = (quota_state["incident_today"] + 1 <= MAX_TOMTOM_INCIDENT_DAILY) and (quota_state["incident_month"] + 1 <= MAX_TOMTOM_INCIDENT_MONTHLY)

                traffic_records = []
                incident_records = []

                if can_flow:
                    for node in HUST_BOTTLENECK_NODES:
                        flow_res = fetch_tomtom_flow(node["lat"], node["lon"], tomtom_key)
                        quota_state["flow_today"] += 1
                        quota_state["flow_month"] += 1
                        if flow_res:
                            raw_coords = flow_res.get("coordinates", {}).get("coordinate", [])
                            seg_coords = [[round(c["longitude"], 6), round(c["latitude"], 6)] for c in raw_coords if "longitude" in c and "latitude" in c]
                            traffic_records.append({
                                "timestamp": now.isoformat(),
                                "node_name": node["name"],
                                "lat": node["lat"],
                                "lon": node["lon"],
                                "current_speed": flow_res.get("currentSpeed"),
                                "free_flow_speed": flow_res.get("freeFlowSpeed"),
                                "travel_time": flow_res.get("currentTravelTime"),
                                "confidence": flow_res.get("confidence"),
                                "road_closure": flow_res.get("roadClosure", False),
                                "coordinates": seg_coords
                            })
                        time.sleep(TOMTOM_FLOW_THROTTLE_SEC)

                    if traffic_records:
                        with open(traffic_out_file, "a", encoding="utf-8") as f:
                            for tr in traffic_records:
                                f.write(json.dumps(tr, ensure_ascii=False) + "\n")

                if can_incident:
                    raw_incidents = fetch_tomtom_incidents(tomtom_key)
                    quota_state["incident_today"] += 1
                    quota_state["incident_month"] += 1
                    for inc in raw_incidents:
                        props = inc.get("properties", {})
                        geom = inc.get("geometry", {})
                        events = props.get("events", [])
                        desc = events[0].get("description", "") if events else ""
                        incident_records.append({
                            "timestamp": now.isoformat(),
                            "incident_id": props.get("id", ""),
                            "icon_category": props.get("iconCategory", 0),
                            "magnitude_of_delay": props.get("magnitudeOfDelay", 0),
                            "delay_seconds": props.get("delay", 0),
                            "length_meters": round(props.get("length", 0), 2),
                            "description": desc,
                            "geometry_type": geom.get("type", "LineString"),
                            "coordinates": geom.get("coordinates", [])
                        })
                    if incident_records:
                        recent_incidents = incident_records
                        with open(incident_out_file, "a", encoding="utf-8") as f:
                            for ir in incident_records:
                                f.write(json.dumps(ir, ensure_ascii=False) + "\n")

                last_tomtom_poll = time.time()
                save_tomtom_quota_state(quota_state)
                next_tomtom_in = tomtom_interval

            # 4. DASHBOARD CLI
            elapsed = time.time() - round_start
            tt_dashboard = render_tomtom_cli_bar(quota_state, next_tomtom_in, is_congested, TOMTOM_CIRCUIT_OPEN)
            
            print(f"[{now.strftime('%H:%M:%S')}] [Vòng {round_no:03d}] "
                  f"🚌 Xe buýt: {len(bus_records)}/{len(v_ids)} phản hồi "
                  f"({active_count} lăn bánh mới, {stale_count} chờ nhịp GPS, {depot_count} đỗ bãi) | "
                  f"{elapsed:.1f}s", flush=True)
            print(f"   {tt_dashboard}", flush=True)
            round_no += 1

            # 5. ĐỒNG BỘ ĐỊNH KỲ LÊN CLOUD
            if hf_token and not single_test and (time.time() - last_hf_sync >= HF_SYNC_INTERVAL_SEC):
                time_tag = now.strftime("%H%M%S")
                upload_batches_to_hf_native(bus_out_file, traffic_out_file, incident_out_file, date_str, time_tag, hf_token)
                last_hf_sync = time.time()

            if single_test:
                print("\n[INFO] Test run 1 vòng 220 xe hoàn tất thành công! Dừng tiến trình.", flush=True)
                break

            sleep_wait = max(3, BUS_POLL_INTERVAL_SEC - elapsed)
            time.sleep(sleep_wait)

        except KeyboardInterrupt:
            print("\n[INFO] Người dùng bấm Ctrl+C. Đang dừng Crawler an toàn...", flush=True)
            save_tomtom_quota_state(quota_state)
            break
        except Exception as err:
            print(f"⚠️ [CẢNH BÁO] Có lỗi tạm thời trong vòng lặp ({err}). Tự động tiếp tục sau 5s...", flush=True)
            time.sleep(5)

if __name__ == "__main__":
    main()
