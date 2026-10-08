"""
Cloud Crawler Step for GitHub Actions (9-Minute Continuous Session)
Author: Antigravity Big Data Architecture Team
Modular architecture importing from core package.
"""

import os
import sys
import json
import time
from concurrent.futures import ThreadPoolExecutor

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import (
    CONFIG_FILE, HF_DATASET_ID,
    get_hanoi_time, is_operating_hours, is_peak_hours,
    get_tomtom_api_key, get_hf_token, HUST_BOTTLENECK_NODES
)
from core.bus_client import (
    fetch_single_bus_raw, sanitize_and_validate_telemetry, load_cluster_config
)
from core.traffic_client import (
    execute_tomtom_poll, TOMTOM_CIRCUIT_OPEN
)
from core.congestion import evaluate_hotspot_congestion
from core.hf_client import (
    get_hf_today_traffic_batch_count, upload_batches_to_hf_native
)

def main():
    hn_time = get_hanoi_time()
    ts_str = hn_time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts_str}] Khởi chạy Cloud Crawler Phiên 9 Phút trên GitHub Actions...", flush=True)

    if not is_operating_hours(hn_time) and "--force" not in sys.argv:
        print(f"[{ts_str}] Ngoài khung giờ xe buýt (22:00 - 05:00). Tạm dừng dây chuyền.", flush=True)
        with open(".stop_chain", "w") as f:
            f.write("night")
        return

    # Xóa cờ stop_chain nếu đang trong giờ hoạt động
    if os.path.exists(".stop_chain"):
        try: os.remove(".stop_chain")
        except Exception: pass

    if not os.path.exists(CONFIG_FILE):
        print(f"[ERROR] Không tìm thấy file cấu hình: {CONFIG_FILE}!", flush=True)
        return

    config = load_cluster_config(CONFIG_FILE)
    v_ids = [v["id"] for v in config.get("vehicles", []) if "id" in v]
    target_route_ids = set(config.get("target_route_ids", []))
    tomtom_key = get_tomtom_api_key()
    hf_token = get_hf_token()

    print(f"[INFO] Khởi động phiên cào {len(v_ids)} xe buýt ({len(target_route_ids)} tuyến hành lang)...", flush=True)

    SESSION_DURATION = 540  # 9 phút
    session_start = time.time()
    single_test = "--test" in sys.argv
    no_tomtom = "--no-tomtom" in sys.argv
    round_no = 1

    all_session_bus_records = []
    traffic_records = []
    incident_records = []
    kinematic_cache = {}

    # 1. Kiểm tra ngân sách TomTom hôm nay từ Cloud Dataset
    date_tag = hn_time.strftime("%Y-%m-%d")
    today_traffic_batches = get_hf_today_traffic_batch_count(date_tag, hf_token) if (hf_token and not single_test) else 0
    can_poll_tomtom = (today_traffic_batches < 31) and not TOMTOM_CIRCUIT_OPEN and not no_tomtom

    if today_traffic_batches >= 31 and not single_test:
        print(f"[{ts_str}] 🚦 [BUDGET GOVERNOR] Đã dùng {today_traffic_batches}/31 đợt TomTom hôm nay (~{today_traffic_batches*19}/600 flow). Tạm dừng TomTom.", flush=True)

    # 2. Lập lịch TomTom (Hỗ trợ phân tách Ngày thường vs Cuối tuần)
    total_mins = hn_time.hour * 60 + hn_time.minute
    step_9m = total_mins // 9
    is_peak = is_peak_hours(hn_time)
    baseline_tomtom = single_test or (is_peak and step_9m % 2 == 0) or (not is_peak and step_9m % 6 == 0)

    tomtom_polled_in_session = False

    # Thu thập TomTom ở đầu phiên nếu trúng lịch baseline
    if tomtom_key and can_poll_tomtom and baseline_tomtom:
        peak_label = "Cao điểm" if is_peak else "Thấp điểm"
        weekend_label = " (Cuối tuần)" if hn_time.weekday() >= 5 else ""
        print(f"[{hn_time.strftime('%H:%M:%S')}] 🚦 Thu thập TomTom (19 Flow + 1 Incident BBox, {peak_label}{weekend_label})...", flush=True)
        traffic_records, incident_records = execute_tomtom_poll(hn_time, tomtom_key)
        tomtom_polled_in_session = True
        print(f"   🚦 Hoàn tất: {len(traffic_records)} flow segments, {len(incident_records)} incidents.", flush=True)

    # 3. Vòng lặp cào GPS 220 xe buýt mỗi 60 giây với Micro-batch Pacing
    batch_size = 8
    micro_batches = [v_ids[i:i + batch_size] for i in range(0, len(v_ids), batch_size)]

    while (time.time() - session_start) < SESSION_DURATION:
        round_start = time.time()
        cur_hn_time = get_hanoi_time()
        round_ts = cur_hn_time.strftime("%H:%M:%S")

        round_bus_records = []
        active_count = 0
        depot_count = 0

        for batch in micro_batches:
            with ThreadPoolExecutor(max_workers=batch_size) as executor:
                futures = {executor.submit(fetch_single_bus_raw, vid): vid for vid in batch}
                for fut in futures:
                    vid = futures[fut]
                    raw_res = fut.result()
                    if raw_res:
                        clean_rec = sanitize_and_validate_telemetry(
                            raw_res, vid, target_route_ids, kinematic_cache, cur_hn_time.isoformat()
                        )
                        if clean_rec:
                            round_bus_records.append(clean_rec)
                            if clean_rec["quality_status"] == "ACTIVE_VALID":
                                active_count += 1
                            elif clean_rec["quality_status"] == "IDLE_DEPOT":
                                depot_count += 1

            if not single_test:
                time.sleep(0.35)

        all_session_bus_records.extend(round_bus_records)
        round_elapsed = time.time() - round_start
        print(f"[{round_ts}] [Vòng {round_no:02d}] 🚌 {len(round_bus_records)}/{len(v_ids)} xe buýt "
              f"({active_count} lăn bánh, {depot_count} đỗ bãi) | {round_elapsed:.1f}s", flush=True)

        # Watchdog: Cảnh báo nếu tỷ lệ phản hồi < 60%
        total_vids = len(v_ids)
        resp_rate = (len(round_bus_records) / total_vids) if total_vids > 0 else 0
        if resp_rate < 0.60:
            print(f"   ⚠️ [WATCHDOG] Cảnh báo: Tỷ lệ xe phản hồi thấp ({len(round_bus_records)}/{total_vids} = {resp_rate*100:.1f}%).", flush=True)

        # Dynamic Congestion Trigger: Đánh giá sau vòng 1 nếu chưa gọi TomTom
        if round_no == 1 and not tomtom_polled_in_session and tomtom_key and can_poll_tomtom:
            congestion_eval = evaluate_hotspot_congestion(round_bus_records, HUST_BOTTLENECK_NODES, recent_incidents=incident_records)
            if congestion_eval["is_congested"]:
                if (step_9m % 2 == 0):
                    print(f"[{round_ts}] 🚨 [DYN-CONGESTION] Phát hiện ùn tắc tại {len(congestion_eval['congested_nodes'])} nút: {congestion_eval['congested_nodes']}. Kích hoạt TomTom sớm!", flush=True)
                    dyn_flow, dyn_inc = execute_tomtom_poll(cur_hn_time, tomtom_key)
                    traffic_records.extend(dyn_flow)
                    incident_records.extend(dyn_inc)
                    tomtom_polled_in_session = True
                    print(f"   🚦 Hoàn tất quét động: {len(dyn_flow)} flow segments, {len(dyn_inc)} incidents.", flush=True)

        round_no += 1

        if single_test or (SESSION_DURATION - (time.time() - session_start)) < 60:
            break

        sleep_wait = max(3, 60 - round_elapsed)
        time.sleep(sleep_wait)

    print(f"\n[SUMMARY] Kết thúc phiên: Thu được {len(all_session_bus_records)} pings ({round_no-1} vòng), {len(traffic_records)} TomTom flow và {len(incident_records)} TomTom incidents.", flush=True)

    # 4. Ghi file batch và đẩy lên Hugging Face qua native Commit API
    tmp_dir = "temp_cloud_output"
    os.makedirs(tmp_dir, exist_ok=True)
    time_tag = hn_time.strftime("%H%M%S")

    bus_chunk = os.path.join(tmp_dir, f"bus_batch_{time_tag}.jsonl")
    with open(bus_chunk, "w", encoding="utf-8") as f:
        for r in all_session_bus_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    traffic_chunk = os.path.join(tmp_dir, f"traffic_batch_{time_tag}.jsonl")
    if traffic_records:
        with open(traffic_chunk, "w", encoding="utf-8") as f:
            for r in traffic_records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    incident_chunk = os.path.join(tmp_dir, f"incident_batch_{time_tag}.jsonl")
    if incident_records:
        with open(incident_chunk, "w", encoding="utf-8") as f:
            for r in incident_records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    if single_test:
        print("\n[INFO] Chế độ --test: Đã ghi file batch cục bộ, KHÔNG đẩy lên Hugging Face.", flush=True)
    else:
        upload_batches_to_hf_native(bus_chunk, traffic_chunk, incident_chunk, date_tag, time_tag, hf_token)

if __name__ == "__main__":
    main()
