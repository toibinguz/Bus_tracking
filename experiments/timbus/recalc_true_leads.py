import sys
import os
sys.path.insert(0, os.path.abspath("."))
import json
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.online_feature_extractor import OnlineFeatureExtractor

with open('data/metadata/timbus_busmap_parity_results.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

extractor = OnlineFeatureExtractor()
records = data.get('matched_records', [])

print("=" * 120)
print(f"{'Plate':<10} {'Route':<5} {'TrueDir':<8} {'BM_Lag':<7} {'dDist':<7} | {'s_TB':<8} {'d_TB':<6} | {'s_BM':<8} {'d_BM':<6} | {'Lead_s (TB-BM)':<15} {'Status'}")
print("=" * 120)

leads_true = []
for r in records:
    p = r.get('plate')
    r_code = r.get('route_code')
    tb_lat, tb_lon = r.get('coord_timbus')
    bm_lat, bm_lon = r.get('coord_busmap')
    lag = r.get('busmap_lag_sec')
    dd = r.get('delta_dist_m')
    
    # Project TimBus on 'go' and 're'
    s_go_t, d_go_t, _ = extractor.project_coordinate(r_code, 'go', tb_lat, tb_lon)
    s_re_t, d_re_t, _ = extractor.project_coordinate(r_code, 're', tb_lat, tb_lon)
    
    # Determine true direction by minimum d_perp of TimBus & BusMap
    best_dir = 'go' if d_go_t <= d_re_t else 're'
    s_t = s_go_t if best_dir == 'go' else s_re_t
    d_t = d_go_t if best_dir == 'go' else d_re_t
    
    s_b, d_b, _ = extractor.project_coordinate(r_code, best_dir, bm_lat, bm_lon)
    lead_s = s_t - s_b
    leads_true.append((r_code, p, best_dir, lag, dd, s_t, d_t, s_b, d_b, lead_s))
    
    status = "AHEAD (+)" if lead_s > 0 else ("BEHIND (-)" if lead_s < 0 else "ZERO")
    print(f"{p:<10} {r_code:<5} {best_dir:<8} {lag:<7.1f} {dd:<7.1f} | {s_t:<8.1f} {d_t:<6.1f} | {s_b:<8.1f} {d_b:<6.1f} | {lead_s:<15.1f} {status}")

print("=" * 120)
pos = [x for x in leads_true if x[9] > 0]
neg = [x for x in leads_true if x[9] < 0]
zero = [x for x in leads_true if x[9] == 0]
print(f"SUMMARY WITH TRUE DIRECTION:")
print(f"Total: {len(leads_true)}")
print(f"Lead > 0 (TB ahead of BM): {len(pos)}/{len(leads_true)} ({len(pos)/len(leads_true)*100:.1f}%)")
print(f"Lead < 0 (TB behind BM): {len(neg)}/{len(leads_true)} ({len(neg)/len(leads_true)*100:.1f}%)")
print(f"Lead == 0: {len(zero)}/{len(leads_true)}")
print(f"Mean Lead s (TB - BM): {sum(x[9] for x in leads_true)/len(leads_true):.1f}m")
print(f"Median Lead s: {sorted([x[9] for x in leads_true])[len(leads_true)//2]:.1f}m")
