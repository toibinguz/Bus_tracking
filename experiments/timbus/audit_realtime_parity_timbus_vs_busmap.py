#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================================================================
THỰC NGHIỆM ĐỐI SOÁT VIỄN TRẮC THỜI GIAN THỰC: TIMBUS (5s) vs. BUSMAP (30-75s)
VÀ THẨM ĐỊNH MÔ HÌNH CẦU NỐI KHÔNG GIAN FRENET (FRENET BRIDGE ARCHITECTURE)
========================================================================================
Mã thực nghiệm: Experiment 1.2 (TD-33 & TD-36)
Tuyến khảo sát: Tuyến 02 (Bác Cổ - BX Yên Nghĩa) và Tuyến 32 (BX Giáp Bát - Nhổn)
"""

import sys
import os
import time
import math
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Tuple, Optional

# Thêm đường dẫn gốc dự án
sys.path.insert(0, os.path.abspath("."))

from experiments.timbus.timbus_tracker import TimBusClient, BusRecord
from module_1_data_ingestion_and_preprocessing.step_1_1_busmap_crawler_and_relay.catalog_refresher import fetch_route_buses_live
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.online_feature_extractor import OnlineFeatureExtractor

TZ_HANOI = timezone(timedelta(hours=7))

def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Tính khoảng cách Haversine giữa 2 tọa độ WGS84 theo mét."""
    R = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2.0)**2
    return 2.0 * R * math.asin(math.sqrt(max(0.0, min(1.0, a))))

def parse_iso_epoch(ts_str: str) -> float:
    """Chuyển chuỗi ISO-8601 sang timestamp epoch."""
    if not ts_str:
        return time.time()
    try:
        # Xử lý các định dạng ISO phổ biến
        if ts_str.endswith("Z"):
            ts_str = ts_str[:-1] + "+00:00"
        dt = datetime.fromisoformat(ts_str)
        return dt.timestamp()
    except Exception:
        return time.time()

def run_parity_audit(routes: List[Tuple[int, str, int, int]] = [(2, "02", 1750, 1667), (32, "32", 1778, 1676)]):
    """
    Thực hiện đối soát toàn diện giữa BusMap và TimBus.
    routes: List of (busmap_route_id, route_code, terminal_go_id, terminal_re_id)
    Chuẩn hóa hướng di chuyển: go theo go (dir=0), re theo re (dir=1).
    """
    print("=" * 110)
    print("THỰC NGHIỆM ĐỐI SOÁT VIỄN TRẮC THỜI GIAN THỰC: TIMBUS (5s) vs. BUSMAP (30-75s)")
    print("CHUẨN HÓA HÌNH HỌC: GO THEO GO, RE THEO RE - ĐỐI SOÁT STATION-ID CHÍNH TẮC")
    print("=" * 110)
    
    # 1. Khởi tạo OnlineFeatureExtractor (chứa Master Ground Truth & Frenet Projector)
    print("[*] Đang khởi tạo OnlineFeatureExtractor và nạp Master Ground Truth vào RAM...")
    t0_ofe = time.time()
    extractor = OnlineFeatureExtractor()
    print(f"[+] OnlineFeatureExtractor sẵn sàng ({int((time.time() - t0_ofe)*1000)}ms).")
    
    now_epoch = time.time()
    now_str = datetime.now(TZ_HANOI).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[*] Thời điểm bắt đầu đo đạc thực địa: {now_str}")
    
    all_matched_records = []
    all_unmatched_records = []
    route_stats = {}
    
    for bm_rid, r_code, term_go, term_re in routes:
        print(f"\n" + "-" * 110)
        print(f"[*] KHẢO SÁT TUYẾN {r_code} (BusMap ID: {bm_rid})...")
        print("-" * 110)
        
        total_bm_count = 0
        matched_count = 0
        dist_diffs = []
        lags_sec = []
        frenet_pass_count = 0
        
        # Duyệt độc lập từng chiều: go theo go (dir=0), re theo re (dir=1)
        for dir_int, dir_str, term_st in [(0, "go", term_go), (1, "re", term_re)]:
            bm_buses = fetch_route_buses_live(bm_rid, dir_int) or []
            total_bm_count += len(bm_buses)
            print(f"[+] Chiều '{dir_str}' (dir={dir_int}, Terminal {term_st}): BusMap API trả về {len(bm_buses)} xe")
            
            for bm_b in bm_buses:
                vid = str(bm_b.get("Id", ""))
                plate_raw = str(bm_b.get("VehicleNumber", vid))
                clean_plate = plate_raw.replace("-", "").replace(".", "").strip().upper()
                bm_lat = float(bm_b.get("Lat", 0.0))
                bm_lng = float(bm_b.get("Lng", 0.0))
                bm_spd = float(bm_b.get("Speed", 0.0))
                bm_ts = bm_b.get("lastUpdateTime", "")
                bm_epoch = parse_iso_epoch(bm_ts)
                lag_sec = max(0.0, now_epoch - bm_epoch)
                
                # Query TimBus CHUẨN HÓA: go theo go (0), re theo re (1)
                tb_b = TimBusClient.query_targeted_vehicle(term_st, r_code, clean_plate, direction=dir_int)
                if not tb_b:
                    print(f"  [-] Xe [{clean_plate}] ({dir_str}): TimBus không trả về kết quả.")
                    all_unmatched_records.append({
                        "route_code": r_code,
                        "direction": dir_str,
                        "plate": clean_plate,
                        "busmap_vid": vid,
                        "busmap_speed": bm_spd,
                        "busmap_ts": bm_ts,
                        "busmap_coord": [bm_lat, bm_lng],
                        "busmap_lag_sec": round(lag_sec, 1)
                    })
                    continue
                
                matched_count += 1
                tb_lat = tb_b.latitude
                tb_lng = tb_b.longitude
                tb_spd = tb_b.speed_kmh
                
                # 1. Tính khoảng cách Haversine giữa 2 tọa độ WGS-84
                delta_dist_m = haversine_m(bm_lat, bm_lng, tb_lat, tb_lng)
                dist_diffs.append(delta_dist_m)
                lags_sec.append(lag_sec)
                
                # 2. Chiếu CHUẨN HÓA lên đúng chiều dir_str của xe (go theo go, re theo re)
                s_t, d_perp_t, is_corridor_t = extractor.project_coordinate(r_code, dir_str, tb_lat, tb_lng)
                s_b, d_perp_b, is_corridor_b = extractor.project_coordinate(r_code, dir_str, bm_lat, bm_lng)
                
                if is_corridor_t:
                    frenet_pass_count += 1
                    
                # Xác định vị trí trạm dừng theo chuẩn BusMap Canonical thông qua s_bus_m của TimBus
                key_rd = (r_code, dir_str)
                st_s_vals = extractor.st_s_vals.get(key_rd, [])
                st_list = extractor.stations_by_dir.get(key_rd, [])
                
                if len(st_s_vals) > 0:
                    import numpy as np
                    k_curr = int(np.searchsorted(st_s_vals, s_t, side="right")) - 1
                    k_curr = min(len(st_s_vals) - 1, max(0, k_curr))
                    curr_st = st_list[k_curr] if k_curr < len(st_list) else None
                    next_st = st_list[k_curr + 1] if (k_curr + 1) < len(st_list) else None
                else:
                    k_curr = -1
                    curr_st, next_st = None, None
                    
                canonical_next_name = next_st[2] if next_st else "N/A"
                canonical_next_id = next_st[1] if next_st else -1
                
                record = {
                    "route_code": r_code,
                    "plate": clean_plate,
                    "busmap_vid": vid,
                    "busmap_lag_sec": round(lag_sec, 1),
                    "delta_dist_m": round(delta_dist_m, 1),
                    "speed_busmap": bm_spd,
                    "speed_timbus": tb_spd,
                    "coord_busmap": [bm_lat, bm_lng],
                    "coord_timbus": [tb_lat, tb_lng],
                    "direction": dir_str,
                    "timbus_frenet_s_m": round(s_t, 1),
                    "timbus_frenet_d_perp_m": round(d_perp_t, 1),
                    "timbus_in_corridor_35m": is_corridor_t,
                    "busmap_frenet_s_m": round(s_b, 1),
                    "progress_lead_s_m": round(s_t - s_b, 1),
                    "timbus_raw_next_id": tb_b.next_station_id,
                    "timbus_raw_next_name": tb_b.next_station_name,
                    "timbus_raw_dist_m": tb_b.distance_m,
                    "canonical_next_station_order": k_curr + 1 if next_st else -1,
                    "canonical_next_station_id": canonical_next_id,
                    "canonical_next_station_name": canonical_next_name,
                }
                all_matched_records.append(record)
                
                print(f"  [+] Xe {clean_plate:<10} ({dir_str}) | Δd = {delta_dist_m:>5.1f}m | Lag BusMap = {lag_sec:>4.1f}s | V_bm={bm_spd} vs V_tb={tb_spd}")
                print(f"      • TimBus Tọa độ: ({tb_lat:.6f}, {tb_lng:.6f}) -> Frenet: s={s_t:.1f}m, d_perp={d_perp_t:.1f}m (Corridor: {is_corridor_t})")
                print(f"      • Trạm BusMap Cầu nối: [#{k_curr+1}] [{canonical_next_id}] '{canonical_next_name}'")
                
        # Phân tích Lead s cho tuyến
        r_matched = [r for r in all_matched_records if r["route_code"] == r_code]
        leads = [r["progress_lead_s_m"] for r in r_matched]
        pos_leads = [x for x in leads if x > 0]
        neg_leads = [x for x in leads if x < 0]
        
        route_stats[r_code] = {
            "total_busmap_active": total_bm_count,
            "total_timbus_matched": matched_count,
            "match_rate_pct": round((matched_count / max(1, total_bm_count)) * 100, 1),
            "mean_delta_dist_m": round(sum(dist_diffs) / max(1, len(dist_diffs)), 1),
            "median_delta_dist_m": round(sorted(dist_diffs)[len(dist_diffs)//2], 1) if dist_diffs else 0.0,
            "max_delta_dist_m": round(max(dist_diffs), 1) if dist_diffs else 0.0,
            "mean_busmap_lag_sec": round(sum(lags_sec) / max(1, len(lags_sec)), 1),
            "frenet_corridor_pass_rate_pct": round((frenet_pass_count / max(1, matched_count)) * 100, 1),
            "lead_s_positive_count": len(pos_leads),
            "lead_s_negative_count": len(neg_leads),
            "mean_lead_s_m": round(sum(leads) / max(1, len(leads)), 1) if leads else 0.0,
            "median_lead_s_m": round(sorted(leads)[len(leads)//2], 1) if leads else 0.0
        }
        
    print("\n" + "=" * 110)
    print("TỔNG HỢP KẾT QUẢ THỰC NGHIỆM ĐỐI SOÁT ĐA NGUỒN (PARITY AUDIT SUMMARY)")
    print("=" * 110)
    for r_code, st in route_stats.items():
        print(f"[*] Tuyến {r_code}:")
        print(f"    - Bắt cặp thành công             : {st['total_timbus_matched']} / {st['total_busmap_active']} xe ({st['match_rate_pct']}%)")
        print(f"    - Độ lệch không gian trung bình  : {st['mean_delta_dist_m']} m (Trung vị: {st['median_delta_dist_m']} m, Max: {st['max_delta_dist_m']} m)")
        print(f"    - Độ trễ đồng hồ BusMap          : {st['mean_busmap_lag_sec']} giây")
        print(f"    - Tỷ lệ khớp hành lang Frenet 35m: {st['frenet_corridor_pass_rate_pct']}%")
        print(f"    - Lead s (TimBus > BusMap)       : {st['lead_s_positive_count']} xe (+) vs {st['lead_s_negative_count']} xe (-) | Trung vị: {st['median_lead_s_m']}m")
    print("=" * 110)
    
    # Lưu kết quả ra file JSON phục vụ báo cáo
    os.makedirs("data/metadata", exist_ok=True)
    out_file = "data/metadata/timbus_busmap_parity_results.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": now_str,
            "route_stats": route_stats,
            "matched_records": all_matched_records,
            "unmatched_records": all_unmatched_records
        }, f, ensure_ascii=False, indent=2)
    print(f"\n[+] Đã lưu toàn bộ kết quả thực nghiệm định lượng vào: {out_file}")
    
    return all_matched_records, route_stats

if __name__ == '__main__':
    run_parity_audit()
