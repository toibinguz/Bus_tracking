import copy
import json
from unittest.mock import patch

from module_1_data_ingestion_and_preprocessing.step_1_1_busmap_crawler_and_relay.hdfs_bronze_adapter import spool_crawler_batch


def test_crawler_spool_operates_without_network_and_splits_hours(tmp_path):
    record = dict(route_id=8, vehicle_id=10, plate='TEST', direction=1, lat=21.0, lon=105.8,
                  device_update_time='2026-11-01T08:59:00+07:00', crawled_at='2026-11-01T09:00:00+07:00')
    records = [record, {**record, 'device_update_time': '2026-11-01T09:01:00+07:00'}]
    original = copy.deepcopy(records)
    with patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('collection must stay offline')):
        paths = spool_crawler_batch(records, spool_root=tmp_path, route_codes={8: '08A'})
    assert len(paths) == 2
    rows = [json.loads(path.read_text()) for path in paths]
    assert {row['provenance'] for row in rows} == {'observed'}
    assert len({row['source_window_id'] for row in rows}) == 2
    assert len({row['event_id'] for row in rows}) == 2
    assert not list(tmp_path.rglob('*.tmp'))
    assert records == original
