import sys, os, time, math
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.abspath('.'))
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.eta_serving_service import EtaServingService
from experiments.timbus.timbus_tracker import TimBusClient

def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi, dlam = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dphi/2.0)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2.0)**2
    return 2.0 * R * math.asin(math.sqrt(max(0.0, min(1.0, a))))

svc = EtaServingService.get_instance()
r_code = "02"
d_str = "go"
t0 = time.time()
res = svc.predict_route_snapshot_live(r_code, d_str)
print(f"Base BusMap snapshot: {len(res['buses'])} buses in {(time.time()-t0)*1000:.1f}ms")

# Terminal stations for TimBus probe
term_map = {
    ("02", "go"): (1750, 1667),
    ("02", "re"): (1667, 1750),
    ("32", "go"): (157, 510),
    ("32", "re"): (510, 157),
}
term_st, alt_term_st = term_map.get((r_code, d_str), (1750, 1667))

plates = [b.get("plate", "") for b in res["buses"]]

def probe(p):
    cp = p.replace("-", "").replace(".", "").strip().upper()
    if not cp: return p, None
    try:
        tb = TimBusClient.query_targeted_vehicle(term_st, r_code, cp, 0, timeout=2)
        if not tb and alt_term_st:
            tb = TimBusClient.query_targeted_vehicle(alt_term_st, r_code, cp, 1, timeout=2)
        return p, tb
    except Exception:
        return p, None

t_tb_start = time.time()
with ThreadPoolExecutor(max_workers=8) as ex:
    tb_results = dict(ex.map(probe, plates))
print(f"TimBus parallel probe completed in {(time.time()-t_tb_start)*1000:.1f}ms")

for b in res["buses"]:
    p = b.get("plate", "")
    tb = tb_results.get(p)
    bm_lat, bm_lon = b.get("lat"), b.get("lon")
    bm_spd = b.get("speed_kmh")
    
    source = "busmap_relay"
    lead_m = 0.0
    
    if tb:
        # Dual-direction Frenet projection
        s_go, d_go, _ = svc.extractor.project_coordinate(r_code, "go", tb.latitude, tb.longitude)
        s_re, d_re, _ = svc.extractor.project_coordinate(r_code, "re", tb.latitude, tb.longitude)
        best_dir = "go" if d_go <= d_re else "re"
        best_d = min(d_go, d_re)
        
        if best_dir == d_str and best_d <= 35.0:
            source = "timbus_frenet_5s"
            lead_m = haversine_m(bm_lat, bm_lon, tb.latitude, tb.longitude)
            print(f"  [⚡ 5s MATCH] {p:<10} | BM: ({bm_lat:.5f}, {bm_lon:.5f}, v={bm_spd}) -> TB: ({tb.latitude:.5f}, {tb.longitude:.5f}, v={tb.speed_kmh}) | d_perp={best_d:.1f}m, lead={lead_m:.1f}m")
        else:
            print(f"  [FALLBACK-CORR] {p:<10} | BestDir={best_dir} vs ReqDir={d_str}, d_perp={best_d:.1f}m")
    else:
        print(f"  [FALLBACK-UNMATCHED] {p:<10} | TimBus returned None")
