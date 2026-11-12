from unittest.mock import patch

import pytest

from module_2_big_data_storage_and_lakehouse.step_2_4_hdfs_history.eta_snapshot import activate, download, inspect_active, publish, verify_artifact, files_manifest
from module_2_big_data_storage_and_lakehouse.step_2_4_hdfs_history.hf_bronze import digest,encoded


class Store:
    def __init__(self):
        self.objects={}
    def exists(self,path):
        return path in self.objects
    def read(self,path):
        return self.objects[path]
    def create(self,path,content):
        assert path not in self.objects
        self.objects[path]=content


def artifact(root,value=b'baseline'):
    root.mkdir(parents=True)
    (root/'baseline.db').write_bytes(value)
    info=dict(snapshot_id='a'*64,files=files_manifest(root))
    info['artifact_id']=digest(encoded(info))
    (root/'artifact.json').write_bytes(encoded(info))
    return info


def test_publish_retry_download_activate_offline(tmp_path):
    root=tmp_path/'build'
    info=artifact(root)
    store=Store()
    publish(root,store)
    previous=len(store.objects)
    publish(root,store)
    assert len(store.objects)==previous
    release=download(info['artifact_id'],tmp_path/'releases',store)
    with patch('subprocess.run',side_effect=AssertionError('offline used Docker')):
        activate(release,tmp_path/'active.json')
        assert inspect_active(tmp_path/'active.json')['artifact_id']==info['artifact_id']


def test_failed_refresh_keeps_active_release(tmp_path):
    old=tmp_path/'old'
    first=artifact(old)
    pointer=tmp_path/'active.json'
    activate(old,pointer)
    before=pointer.read_bytes()
    new=tmp_path/'new'
    second=artifact(new,b'new')
    store=Store()
    publish(new,store)
    key=next(key for key in store.objects if key.endswith('/baseline.db'))
    store.objects[key]=b'corrupt'
    with pytest.raises(ValueError,match='hash mismatch'):
        download(second['artifact_id'],tmp_path/'releases',store)
    assert pointer.read_bytes()==before
    assert inspect_active(pointer)['artifact_id']==first['artifact_id']


def test_corrupt_or_mixed_release_not_activated(tmp_path):
    root=tmp_path/'build'
    artifact(root)
    (root/'unexpected.parquet').write_bytes(b'other snapshot')
    with pytest.raises(ValueError,match='unlisted'):
        activate(root,tmp_path/'active.json')
    assert not (tmp_path/'active.json').exists()
    (root/'unexpected.parquet').unlink()
    (root/'baseline.db').write_bytes(b'corrupt')
    with pytest.raises(ValueError,match='corrupted'):
        verify_artifact(root)


def test_valid_but_wrong_existing_release_is_not_reused(tmp_path):
    first=tmp_path/'first'
    info=artifact(first)
    store=Store()
    publish(first,store)
    releases=tmp_path/'releases'
    artifact(releases/info['artifact_id'],b'different valid artifact')
    with pytest.raises(ValueError,match='another artifact'):
        download(info['artifact_id'],releases,store)


def test_real_baseline_preserves_numeric_route_code_leading_zero(tmp_path,monkeypatch):
    import sqlite3
    import pandas as pd
    from datetime import datetime
    from module_3_bus_eta_prediction.step_3_1_historical_baseline_model import baseline_matrix_builder as baseline
    database=tmp_path/'baseline.db'
    with sqlite3.connect(database) as conn:
        conn.execute('CREATE TABLE canonical_shape_master(route_code TEXT,direction TEXT,cum_distance_m REAL)')
        conn.execute("INSERT INTO canonical_shape_master VALUES ('02','go',600)")
        conn.execute('CREATE TABLE canonical_station_master(route_code TEXT,direction TEXT,station_order INTEGER,station_id INTEGER,station_name TEXT,cum_distance_m REAL)')
        conn.executemany("INSERT INTO canonical_station_master VALUES ('02','go',?,?,?,?)",[(i,i+1,str(i),i*200) for i in range(4)])
    silver=tmp_path/'silver'
    partition=silver/'route_code=02'/'dt=2026-10-27'
    partition.mkdir(parents=True)
    epoch=datetime.fromisoformat('2026-10-27T13:00:00+07:00').timestamp()
    pd.DataFrame([dict(vehicle_id=1,device_update_time='2026-10-27T13:00:00+07:00',device_epoch=epoch+i*30,direction='go',s_bus_m=i*150.0,derived_speed_kmh=18.0) for i in range(5)]).to_parquet(partition/'part.parquet',index=False)
    monkeypatch.setattr(baseline,'DB_PATH',str(database))
    monkeypatch.setattr(baseline,'SILVER_TEL_DIR',str(silver))
    monkeypatch.setattr(baseline,'GOLD_BASELINE_DIR',str(tmp_path/'gold'))
    result=baseline.build_and_evaluate_baseline_matrix()
    assert result['train_trips']==1 and result['total_cells']>0
    with sqlite3.connect(database) as conn:
        assert conn.execute('SELECT DISTINCT route_code FROM agg_segment_travel_times').fetchall()==[('02',)]
