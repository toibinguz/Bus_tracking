from datetime import datetime,timezone
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from experiment_eta_streaming import motion_projection,ExperimentalExtractor
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.frenet import ShapeProjectionModel
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.dto import BusVehicleDTO


def hairpin():
    return ShapeProjectionModel.build([(0,0,0,0),(1,0,.01,1113.2),
                                       (2,.0002,.01,1135.4),(3,.0002,0,2248.6)])


def test_motion_disambiguates_nearby_opposite_branches():
    shape=hairpin();previous=(100,.00012,.004,(445.3,13.3,0))
    assert shape.project_point(.00012,.0042)[2]==2
    assert motion_projection(shape,.00012,.0042,previous,105)[2]==0


def test_small_displacement_keeps_plausible_branch_without_clamping_position():
    shape=hairpin();previous=(100,.00012,.004,(445.3,13.3,0))
    projected=motion_projection(shape,.00012,.00401,previous,105)
    assert projected[2]==0
    assert projected[0]>previous[3][0]


def test_real_return_leg_is_allowed_and_long_gap_reacquires():
    shape=hairpin();previous=(100,.0002,.008,shape.project_point(.0002,.008))
    assert motion_projection(shape,.0002,.0078,previous,105)[2]==2
    # A large gap does not silently impose old branch state on new observations.
    old=(100,.00012,.004,(445.3,13.3,0))
    assert motion_projection(shape,.00012,.0042,old,140)==shape.project_point(.00012,.0042)


def test_late_or_duplicate_event_cannot_replace_branch_state():
    shape=hairpin();old=(100,.00012,.004,(445.3,13.3,0))
    assert motion_projection(shape,0,.009,old,99)==old[3]
    assert motion_projection(shape,0,.009,old,100)==old[3]


def test_speed_carry_expires_and_does_not_reuse_it_indefinitely():
    class Access:
        def get_shape_points(self,*args):return [(0,0,0,0),(1,0,.02,2226.4)]
        def get_corridor_stations(self,*args):return [(0,0,'start',0),(1,1,'end',2226.4)]
        def get_route_profile(self,*args):return (20,2226.4,2226.4)
    ex=ExperimentalExtractor(Access(),carry=True)
    ex._segment_array=lambda *args,**kwargs:[400.]
    shape=ex._get_shape_model(27,'re')
    def observe(t,s,speed):
        v=BusVehicleDTO(id=1,plate='fixture',route_id=27,direction=1,lat=0,lng=s/shape.kx,
                        deg=90,speed_kmh=speed,raw_speed_kmh=speed,
                        updated_at=datetime.fromtimestamp(t,timezone.utc).isoformat())
        ex.update_observation(27,1,[v],t)
        return ex._fleet[(27,1)][1][2]
    observe(1000,500,20);mature=observe(1100,1000,20)
    assert observe(1105,880,17)==mature
    assert observe(1109.7,892.4,3)==mature
    observe(1140,1000,20)
    assert (27,1,1) not in ex.held


def test_lost_unique_packet_is_not_recovered_from_duplicate_delivery():
    class Access:
        def get_shape_points(self,*args):return [(0,0,0,0),(1,0,.02,2226.4)]
        def get_corridor_stations(self,*args):return [(0,0,'start',0),(1,1,'end',2226.4)]
        def get_route_profile(self,*args):return (20,2226.4,2226.4)
    ex=ExperimentalExtractor(Access(),drop_unique=True)
    ex._segment_array=lambda *args,**kwargs:[400.]
    def observe(t):
        v=BusVehicleDTO(id=1,plate='fixture',route_id=27,direction=1,lat=0,lng=.005,
                        deg=90,speed_kmh=10,updated_at=datetime.fromtimestamp(t,timezone.utc).isoformat())
        ex.update_observation(27,1,[v],t)
    for t in range(1000,1005):observe(t)
    held=ex.delivered[(27,1,1)].updated_at
    assert held==datetime.fromtimestamp(1003,timezone.utc).isoformat()
    observe(1004)
    assert ex.stats['unique_packets']==5
    assert ex.stats['dropped_unique_packets']==1
    assert ex.delivered[(27,1,1)].updated_at==held
