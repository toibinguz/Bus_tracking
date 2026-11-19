import sqlite3
from pathlib import Path
import sys

import pandas as pd
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from verify_canonical_architecture import verify


def test_silver_readiness_allows_existing_gold_and_rejects_missing_schema(tmp_path):
    db=tmp_path/'db.sqlite';lake=tmp_path/'lake'
    with sqlite3.connect(db) as conn:
        conn.execute('CREATE TABLE canonical_route_master(route_id,route_code)')
        conn.execute("INSERT INTO canonical_route_master VALUES (2,'02')")
        conn.execute('CREATE TABLE canonical_station_master(route_id,route_code,direction,station_order,station_id,cum_distance_m)')
        conn.execute("INSERT INTO canonical_station_master VALUES (2,'02','go',1,5,100.)")
        conn.execute('CREATE TABLE canonical_shape_master(route_id,route_code,direction,point_order,lat,lon,cum_distance_m)')
        conn.execute("INSERT INTO canonical_shape_master VALUES (2,'02','go',0,21.,105.,0.)")
        conn.execute('CREATE TABLE agg_segment_travel_times(anything)')
    path=lake/'silver/route_projected_telemetry/route_code=02/dt=2026-10-22';path.mkdir(parents=True)
    pd.DataFrame([dict(vehicle_id=1,device_update_time='2026-10-22T08:00:00+07:00',device_epoch=1.,direction='go',s_bus_m=100.,derived_speed_kmh=None)]).to_parquet(path/'part.parquet')
    assert verify(db,lake,'silver')['silver']['rows']==1
    with pytest.raises(ValueError,match='missing table/columns'):verify(db,lake,'gold')
