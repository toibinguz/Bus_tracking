"""Real SQLite + release manifests + HTTP; HDFS is never used by requests."""
from datetime import datetime
import json
from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient
import pytest

from module_2_big_data_storage_and_lakehouse.step_2_4_hdfs_history import eta_snapshot as pipeline
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation import serving_service as serving
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.dto import BusVehicleDTO, RouteLiveResponse
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.model_runtime import ModelRuntime


@pytest.fixture
def source(tmp_path):
    catalog = tmp_path / 'catalog.db'
    with sqlite3.connect(catalog) as conn:
        conn.execute('CREATE TABLE canonical_route_master(route_id,route_code,route_name)')
        conn.execute("INSERT INTO canonical_route_master VALUES (2,'02','Route 02')")
        conn.execute('CREATE TABLE canonical_shape_master(route_id,route_code,direction,point_order,lat,lon,cum_distance_m)')
        conn.executemany("INSERT INTO canonical_shape_master VALUES (2,'02','go',?,?,?,?)",
                         [(0,21.0,105.0,0.0),(1,21.01,105.0,1112.0)])
        conn.execute('CREATE TABLE canonical_station_master(route_id,route_code,direction,station_order,station_id,station_name,address,lat,lon,cum_distance_m)')
        conn.executemany("INSERT INTO canonical_station_master VALUES (2,'02','go',?,?,?,?,?,?,?)",
                         [(i,i+10,str(i),'',21.0+s/111200,105.0,s) for i,s in enumerate((0,300,700,1112))])
        conn.execute('CREATE TABLE agg_segment_travel_times(route_code,direction,from_station_order,to_station_order,day_type,hour_slot,quality_tier,tt_p10_sec,tt_p50_sec,tt_p90_sec,tt_mean_sec,tt_std_sec,segment_length_m)')
        conn.executemany("INSERT INTO agg_segment_travel_times VALUES ('02','go',1,2,?,?,1,50,999,150,100,20,400)",
                         [(day,hour) for day in range(3) for hour in range(5,22)])
    pointer = tmp_path / 'active.json'

    def make_release(name, p50=100):
        release = tmp_path / name
        release.mkdir()
        with sqlite3.connect(catalog) as src, sqlite3.connect(release/'baseline.db') as dest:
            src.backup(dest)
            dest.execute('UPDATE agg_segment_travel_times SET tt_p50_sec=?', (p50,))
        info = dict(schema_version='eta-artifact.v1', snapshot_id='a'*64, files=pipeline.files_manifest(release))
        info['artifact_id'] = pipeline.digest(pipeline.encoded(info))
        (release/'artifact.json').write_bytes(pipeline.encoded(info))
        pipeline.activate(release, pointer)
        return release, info

    release, info = make_release('release')
    return dict(catalog=catalog, pointer=pointer, release=release, info=info,
                make_release=make_release, timbus=tmp_path/'missing-timbus.db')


def create_service(source):
    return serving.BusMapServingService(str(source['catalog']), str(source['timbus']), str(source['pointer']))


def test_release_http_uses_exported_baseline_without_hdfs_or_candidate_model(source, monkeypatch):
    from module_3_bus_eta_prediction.step_3_5_web_demo import app as web

    def forbidden(*args, **kwargs):
        pytest.fail('release serving invoked an external process/HDFS or unverified model loader')
    monkeypatch.setattr(pipeline, 'transport', forbidden)
    monkeypatch.setattr('subprocess.run', forbidden)
    monkeypatch.setattr(ModelRuntime, 'load', forbidden)
    svc = create_service(source)
    monkeypatch.setattr(web, 'service', svc)
    # The operational DB deliberately contains 999 seconds, not the release's 100.
    assert svc._da.get_baseline_cell(2, 0, 1, 2, 0, 8)[1] == 100
    now = datetime.now().astimezone().isoformat()
    bus = BusVehicleDTO(id=1,plate='29A00001',route_id=2,direction=0,
                        lat=21.0036,lng=105.0,deg=0,speed_kmh=20,updated_at=now)
    monkeypatch.setattr(serving, 'fetch_live_vehicles_for_route', lambda route_id,direction=0:
                        RouteLiveResponse(route_id=route_id,direction=direction,timestamp=now,count=1,vehicles=[bus]))
    with TestClient(web.app) as client:
        assert client.get('/api/routes').json()[0]['route_no'] == '02'
        assert client.get('/api/route-stations', params={'route':'02'}).status_code == 200
        result = client.get('/api/station-eta',params={'route':'02','direction':0,'station_order':2})
        assert result.status_code == 200, result.text
        assert result.json()['buses'][0]['prediction_source'] == 'baseline_fallback'
        # About 300 of the 400 segment metres remain: release ETA is ~75s,
        # whereas accidentally reading the operational DB would give ~749s.
        assert result.json()['buses'][0]['eta_seconds'] == pytest.approx(75, abs=2)
        identity = client.get('/api/health').json()['serving']
        assert identity['artifact_id'] == source['info']['artifact_id']
        assert identity['baseline_routes'] == ['02']
        assert identity['model_status'] == 'disabled_release_compatibility_unverified'
    assert not svc._runtime.available
    assert Path(svc._incidents._inc_dir).is_relative_to(source['release'])


def test_release_is_pinned_until_service_restart(source):
    first = create_service(source)
    _, second_info = source['make_release']('next-release', p50=120)
    assert first._da.get_baseline_cell(2,0,1,2,0,8)[1] == 100
    assert first.source_info['artifact_id'] == source['info']['artifact_id']
    second = create_service(source)
    assert second._da.get_baseline_cell(2,0,1,2,0,8)[1] == 120
    assert second.source_info['artifact_id'] == second_info['artifact_id']


@pytest.mark.parametrize('table,column', [('canonical_shape_master','lat'), ('canonical_station_master','cum_distance_m')])
def test_mismatched_geometry_is_rejected_instead_of_mixed(source, table, column):
    with sqlite3.connect(source['catalog']) as conn:
        conn.execute(f'UPDATE {table} SET {column}={column}+1')
    with pytest.raises(ValueError, match='geometry mismatch'):
        create_service(source)


def test_wrong_route_id_is_rejected(source):
    with sqlite3.connect(source['catalog']) as conn:
        conn.execute('UPDATE canonical_route_master SET route_id=999')
    with pytest.raises(ValueError, match='route identity mismatch'):
        create_service(source)


def test_corrupted_release_is_rejected_without_local_fallback(source):
    with (source['release']/'baseline.db').open('ab') as stream:
        stream.write(b'corruption')
    with pytest.raises(ValueError, match='corrupted'):
        create_service(source)


def test_mismatched_pointer_is_rejected(source):
    pointer = json.loads(source['pointer'].read_text())
    pointer['artifact_id'] = 'f'*64
    source['pointer'].write_text(json.dumps(pointer))
    with pytest.raises(ValueError, match='pointer/release mismatch'):
        create_service(source)
