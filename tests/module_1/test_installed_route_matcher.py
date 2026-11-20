"""Installed matcher lifecycle/causality, complemented by recorded-live HTTP replay."""
from datetime import datetime,timezone
import pytest

from module_1_data_ingestion_and_preprocessing.step_1_4_frenet_spatial_projection.route_matcher import RouteHMM,ShapeProjectionModel
from module_1_data_ingestion_and_preprocessing.step_1_4_frenet_spatial_projection.multi_route_projector import project_points_to_shape
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.projection_tracker import RouteProjectionTracker
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.dto import BusVehicleDTO


POINTS=[(0,0,0,0),(1,0,.02,2226.4)]


class Geometry:
    def get_shape_points(self,route,direction):
        return POINTS if direction=='go' else [(0,0,.02,0),(1,0,0,2226.4)]


def vehicle(epoch,s,direction=0):
    shape=ShapeProjectionModel.build(POINTS)
    return BusVehicleDTO(id=1,plate='fixture',route_id=2,direction=direction,lat=0,lng=s/shape.kx,
                         speed_kmh=20,updated_at=datetime.fromtimestamp(epoch,timezone.utc).isoformat())


def test_offline_and_serving_share_exact_causal_projection():
    pings=[(i,0,lon,100+i*5) for i,lon in enumerate([.001,.0015,.002,.0025])]
    expected=project_points_to_shape(pings,POINTS)
    ex=RouteProjectionTracker(Geometry());actual=[]
    for i,lat,lon,epoch in pings:
        v=BusVehicleDTO(id=1,plate='fixture',route_id=2,direction=0,lat=lat,lng=lon,speed_kmh=20,updated_at=datetime.fromtimestamp(epoch,timezone.utc).isoformat())
        out=ex.project_vehicle(2,0,v,epoch)
        actual.append((i,out.matched_projection[0],out.matched_projection[1]))
    assert actual==expected
    assert project_points_to_shape(pings[:2],POINTS)==expected[:2]


def test_near_terminal_reversal_clears_history_and_accepts_new_direction():
    ex=RouteProjectionTracker(Geometry())
    assert ex.project_vehicle(2,0,vehicle(1000,2100),1000).matched_projection
    first=ex.project_vehicle(2,0,vehicle(1010,2000),1010)
    assert first.projection_status=='no_feasible_transition'
    # Re-fetching the same coordinate is not a second independent reversal observation.
    same=ex.project_vehicle(2,0,vehicle(1015,2000),1015)
    assert same.projection_generation==0
    reversed_=ex.project_vehicle(2,0,vehicle(1020,1980),1020)
    assert reversed_.projection_status=='direction_change_pending'
    assert reversed_.projection_generation==1
    fresh=ex.project_vehicle(2,1,vehicle(1030,1950,1),1030)
    assert fresh.matched_projection is not None and fresh.projection_generation==2
    assert ex._matchers[(2,1,1)].best_path[0].epoch==1030
    stale=ex.project_vehicle(2,0,vehicle(1025,1970),1030)
    assert stale.projection_status=='old_direction'
    assert ex._generations[(2,1)]==2


def test_midroute_backward_outlier_does_not_reset_trip():
    ex=RouteProjectionTracker(Geometry());ex.project_vehicle(2,0,vehicle(1000,1100),1000)
    a=ex.project_vehicle(2,0,vehicle(1010,1000),1010)
    b=ex.project_vehicle(2,0,vehicle(1020,980),1020)
    assert a.matched_projection is None and b.matched_projection is None
    assert b.projection_generation==0
    recovered=ex.project_vehicle(2,0,vehicle(1030,1150),1030)
    assert recovered.matched_projection is not None


def test_projection_metadata_is_not_added_to_public_vehicle_payload():
    ex=RouteProjectionTracker(Geometry());v=ex.project_vehicle(2,0,vehicle(1000,100),1000)
    assert v.projection_checked
    assert not any(k.startswith('projection_') or k=='matched_projection' for k in v.model_dump())
