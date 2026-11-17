import io
import json
from datetime import datetime, timedelta

import pytest

from module_2_big_data_storage_and_lakehouse.step_2_4_hdfs_history.history_execution import merge_bus, project_vehicles, read_batches
from module_2_big_data_storage_and_lakehouse.step_2_4_hdfs_history.history_snapshot import normalize_bus, merge_event, project_group
from module_2_big_data_storage_and_lakehouse.step_2_4_hdfs_history.hf_bronze import descriptor
from module_2_big_data_storage_and_lakehouse.step_2_4_hdfs_history.eta_snapshot import parquet_table


def observations():
    ref=dict(routes={'8':'08A'},stations=[],shapes={'8':{'go':[[0,21.0,105.8,0],[1,21.02,105.8,2222]],'re':[[0,21.02,105.8,0],[1,21.0,105.8,2222]]}})
    start=datetime.fromisoformat('2026-11-12T23:59:30+07:00')
    rows=[]
    for vehicle in (1,2):
        for i in range(4):
            time=(start+timedelta(seconds=i*30)).isoformat()
            raw=json.dumps(dict(route_id=8,vehicle_id=vehicle,lat=21.002+i*.001,lon=105.8,device_update_time=time,crawled_at=time,direction=1 if i==1 else 0))
            row=normalize_bus(raw,'batch-a',ref)[1]
            row['batch_ids']=['batch-a']
            rows.append(row)
    return ref,rows


def ordered(rows):
    return iter(sorted([((r['route_id'],r['vehicle_id'],r['observed_ms'],r['event_id']),r) for r in rows]))


def test_vehicle_projection_exact_parity_across_midnight_and_direction_blip():
    ref,rows=observations()
    expected=project_group((8,list(reversed(rows))),ref)
    actual=list(project_vehicles(ordered(rows),ref,4))
    canonical=lambda rs:sorted(rs,key=lambda r:r['event_id'])
    assert len(expected['rows'])==8
    assert canonical(expected['rows'])==canonical([r for group in actual for r in group['rows']])
    assert sorted(r['input_events'] for r in actual)==[4,4]
    assert any(r['derived_speed_kmh'] is not None and '2026-11-13T00:00' in r['device_update_time'] for r in expected['rows'])
    with pytest.raises(ValueError,match='event limit'):
        list(project_vehicles(ordered(rows),ref,3))


def test_combiner_matches_original_late_observation_and_preserves_all_lineage():
    _,rows=observations()
    first=rows[0]
    later=dict(first,captured_ms=first['captured_ms']+1000,batch_id='batch-b',batch_ids=['batch-b'])
    earlier=dict(first,captured_ms=first['captured_ms']-1000,batch_id='batch-c',batch_ids=['batch-c'])
    expected=merge_event((first['event_id'],[first,later,earlier]))
    assert merge_bus(merge_bus(first,later),earlier)==expected
    assert merge_bus(first,merge_bus(earlier,later))==expected


def test_stale_gap_sessions_match_whole_history_without_midnight_reset():
    ref,rows=observations()
    later=[]
    for row in rows:
        raw=json.loads(row['raw_json'])
        for name in ('device_update_time','crawled_at'):
            raw[name]=(datetime.fromisoformat(raw[name])+timedelta(days=1)).isoformat()
        value=normalize_bus(json.dumps(raw),'late-batch',ref)[1]
        value['batch_ids']=['late-batch']
        later.append(value)
    combined=rows+later
    expected=project_group((8,combined),ref)
    actual=list(project_vehicles(ordered(combined),ref,4))
    assert len(actual)==4
    canonical=lambda rs:sorted(rs,key=lambda r:r['event_id'])
    assert canonical(expected['rows'])==canonical([r for group in actual for r in group['rows']])
    assert all(group['input_events']==4 for group in actual)


def test_executor_checks_raw_hash_and_size_before_normalization(monkeypatch):
    from module_2_big_data_storage_and_lakehouse.step_2_4_hdfs_history import artifact_transport
    raw=b'{"invalid":"bus"}\n'
    metadata=descriptor('dataset','a'*40,'raw_data/2026-11-12/bus/batch.jsonl',raw)
    class Store:
        def read(self,path,max_bytes=None):return raw
    monkeypatch.setattr(artifact_transport,'PrivateWebHdfs',Store)
    result=list(read_batches([metadata],{},1024))
    assert result[0][0]=='bus_reject' and result[-1][0]=='batch'
    with pytest.raises(ValueError,match='byte limit'):
        list(read_batches([metadata],{},1))
    with pytest.raises(ValueError,match='hash mismatch'):
        list(read_batches([dict(metadata,bytes=len(raw)+1)],{},1024))


def test_cache_reads_only_selected_partition_and_preserves_route_02():
    import pyarrow as pa
    import pyarrow.parquet as pq
    class Store:
        def __init__(self):self.reads=[]
        def call(self,*args):
            return b'file /silver/route_code=02/dt=2026-11-01/part.parquet\nfile /silver/route_code=27/dt=2026-11-01/part.parquet\nfile /silver/route_code=02/dt=2026-11-02/part.parquet\n'
        def read(self,path):
            self.reads.append(path)
            buffer=io.BytesIO()
            pq.write_table(pa.table({'event_id':['event']}),buffer)
            return buffer.getvalue()
    store=Store()
    table=parquet_table(store,'/silver',['2026-11-01'],['02'])
    assert store.reads==['/silver/route_code=02/dt=2026-11-01/part.parquet']
    assert table.to_pylist()==[dict(event_id='event',route_code='02',dt='2026-11-01')]
    assert len(parquet_table(store,'/silver',['2026-12-01'],allow_empty=True))==0


def test_selected_cache_accounts_partition_rows_and_uses_hanoi_event_day(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq
    from module_2_big_data_storage_and_lakehouse.step_2_4_hdfs_history.eta_snapshot import materialize, HDFS
    from module_2_big_data_storage_and_lakehouse.step_2_4_hdfs_history.hf_bronze import encoded, digest
    snapshot='a'*64
    root=HDFS+'/silver/history/_runs/snapshot='+snapshot+'/attempt=one'
    reference=encoded({'routes':{'2':'02'},'stations':[],'shapes':{}})
    source=dict(snapshot_id=snapshot,snapshot_path=root,silver_path=root+'/route_projected_telemetry',
                reference_path=HDFS+'/reference/history/ref.json',reference_sha256=digest(reference),accepted_bus_rows=2,
                incident_observations=1,silver_partitions=[dict(route_code=r,dt='2026-11-17',rows=1) for r in ('02','27')])
    stream=io.BytesIO()
    timestamp='2026-11-16T17:00:00+00:00'
    pq.write_table(pa.table({'event_id':['event'],'device_update_time':[timestamp],'device_epoch_s':[datetime.fromisoformat(timestamp).timestamp()]}),stream)
    selected=source['silver_path']+'/route_code=02/dt=2026-11-17/part.parquet'
    incident_part=root+'/incident_observations/dt=2026-11-17/part.parquet'
    incident_stream=io.BytesIO()
    pq.write_table(pa.table({'raw_json':[json.dumps(dict(incident_id='incident',timestamp=timestamp))]}),incident_stream)
    class Store:
        def call(self,*args):
            return (incident_part if args[-1].endswith('/incident_observations') else selected+'\n'+selected.replace('route_code=02','route_code=27')).encode()
        def read(self,path):
            return {HDFS+'/_published/history_snapshots/'+snapshot+'.json':encoded(source),root+'/snapshot.json':encoded(source),
                    source['reference_path']:reference,selected:stream.getvalue(),incident_part:incident_stream.getvalue()}[path]
    info=materialize(snapshot,tmp_path/'cache',['2026-11-17'],['02'],Store())
    assert info['ping_count']==1
    assert info['incident_observations']==1
    assert (tmp_path/'cache/raw/2026-11-17/incidents/observed.jsonl').exists()
    assert (tmp_path/'cache/silver/route_projected_telemetry/route_code=02/dt=2026-11-17/part.parquet').exists()


def test_transport_refuses_oversized_remote_bytes(monkeypatch):
    from module_2_big_data_storage_and_lakehouse.step_2_4_hdfs_history import artifact_transport
    class Opener:
        def open(self,*args,**kwargs):return io.BytesIO(b'oversized')
    monkeypatch.setattr(artifact_transport,'build_opener',Opener)
    store=artifact_transport.PrivateWebHdfs()
    with pytest.raises(ValueError,match='byte limit'):
        store.read('/bus-eta/v1/bronze/test',max_bytes=2)


def test_bulk_recheck_restores_remote_even_when_local_receipt_exists(tmp_path,monkeypatch):
    import config
    import huggingface_hub
    from types import SimpleNamespace
    from scripts import hdfs_import_history as importer
    from module_2_big_data_storage_and_lakehouse.step_2_4_hdfs_history.hf_bronze import stage_batch, receive_batch, encoded
    root=tmp_path/'runtime/hf_full_history'
    content=b'{"source":"retained"}\n'
    source=tmp_path/'retained.jsonl'
    source.write_bytes(content)
    metadata=stage_batch(root/'stage','fixture','a'*40,'raw_data/2026-11-17/bus/one.jsonl',content)
    receipt=root/'stage'/metadata['batch_id']/'receipts'/('a'*40+'.json')
    receipt.parent.mkdir()
    receipt.write_bytes(encoded(dict(metadata,status='verified')))
    inventory=dict(dataset='fixture',revision='a'*40,total_bytes=len(content),categories={'bus':1},
                   files=[dict(path=metadata['path'],bytes=len(content))])
    plan=root/'plan.json'
    plan.write_bytes(encoded(inventory))
    objects={}
    class Store:
        def exists(self,path):return path in objects
        def read(self,path):return objects[path]
        def create(self,path,data):objects[path]=data
    def upload(*args,**kwargs):
        receive_batch(root/'stage',root/'stage'/metadata['batch_id']/'sources'/('a'*40+'.json'),Store())
        return SimpleNamespace(returncode=0,stdout='verified',stderr='')
    monkeypatch.setattr(importer,'ROOT',tmp_path)
    monkeypatch.setattr(huggingface_hub,'hf_hub_download',lambda *args,**kwargs:str(source))
    monkeypatch.setattr(config,'get_hf_token',lambda:None)
    monkeypatch.setattr(importer.subprocess,'run',upload)
    importer.run(plan,1,1,recheck=True)
    assert objects[metadata['hdfs_raw_path']]==content
    assert json.loads(receipt.read_text())['status']=='verified'
