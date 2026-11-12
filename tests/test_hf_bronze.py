import json
import pytest

from module_2_big_data_storage_and_lakehouse.step_2_4_hdfs_history.hf_bronze import descriptor, receive_batch, stage_batch

REV = 'a' * 40
PATH = 'raw_data/2026-11-12/bus/batch_161350.jsonl'


class Store:
    def __init__(self):
        self.objects = {}
    def exists(self, path):
        return path in self.objects
    def create(self, path, content):
        assert path not in self.objects
        self.objects[path] = content
    def read(self, path):
        return self.objects[path]


def prepare(tmp_path, revision=REV, content=b'{"raw":true}\n'):
    metadata = stage_batch(tmp_path, 'test/dataset', revision, PATH, content)
    return tmp_path / metadata['batch_id'] / 'sources' / (revision + '.json')


def test_repeated_receive_and_revision_keep_one_batch(tmp_path):
    source = prepare(tmp_path)
    store = Store()
    first = receive_batch(tmp_path, source, store)
    count = len(store.objects)
    second = receive_batch(tmp_path, source, store)
    assert second['already_received'] and first['batch_id'] == second['batch_id']
    assert len(store.objects) == count
    third = receive_batch(tmp_path, prepare(tmp_path, 'b' * 40), store)
    assert third['batch_id'] == first['batch_id'] and third['already_received']
    assert len(store.objects) == count + 1  # only revision sighting


@pytest.mark.parametrize('failpoint', ['after_raw', 'before_receipt'])
def test_interruption_retry(tmp_path, failpoint):
    source, store = prepare(tmp_path), Store()
    with pytest.raises(RuntimeError, match='injected'):
        receive_batch(tmp_path, source, store, failpoint)
    assert not list(tmp_path.glob('*/receipts/*.json'))
    receive_batch(tmp_path, source, store)
    assert len(store.objects) == 3
    assert len(list(tmp_path.glob('*/receipts/*.json'))) == 1


def test_modified_same_path_is_new_version(tmp_path):
    first = prepare(tmp_path)
    second = prepare(tmp_path, content=b'{"raw":false}\n')
    store = Store()
    a, b = receive_batch(tmp_path, first, store), receive_batch(tmp_path, second, store)
    assert a['batch_id'] != b['batch_id'] and len(store.objects) == 6


def test_staging_corruption_prevents_any_upload(tmp_path):
    source = prepare(tmp_path)
    (source.parent.parent / 'batch.jsonl').write_bytes(b'changed')
    store = Store()
    with pytest.raises(ValueError, match='mismatch'):
        receive_batch(tmp_path, source, store)
    assert not store.objects


def test_remote_corruption_not_hidden_by_local_receipt(tmp_path):
    source, store = prepare(tmp_path), Store()
    receive_batch(tmp_path, source, store)
    metadata = json.loads(source.read_text())
    store.objects[metadata['hdfs_raw_path']] = b'wrong'
    with pytest.raises(ValueError, match='differs'):
        receive_batch(tmp_path, source, store)


def test_outage_preserves_staging_without_false_receipt(tmp_path):
    source = prepare(tmp_path)
    before = (source.parent.parent / 'batch.jsonl').read_bytes()
    class Offline(Store):
        def exists(self, path):
            raise RuntimeError('HDFS unavailable')
    with pytest.raises(RuntimeError, match='unavailable'):
        receive_batch(tmp_path, source, Offline())
    assert (source.parent.parent / 'batch.jsonl').read_bytes() == before
    assert not list(tmp_path.glob('*/receipts/*.json'))


def test_lost_create_ack_is_verified_before_success(tmp_path):
    source = prepare(tmp_path)
    class LostReply(Store):
        def create(self, path, content):
            super().create(path, content)
            raise RuntimeError('ack lost after commit')
    store = LostReply()
    receive_batch(tmp_path, source, store)
    assert len(store.objects) == 3
    assert len(list(tmp_path.glob('*/receipts/*.json'))) == 1


@pytest.mark.parametrize('path', ['../other.jsonl', 'raw_data/2026-11-12/unknown/file.jsonl', 'raw_data/bad/bus/file.jsonl'])
def test_path_contract(path):
    with pytest.raises(ValueError):
        descriptor('test/dataset', REV, path, b'')


def test_legacy_traffic_is_raw_bronze_not_bus_schema():
    content=b'{"legacy_traffic":true}\n'
    metadata=descriptor('test/dataset',REV,'raw_data/2026-11-12/traffic/file.jsonl',content)
    assert metadata['category']=='traffic'
    assert '/category=traffic/' in metadata['hdfs_raw_path']
