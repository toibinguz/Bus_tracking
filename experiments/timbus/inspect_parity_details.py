import json
import math

with open('data/metadata/timbus_busmap_parity_results.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

print("=" * 100)
print(f"AUDIT RUN TIMESTAMP: {data.get('timestamp')}")
print("=" * 100)

for r_code, stats in data.get('route_stats', {}).items():
    print(f"\n--- ROUTE {r_code} OVERALL STATS ---")
    for k, v in stats.items():
        print(f"  {k}: {v}")

records = data.get('matched_records', [])
print(f"\nTOTAL MATCHED VEHICLES ACROSS ALL ROUTES: {len(records)}")

for r_code in ["02", "32"]:
    r_recs = [r for r in records if r.get('route_code') == r_code]
    print(f"\n{'='*40} ROUTE {r_code} ({len(r_recs)} VEHICLES) {'='*40}")
    
    corridor_pass_count = sum(1 for r in r_recs if r.get('timbus_in_corridor_35m'))
    corridor_fail_count = len(r_recs) - corridor_pass_count
    
    lead_s_pos = [r for r in r_recs if r.get('progress_lead_s_m', 0) > 0]
    lead_s_neg = [r for r in r_recs if r.get('progress_lead_s_m', 0) < 0]
    lead_s_zero = [r for r in r_recs if r.get('progress_lead_s_m', 0) == 0]
    
    print(f"Corridor pass (<=35m): {corridor_pass_count}/{len(r_recs)} ({corridor_pass_count/len(r_recs)*100:.1f}%) | Fail (>35m): {corridor_fail_count}/{len(r_recs)} ({corridor_fail_count/len(r_recs)*100:.1f}%)")
    print(f"Lead s > 0 (TB ahead of BM): {len(lead_s_pos)} | Lead s < 0 (TB behind BM): {len(lead_s_neg)} | Lead s == 0: {len(lead_s_zero)}")
    
    print("-" * 100)
    print(f"{'Plate':<10} {'Dir':<4} {'BM_Lag':<7} {'dDist':<8} {'V_BM':<5} {'V_TB':<5} {'s_TB':<8} {'d_TB':<7} {'Pass':<6} {'s_BM':<8} {'Lead_s':<9} {'TB_NextName':<25} {'Canon_NextName'}")
    print("-" * 100)
    for r in r_recs:
        p = r.get('plate')
        d = r.get('direction')
        lag = r.get('busmap_lag_sec')
        dd = r.get('delta_dist_m')
        v_bm = r.get('speed_busmap')
        v_tb = r.get('speed_timbus')
        s_tb = r.get('timbus_frenet_s_m')
        d_tb = r.get('timbus_frenet_d_perp_m')
        pass_tb = "PASS" if r.get('timbus_in_corridor_35m') else "FAIL"
        s_bm = r.get('busmap_frenet_s_m')
        lead = r.get('progress_lead_s_m')
        tb_name = r.get('timbus_raw_next_name', '')
        c_name = r.get('canonical_next_station_name', '')
        print(f"{p:<10} {d:<4} {lag:<7.1f} {dd:<8.1f} {v_bm:<5} {v_tb:<5} {s_tb:<8.1f} {d_tb:<7.1f} {pass_tb:<6} {s_bm:<8.1f} {lead:<9.1f} {tb_name[:24]:<25} {c_name}")
