import sys, os, time, math, re
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.abspath('.'))

from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.eta_serving_service import EtaServingService
from experiments.timbus.timbus_tracker import TimBusClient

def test_prototype():
    svc = EtaServingService.get_instance()
    r_code = "02"
    d_str = "go"
    dir_int = 0
    
    t0 = time.time()
    raw_snapshot = svc.predict_route_snapshot_live(r_code, d_str)
    print(f"BusMap snapshot: {len(raw_snapshot['buses'])} buses in {(time.time()-t0)*1000:.1f}ms")
    
    # Terminal station ID
    st_list = svc.extractor.stations_by_dir.get((r_code, d_str), [])
    term_sid = st_list[-1][1] if st_list else 1750
    alt_sid = st_list[0][1] if st_list else 1667
    
    def probe_bus(b):
        p = b.get("plate", "")
        cp = re.sub(r'[^A-Za-z0-9]', '', p).upper()
        if not cp:
            return b["vehicle_id"], None
        try:
            tb = TimBusClient.query_targeted_vehicle(term_sid, r_code, cp, direction=dir_int, timeout=2)
            if not tb and alt_sid:
                tb = TimBusClient.query_targeted_vehicle(alt_sid, r_code, cp, direction=dir_int, timeout=2)
            return b["vehicle_id"], tb
        except Exception:
            return b["vehicle_id"], None
            
    t1 = time.time()
    with ThreadPoolExecutor(max_workers=8) as ex:
        probe_map = dict(ex.map(probe_bus, raw_snapshot["buses"]))
    print(f"Parallel probe: {len(probe_map)} vehicles in {(time.time()-t1)*1000:.1f}ms")
    
    matched = 0
    for b in raw_snapshot["buses"]:
        vid = b["vehicle_id"]
        tb = probe_map.get(vid)
        if tb:
            s_bus, d_perp, is_on = svc.extractor.project_coordinate(r_code, d_str, tb.latitude, tb.longitude)
            if is_on:
                matched += 1
                lead = s_bus - b.get("current_s_bus_m", s_bus)
                print(f"  MATCH: {b.get('plate')} -> TB: ({tb.latitude:.5f}, {tb.longitude:.5f}, v={tb.speed_kmh}km/h), d_perp={d_perp:.1f}m, delta_s={lead:.1f}m")
            else:
                print(f"  OFF-CORRIDOR: {b.get('plate')} -> d_perp={d_perp:.1f}m > 35m")
        else:
            print(f"  UNMATCHED/DEPOT: {b.get('plate')} -> fallback to BusMap")
            
    print(f"\nSummary: {matched}/{len(raw_snapshot['buses'])} matched with TimBus 5s.")

if __name__ == "__main__":
    test_prototype()
