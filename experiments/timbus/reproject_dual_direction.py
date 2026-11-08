import sys
import os
sys.path.insert(0, os.path.abspath("."))
import json
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.online_feature_extractor import OnlineFeatureExtractor

with open('data/metadata/timbus_busmap_parity_results.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

extractor = OnlineFeatureExtractor()
records = data.get('matched_records', [])

print("RE-PROJECTING EVERY VEHICLE ONTO BOTH 'go' AND 're' DIRECTIONS:")
print("=" * 110)
print(f"{'Plate':<10} {'Route':<5} {'ScriptDir':<10} | {'d_go(m)':<8} {'s_go(m)':<9} | {'d_re(m)':<8} {'s_re(m)':<9} | {'BestDir':<8} {'True_d_perp':<11} {'Status'}")
print("=" * 110)

route_recalc = {"02": {"pass": 0, "fail": 0, "total": 0}, "32": {"pass": 0, "fail": 0, "total": 0}}

for r in records:
    p = r.get('plate')
    r_code = r.get('route_code')
    script_dir = r.get('direction')
    tb_lat, tb_lon = r.get('coord_timbus')
    bm_lat, bm_lon = r.get('coord_busmap')
    
    # Project TimBus on 'go'
    s_go_t, d_go_t, in_corridor_go = extractor.project_coordinate(r_code, 'go', tb_lat, tb_lon)
    # Project TimBus on 're'
    s_re_t, d_re_t, in_corridor_re = extractor.project_coordinate(r_code, 're', tb_lat, tb_lon)
    
    best_dir = 'go' if d_go_t <= d_re_t else 're'
    best_d = min(d_go_t, d_re_t)
    best_pass = (best_d <= 35.0)
    
    route_recalc[r_code]["total"] += 1
    if best_pass:
        route_recalc[r_code]["pass"] += 1
    else:
        route_recalc[r_code]["fail"] += 1
        
    status = "OK" if best_pass else "OUT_OF_CORRIDOR"
    dir_mismatch = " [DIR FLIPPED!]" if best_dir != script_dir else ""
    
    print(f"{p:<10} {r_code:<5} {script_dir:<10} | {d_go_t:<8.1f} {s_go_t:<9.1f} | {d_re_t:<8.1f} {s_re_t:<9.1f} | {best_dir:<8} {best_d:<11.1f} {status}{dir_mismatch}")

print("=" * 110)
print("RE-CALCULATED CORRIDOR PASS RATES WITH CORRECT DIRECTION MATCHING:")
for r_code, res in route_recalc.items():
    pct = (res['pass'] / max(1, res['total'])) * 100
    print(f"Route {r_code}: {res['pass']}/{res['total']} passed ({pct:.1f}%), {res['fail']} failed")
