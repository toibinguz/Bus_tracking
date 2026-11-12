import json
from unittest.mock import patch

from module_2_big_data_storage_and_lakehouse.step_2_4_hdfs_history.history_snapshot import normalize_bus, normalize_incident, merge_event, project_group


def reference():
    return {'routes':{'8':'08A'}, 'stations':[], 'shapes':{}}


def raw(**changes):
    value = dict(route_id=8, vehicle_id=1,lat=21,lon=105.8,device_update_time='2026-11-12T08:00:00+07:00',crawled_at='2026-11-12T08:00:05+07:00',direction=0,current_station_id=45)
    value.update(changes)
    return json.dumps(value)


def test_identity_independent_of_batch_poll_and_arrival_order():
    a = normalize_bus(raw(), 'batch-a',reference())[1]
    b = normalize_bus(raw(crawled_at='2026-11-12T08:01:00+07:00'), 'batch-b',reference())[1]
    assert a['event_id'] == b['event_id']
    first = merge_event((a['event_id'],[a,b]))
    assert first == merge_event((a['event_id'],[b,a]))
    assert first['batch_ids'] == ['batch-a','batch-b'] and first['captured_ms'] == a['captured_ms']


def test_unknown_route_and_naive_timestamp_rejected_per_event():
    assert normalize_bus(raw(route_id=99999),'batch',reference())[1]['reason'] == 'unknown_route'
    assert normalize_bus(raw(device_update_time='2026-11-12T08:00:00'),'batch',reference())[0] == 'reject'
    assert normalize_bus(raw(device_update_time=None),'batch',reference())[0] == 'reject'


def test_incident_identity_retains_changes_and_null():
    value = {'incident_id':'id','timestamp':'2026-11-12T08:00:00+07:00','delay_seconds':None}
    a = normalize_incident(json.dumps(value),'batch-a')[1]
    b = normalize_incident(json.dumps(value),'batch-b')[1]
    assert a['observation_id']==b['observation_id']
    assert json.loads(a['raw_json'])['delay_seconds'] is None
    c = normalize_incident(json.dumps(dict(value,delay_seconds=10)),'batch-a')[1]
    assert c['observation_id']!=a['observation_id']
    assert normalize_incident('{}','batch-a')[0]=='reject'


def test_ambiguous_station_keeps_raw_hint_not_arbitrary_lookup():
    ref = reference()
    ref['stations'] = [dict(route_id=8,station_id=45,direction=d) for d in ('go','re')]
    row = normalize_bus(raw(direction=1),'batch',ref)[1]
    row['batch_ids'] = ['batch']
    target = 'module_1_data_ingestion_and_preprocessing.step_1_4_frenet_spatial_projection.projection_boundary.project_route_events'
    with patch(target, return_value=([],{})) as projector:
        project_group((8,[row]),ref)
        events, shapes, station_lookup = projector.call_args.args
        assert events[0].direction_hint == 're'
        assert (8,45) not in station_lookup


def test_unknown_direction_is_not_return():
    row = normalize_bus(raw(direction=-1),'batch',reference())[1]
    target = 'module_1_data_ingestion_and_preprocessing.step_1_4_frenet_spatial_projection.projection_boundary.project_route_events'
    with patch(target, return_value=([],{'unknown_direction':1})) as projector:
        result = project_group((8,[row]),reference())
        assert projector.call_args.args[0][0].direction_hint == 'unknown'
        assert result['rejected'][0]['event_id'] == row['event_id']
