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
    MAX_DAILY_TOMTOM_BATCHES, MAX_TOMTOM_FLOW_DAILY,
    SESSION_DURATION_SEC, BUS_MICRO_BATCH_SIZE, BUS_MICRO_BATCH_DELAY_SEC,
    BUS_POLL_INTERVAL_SEC, WATCHDOG_MIN_RESPONSE_RATE,
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

    single_test = "--test" in sys.argv

    # 🌙 Ban đêm (22:00 - 05:00): Không gọi API BusMap/TomTom để bảo vệ hạn ngạch.
    # Ngủ đủ nhịp 9 phút để duy trì chuỗi tiếp sức 24/7 đơn luồng không bao giờ ngắt.
    if not is_operating_hours(hn_time) and "--force" not in sys.argv:
        print(f"[{ts_str}] 🌙 Đêm (22:00 - 05:00): Ngoài giờ xe buýt hoạt động. Không gửi request API.", flush=True)
        if single_test:
            print("[INFO] Chế độ --test: Thoát ngay.", flush=True)
            return
        print(f"[{ts_str}] ⏳ Nghỉ ngơi duy trì nhịp tiếp sức 24/7 ({SESSION_DURATION_SEC}s)...", flush=True)
        time.sleep(SESSION_DURATION_SEC)
        return

    if not os.path.exists(CONFIG_FILE):
        print(f"[ERROR] Không tìm thấy file cấu hình: {CONFIG_FILE}!", flush=True)
        return

    config = load_cluster_config(CONFIG_FILE)
    single_test = "--test" in sys.argv
    today_str = hn_time.strftime("%Y-%m-%d")
    last_refresh = config.get("last_catalog_refresh", "")

    # 🌅 Tự động làm mới danh bạ đầu ngày: Kích hoạt ở phiên đầu tiên trong ngày (05:00 AM+)
    if is_operating_hours(hn_time) and not last_refresh.startswith(today_str) and not single_test:
        print(f"[{ts_str}] 🌅 Phiên đầu ngày ({today_str}): Tự động rà soát & làm mới danh mục 220 xe buýt...", flush=True)
        try:
            from scripts.daily_catalog_refresh import run_daily_catalog_refresh
            run_daily_catalog_refresh()
            config = load_cluster_config(CONFIG_FILE)
            print(f"[{ts_str}] ✅ Hoàn tất làm mới danh mục! Cập nhật: {len(config.get('vehicles', []))} xe.", flush=True)
        except Exception as e:
            print(f"[{ts_str}] ⚠️ Lỗi khi làm mới danh mục đầu ngày: {e}. Dùng cấu hình hiện có.", flush=True)

    v_ids = [v["id"] for v in config.get("vehicles", []) if "id" in v]
    target_route_ids = set(config.get("target_route_ids", []))
    tomtom_key = get_tomtom_api_key()
    hf_token = get_hf_token()

    print(f"[INFO] Khởi động phiên cào {len(v_ids)} xe buýt ({len(target_route_ids)} tuyến hành lang)...", flush=True)

    session_start = time.time()
    no_tomtom = "--no-tomtom" in sys.argv
    round_no = 1

    all_session_bus_records = []
    traffic_records = []
    incident_records = []
    kinematic_cache = {}

    # 1. Kiểm tra ngân sách TomTom hôm nay từ Cloud Dataset
    date_tag = hn_time.strftime("%Y-%m-%d")
    today_traffic_batches = get_hf_today_traffic_batch_count(date_tag, hf_token) if (hf_token and not single_test) else 0
    can_poll_tomtom = (today_traffic_batches < MAX_DAILY_TOMTOM_BATCHES) and not TOMTOM_CIRCUIT_OPEN and not no_tomtom

    if today_traffic_batches >= MAX_DAILY_TOMTOM_BATCHES and not single_test:
        print(f"[{ts_str}] 🚦 [BUDGET GOVERNOR] Đã dùng {today_traffic_batches}/{MAX_DAILY_TOMTOM_BATCHES} đợt TomTom hôm nay (~{today_traffic_batches*len(HUST_BOTTLENECK_NODES)}/{MAX_TOMTOM_FLOW_DAILY} flow). Tạm dừng TomTom.", flush=True)

    # 2. Lập lịch TomTom (Hỗ trợ phân tách Ngày thường vs Cuối tuần)
    total_mins = hn_time.hour * 60 + hn_time.minute
    step_9m = total_mins // (SESSION_DURATION_SEC // 60)
    is_peak = is_peak_hours(hn_time)
    baseline_tomtom = single_test or (is_peak and step_9m % 2 == 0) or (not is_peak and step_9m % 6 == 0)

    tomtom_polled_in_session = False

    # Thu thập TomTom ở đầu phiên nếu trúng lịch baseline
    if tomtom_key and can_poll_tomtom and baseline_tomtom:
        peak_label = "Cao điểm" if is_peak else "Thấp điểm"
        weekend_label = " (Cuối tuần)" if hn_time.weekday() >= 5 else ""
        print(f"[{hn_time.strftime('%H:%M:%S')}] 🚦 Thu thập TomTom ({len(HUST_BOTTLENECK_NODES)} Flow + 1 Incident BBox, {peak_label}{weekend_label})...", flush=True)
        traffic_records, incident_records = execute_tomtom_poll(hn_time, tomtom_key)
        tomtom_polled_in_session = True
        print(f"   🚦 Hoàn tất: {len(traffic_records)} flow segments, {len(incident_records)} incidents.", flush=True)

    # 3. Vòng lặp cào GPS xe buýt với Micro-batch Pacing
    micro_batches = [v_ids[i:i + BUS_MICRO_BATCH_SIZE] for i in range(0, len(v_ids), BUS_MICRO_BATCH_SIZE)]

    while (time.time() - session_start) < SESSION_DURATION_SEC:
        round_start = time.time()
        cur_hn_time = get_hanoi_time()
        round_ts = cur_hn_time.strftime("%H:%M:%S")

        round_bus_records = []
        active_count = 0
        depot_count = 0
        stale_count = 0

        for batch in micro_batches:
            with ThreadPoolExecutor(max_workers=BUS_MICRO_BATCH_SIZE) as executor:
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
                            st = clean_rec["quality_status"]
                            if st == "ACTIVE_VALID":
                                active_count += 1
                            elif st == "IDLE_DEPOT":
                                depot_count += 1
                            elif st == "STALE_PING":
                                stale_count += 1

            if not single_test:
                time.sleep(BUS_MICRO_BATCH_DELAY_SEC)

        all_session_bus_records.extend(round_bus_records)
        round_elapsed = time.time() - round_start
        print(f"[{round_ts}] [Vòng {round_no:02d}] 🚌 {len(round_bus_records)}/{len(v_ids)} xe buýt "
              f"({active_count} lăn bánh mới, {stale_count} chờ nhịp GPS, {depot_count} đỗ bãi) | {round_elapsed:.1f}s", flush=True)

        # Watchdog: Cảnh báo nếu tỷ lệ phản hồi < ngưỡng an toàn
        total_vids = len(v_ids)
        resp_rate = (len(round_bus_records) / total_vids) if total_vids > 0 else 0
        if resp_rate < WATCHDOG_MIN_RESPONSE_RATE:
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

        if single_test or (SESSION_DURATION_SEC - (time.time() - session_start)) < BUS_POLL_INTERVAL_SEC:
            break

        sleep_wait = max(3, BUS_POLL_INTERVAL_SEC - round_elapsed)
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
