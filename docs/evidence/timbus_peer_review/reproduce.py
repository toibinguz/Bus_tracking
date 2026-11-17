"""Read-only reproductions for the TimBus peer review; no DB/network required."""
import json
import sys
import threading
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(next(p for p in __import__('pathlib').Path(__file__).resolve().parents if (p / 'AGENTS.md').is_file())))
from experiments.timbus.timbus_tracker import TimBusClient
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.dto import BusVehicleDTO, RouteLiveResponse
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.serving_service import BusMapServingService
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.online_features import OnlineFeatureExtractor

now = 1000.0
def vehicle(vid, s):
    return BusVehicleDTO(id=vid, plate=f'29A0000{vid}', route_id=1, direction=0,
                         lat=s / 1000, lng=0, deg=0, speed_kmh=20,
                         updated_at=datetime.fromtimestamp(now - 10, timezone.utc).isoformat())

class Shape:
    def project_point(self, lat, lng): return lat * 1000, 0, 0
    def segment_unit_tangent(self, idx): return 0, 1

svc = BusMapServingService.__new__(BusMapServingService)
svc._tb_lock = threading.Lock()
svc._passed_station_plates = {(1, 0, 2, '29A00001'): now - 2}
v = vehicle(1, 90)
svc._tb_last_valid = {(1, 0, v.plate): (now - 1, 90, v)}
svc._apply_macro_speeds = lambda *args: args[4]
kw = dict(route_id=1, dir_int=0, dir_str='go', anchor_sids=[1],
          target_plates=[v.plate], bm_proj={v.plate: (v, 90, 0)}, raw_vehicles=[v],
          shape_model=Shape(), now_epoch=now, s_target=100, station_order=2)
record = SimpleNamespace(latitude=.09, longitude=0, speed_kmh=20, fetch_timestamp=now)
with patch.object(TimBusClient, 'query_central_vehicles', return_value={v.plate: record}):
    fresh = svc._sync_and_merge_timbus(**kw, use_live_cache=False)
    cached = svc._sync_and_merge_timbus(**kw, use_live_cache=True)
cache_result = dict(fresh_query_bus_count=len(fresh), cached_query_bus_count=len(cached),
                    passed_marker_retained=(1, 0, 2, v.plate) in svc._passed_station_plates)

# Real station synchronization hands the filtered list to the fleet extractor.
vehicles = [vehicle(1, 90), vehicle(2, 110)]
svc._passed_station_plates = {}
svc._tb_last_valid = { (1, 0, bus.plate): (now, bus.lat * 1000, bus) for bus in vehicles }
svc._da = SimpleNamespace(get_timbus_anchors=lambda *a: (True, [1]))
svc._get_shape_model = lambda *a: Shape()
extractor = OnlineFeatureExtractor.__new__(OnlineFeatureExtractor)
extractor._obs_lock = threading.Lock()
extractor._obs = {}
extractor._fleet = {}
extractor._da = SimpleNamespace(get_corridor_stations=lambda *a: [(0, 0, 0, 0), (1, 0, 0, 200)],
                                get_route_profile=lambda *a: (20, 200, 200))
extractor._get_shape_model = lambda *a: Shape()
extractor._segment_array = lambda *a, **k: [36]
svc._extractor = extractor
response = RouteLiveResponse(route_id=1, direction=0, timestamp=datetime.fromtimestamp(now, timezone.utc).isoformat(), count=2, vehicles=vehicles)
svc._sync_single_direction(1, 0, now, pre_live_resp=response)
before = len(extractor._fleet[(1, 0)])
_, station_buses = svc._sync_single_direction(1, 0, now, station_order=2, s_target=100, pre_live_resp=response)
fleet_result = dict(active_before_station_query=before, active_after_station_query=len(extractor._fleet[(1, 0)]),
                    approaching_bus_count=len(station_buses))

times = [0, 75, 150, 225, 300, 375, 450]
positions = [0, 100, 200, 300, 400, 500, 1500]
extractor._obs[(1, 0, 1)] = list(zip(times, positions, [20]*7))
online = extractor._speed_features(1, 0, 1, positions[-1], 48)
train3 = (positions[-1] - positions[-4]) / (times[-1] - times[-4]) * 3.6
train5 = (positions[-1] - positions[-6]) / (times[-1] - times[-6]) * 3.6
print(json.dumps(dict(cache=cache_result, fleet=fleet_result,
                     windows=dict(train_roll3=train3, serving_roll3=online[1],
                                  train_roll5=train5, serving_roll5=online[2])), indent=2))
