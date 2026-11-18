import hashlib
import json
import struct

from module_1_data_ingestion_and_preprocessing.step_1_1_busmap_crawler_and_relay.upstream_capture import capture,http_request_id
from experiments.timbus.timbus_tracker import TimBusClient


def test_raw_bytes_are_lossless_deduplicated_and_each_exchange_is_retained(tmp_path,monkeypatch):
    monkeypatch.setenv('ETA_UPSTREAM_RAW_DIR',str(tmp_path))
    body=b' {"x":1.000,"unknown":null}\r\n'
    token=http_request_id.set('request-123')
    try:
        for _ in range(2):capture('busmap',{'route_id':2},body,200,{'Content-Type':'application/json','Set-Cookie':'secret'})
    finally:http_request_id.reset(token)
    rows=[json.loads(x) for x in (tmp_path/'index.jsonl').read_text().splitlines()]
    assert len(rows)==2 and rows[0]['capture_id']!=rows[1]['capture_id']
    assert len(list((tmp_path/'objects').rglob('*.bin')))==1
    for row in rows:
        reference=row['files']['response']
        assert (tmp_path/reference['path']).read_bytes()==body
        assert reference['sha256']==hashlib.sha256(body).hexdigest()
        assert row['http_request_id']=='request-123'
        assert 'Set-Cookie' not in row['headers']


def test_timbus_request_material_can_be_decoded_without_parsed_dto():
    payload=TimBusClient.build_request_body(1676,'','29F05192',0)
    encrypted=TimBusClient.encrypt_packet(payload)
    assert TimBusClient.decrypt_packet(encrypted)==struct.pack('<I',TimBusClient.DEFAULT_CLIENT_ID)+payload


def test_capture_is_opt_in_and_does_not_raise_on_storage_failure(tmp_path,monkeypatch):
    monkeypatch.delenv('ETA_UPSTREAM_RAW_DIR',raising=False)
    assert capture('busmap',{},b'raw') is None
    blocker=tmp_path/'file';blocker.write_text('occupied')
    monkeypatch.setenv('ETA_UPSTREAM_RAW_DIR',str(blocker))
    assert capture('busmap',{},b'raw') is None
