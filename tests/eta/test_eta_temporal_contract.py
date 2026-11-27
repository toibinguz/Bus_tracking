import hashlib
import json
import sqlite3
from datetime import datetime, timedelta

import pandas as pd
import pytest

from modules.eta.temporal_contract import split_at_dates, require_validation_provenance


def test_trip_windows_cannot_share_label_brackets_across_splits():
    pings=[('2026-10-23',1,10),('2026-10-24',2,20),('2026-10-31',3,30),('2026-11-01',4,40)]
    groups=split_at_dates(pings,['2026-10-23','2026-10-31'])
    assert groups==[pings[:1],pings[1:3],pings[3:]]
    assert [p for group in groups for p in group]==pings


def test_new_training_rejects_missing_overlapping_or_corrupt_feature_provenance(tmp_path):
    with pytest.raises(ValueError,match='lacks provenance'):require_validation_provenance(tmp_path)
    part=tmp_path/'part.parquet';part.write_bytes(b'input')
    manifest=dict(baseline_fit_end_date='2026-10-24',files={'part.parquet':hashlib.sha256(part.read_bytes()).hexdigest()})
    path=tmp_path/'feature_store_manifest.json';path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='overlaps validation'):require_validation_provenance(tmp_path)
    manifest['baseline_fit_end_date']='2026-10-23';path.write_text(json.dumps(manifest))
    assert require_validation_provenance(tmp_path)==manifest
    part.write_bytes(b'changed')
    with pytest.raises(ValueError,match='hash mismatch'):require_validation_provenance(tmp_path)


@pytest.mark.parametrize('fit_end,expected_fit',[('2026-10-31',1),('2026-10-23',0),('2026-10-26',0)])
def test_validation_day_cannot_fit_earlier_baseline_even_with_utc_timestamp(tmp_path,monkeypatch,fit_end,expected_fit):
    from modules.eta.baseline import baseline_matrix_builder as baseline
    database=tmp_path/'baseline.db'
    with sqlite3.connect(database) as conn:
        conn.execute('CREATE TABLE canonical_shape_master(route_code TEXT,direction TEXT,cum_distance_m REAL)')
        conn.execute("INSERT INTO canonical_shape_master VALUES ('02','go',600)")
        conn.execute('CREATE TABLE canonical_station_master(route_code TEXT,direction TEXT,station_order INTEGER,station_id INTEGER,station_name TEXT,cum_distance_m REAL)')
        conn.executemany("INSERT INTO canonical_station_master VALUES ('02','go',?,?,?,?)",[(i,i+1,str(i),i*200) for i in range(4)])
    partition=tmp_path/'silver/route_code=02/dt=2026-10-27';partition.mkdir(parents=True)
    # All samples are 27 Oct in Hanoi, although ISO strings start with 26 Oct.
    start=datetime.fromisoformat('2026-10-26T20:00:00+00:00')
    pd.DataFrame([dict(vehicle_id=1,device_update_time=(start+timedelta(seconds=i*30)).isoformat(),
                       device_epoch=start.timestamp()+i*30,direction='go',s_bus_m=i*150.,derived_speed_kmh=18.) for i in range(5)]).to_parquet(partition/'part.parquet',index=False)
    monkeypatch.setattr(baseline,'DB_PATH',str(database));monkeypatch.setattr(baseline,'SILVER_TEL_DIR',str(tmp_path/'silver'))
    monkeypatch.setattr(baseline,'GOLD_BASELINE_DIR',str(tmp_path/'gold'))
    result=baseline.build_and_evaluate_baseline_matrix(fit_end_date=fit_end)
    assert result['fit_trips']==expected_fit
    with sqlite3.connect(database) as conn:
        observed=conn.execute('SELECT SUM(sample_count) FROM agg_segment_travel_times').fetchone()[0]
        assert (observed>0)==bool(expected_fit)
        assert conn.execute('SELECT fit_end_date FROM eta_baseline_manifest').fetchone()[0]==fit_end
