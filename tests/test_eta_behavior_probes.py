import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from probe_eta_behavior import transition, recommendation_check


def packet(vehicle,epoch,eta,distance):
    return dict(query_epoch=epoch,result=dict(vehicle_id=vehicle,eta_seconds=eta),
                features=dict(remaining_distance_m=distance))


def test_remaining_eta_decreases_but_arrival_can_move_later():
    result=transition(packet(1,0,100,500),packet(1,60,80,500))
    assert result['eta_change_sec']==-20
    assert result['arrival_revision_sec']==40
    assert result['distance_advance_m']==0


def test_next_bus_must_not_be_reported_as_same_bus_eta_jump():
    with pytest.raises(ValueError,match='different vehicles'):
        transition(packet(1,0,5,20),packet(2,5,600,2000))


def test_recommendation_inside_bracket_is_not_proven_late():
    result=recommendation_check(100,10,108,112)
    assert result['later_than_earliest_gps_crossing']
    assert not result['later_than_latest_gps_crossing']
    assert result['lateness_beyond_right_sec']==0


def test_recommendation_after_entire_bracket_is_flagged():
    result=recommendation_check(100,15,108,112)
    assert result['later_than_latest_gps_crossing']
    assert result['lateness_beyond_right_sec']==3


def test_window_speed_units_and_minimum_history():
    from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.online_features import _window_speed
    assert _window_speed([(0,0,0),(10,100,0)],100,240,10)==(36.,10)
    speed,dt=_window_speed([(0,0,17),(4.7,12.4,3)],12.4,240,10)
    assert speed is None
    assert dt==4.7


def test_legacy_global_reference_reproduces_recorded_reset_failure():
    from global_projection_reference import GlobalProjectionReference as OnlineFeatureExtractor
    from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.dto import BusVehicleDTO
    class Access:
        def get_shape_points(self,*args):return [(0,0,0,0),(1,0,.02,2226.4)]
        def get_corridor_stations(self,*args):return [(0,0,'start',0),(1,1,'end',2226.4)]
        def get_route_profile(self,*args):return (20,2226.4,2226.4)
    ex=OnlineFeatureExtractor(Access())
    ex._segment_array=lambda *args,**kwargs:[400.]
    shape=ex._get_shape_model(27,'re')
    def observe(t,s,raw):
        v=BusVehicleDTO(id=1,plate='fixture',route_id=27,direction=1,lat=0,lng=s/shape.kx,
                        deg=90,speed_kmh=raw,raw_speed_kmh=raw,
                        updated_at=datetime.fromtimestamp(t,timezone.utc).isoformat())
        ex.update_observation(27,1,[v],t)
        return ex._fleet[(27,1)][1][2]
    observe(1000,500,20);observe(1100,1000,20)
    assert len(ex._obs[(27,1,1)])==2
    assert observe(1105,880,17)==17
    assert len(ex._obs[(27,1,1)])==1
    assert observe(1109.7,892.4,3)==3
