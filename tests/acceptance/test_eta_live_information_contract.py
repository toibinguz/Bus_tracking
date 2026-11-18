"""Behavioral acceptance, including currently missing live preceding-bus probes.

Controlled, explicitly synthetic GPS/Parquet inputs with hand-computable results.
Real DataAccess, IncidentsProvider and OnlineFeatureExtractor are used unchanged;
neither the feature producer nor the expected output is mocked. A red test here
is a missing requirement, not something to mark xfail to obtain a green suite.
"""
from datetime import datetime,timezone
import sqlite3

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.data_access import DataAccess,IncidentsProvider
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.dto import BusVehicleDTO
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.online_features import OnlineFeatureExtractor


@pytest.fixture
def environment(tmp_path):
    db=tmp_path/'catalog.db'
    with sqlite3.connect(db) as conn:
        conn.execute('CREATE TABLE canonical_route_master(route_id,route_code,route_name)')
        conn.execute("INSERT INTO canonical_route_master VALUES (2,'02','Controlled fixture')")
        conn.execute('CREATE TABLE canonical_shape_master(route_id,route_code,direction,point_order,lat,lon,cum_distance_m)')
        conn.executemany("INSERT INTO canonical_shape_master VALUES (2,'02','go',?,?,?,?)",[(0,21.,105.,0.),(1,21.004,105.,444.8)])
        conn.execute('CREATE TABLE canonical_station_master(route_id,route_code,direction,station_order,station_id,station_name,address,lat,lon,cum_distance_m)')
        conn.executemany("INSERT INTO canonical_station_master VALUES (2,'02','go',?,?,?,?,?,?,?)",[(i,i+10,str(i),'',21.+s/111200,105.,s) for i,s in enumerate([0.,100.,200.,300.,400.])])
        conn.execute('CREATE TABLE agg_segment_travel_times(route_code,direction,from_station_order,to_station_order,day_type,hour_slot,quality_tier,tt_p10_sec,tt_p50_sec,tt_p90_sec,tt_mean_sec,tt_std_sec,segment_length_m)')
        conn.executemany("INSERT INTO agg_segment_travel_times VALUES ('02','go',?,?,?,?,0,15,20,25,20,2,100)",[(a,a+1,day,hour) for a in [1,2] for day in range(3) for hour in range(5,22)])
    root=tmp_path/'lakehouse';root.mkdir()
    return DataAccess(str(db),timbus_db_path=str(tmp_path/'no-timbus.db')),root


def vehicle(extractor,vid,epoch,s):
    shape=extractor._get_shape_model(2,'go')
    return BusVehicleDTO(id=vid,plate=f'controlled-{vid}',route_id=2,direction=0,
                         lat=21.+s/shape.ky,lng=105.,deg=0,speed_kmh=36.,raw_speed_kmh=36.,
                         updated_at=datetime.fromtimestamp(epoch,timezone.utc).isoformat())


def test_completed_preceding_bus_traversal_changes_probe_features(environment):
    access,root=environment
    ex=OnlineFeatureExtractor(access,IncidentsProvider(str(root)))
    # Independent bracket arithmetic: cross s=100 at t=1001 and s=200 at
    # t=1011. Completed segment took 10s, compared with a 20s baseline.
    for t,s in [(1000,90),(1002,110),(1010,190),(1012,210)]:
        ex.update_observation(2,0,[vehicle(ex,1,t,s)],t)
    ego=vehicle(ex,2,1013,150)
    ex.update_observation(2,0,[vehicle(ex,1,1013,220),ego],1013)
    f=ex.build_features(2,0,ego,2,200.,150.,1013)
    assert f['baseline_eta_p50_sec']==pytest.approx(10.)
    actual={k:f[k] for k in ['recent_seg_coverage_ratio','recent_next_seg_congestion_ratio',
                             'recent_corridor_congestion_ratio','recent_corridor_tt_sum_sec']}
    assert actual==pytest.approx(dict(recent_seg_coverage_ratio=1.,recent_next_seg_congestion_ratio=.5,
                                     recent_corridor_congestion_ratio=.5,recent_corridor_tt_sum_sec=5.)),actual


def test_active_incident_parquet_reaches_features_and_expires(environment):
    access,root=environment
    part=root/'silver/fact_route_tomtom_incidents/route_code=02';part.mkdir(parents=True)
    pq.write_table(pa.table(dict(direction=['go'],t_start_epoch=[1000.],t_end_epoch=[1100.],
                                 s_min_m=[150.],s_max_m=[200.],delay_seconds=[60.],
                                 magnitude_of_delay=[3.],overlap_length_m=[50.])),part/'incident.parquet')
    ex=OnlineFeatureExtractor(access,IncidentsProvider(str(root)))
    ego=vehicle(ex,2,1050,150)
    active=ex.build_features(2,0,ego,2,200.,150.,1050)
    assert active['inc_ahead_count']==1
    assert active['inc_ahead_total_delay_sec']==pytest.approx(60.)
    assert active['inc_ahead_max_magnitude']==3
    assert active['inc_ahead_jam_length_m']==50
    assert active['inc_dist_to_nearest_m']==0
    expired=ex.build_features(2,0,ego,2,200.,150.,1101)
    assert expired['inc_ahead_count']==0
    assert expired['inc_ahead_total_delay_sec']==0
