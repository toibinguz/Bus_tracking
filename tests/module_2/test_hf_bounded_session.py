import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from sync_hf_hdfs_session import choose, once


class Store:
    def __init__(self):self.objects={}
    def exists(self,path):return path in self.objects
    def read(self,path):return self.objects[path]
    def create(self,path,content):
        assert path not in self.objects
        self.objects[path]=content


def entry(number,content=b'{}\n'):
    sha=hashlib.sha256(content).hexdigest()
    return dict(path=f'raw_data/2026-11-17/bus/{number}.jsonl',bytes=len(content),signature=sha,sha256=sha)


def test_bounded_sessions_resume_and_recheck_remote_even_after_data_loss(tmp_path):
    entries=[entry(i) for i in range(3)];store=Store()
    first=once(tmp_path,'dataset','a'*40,entries,lambda path:b'{}\n',store,max_files=2)
    assert first['processed']==2 and first['remaining_new']==1
    second=once(tmp_path,'dataset','a'*40,entries,lambda path:b'{}\n',store,max_files=2)
    assert second['remaining_new']==0
    store.objects.clear()
    for _ in range(3):once(tmp_path,'dataset','a'*40,entries,lambda path:b'{}\n',store,max_files=2)
    assert sum(path.endswith('/manifest.json') for path in store.objects)==3


def test_failed_upload_never_advances_checkpoint(tmp_path):
    class Offline(Store):
        def create(self,*args):raise RuntimeError('offline')
    with pytest.raises(RuntimeError):once(tmp_path,'dataset','a'*40,[entry(1)],lambda path:b'{}\n',Offline())
    assert not (tmp_path/'checkpoint.json').exists()
    assert list((tmp_path/'stage').rglob('batch.jsonl'))


def test_corrupt_source_same_size_is_rejected_before_any_upload(tmp_path):
    store=Store()
    with pytest.raises(ValueError,match='SHA-256'):
        once(tmp_path,'dataset','rev',[entry(1)],lambda path:b'[]\n',store)
    assert store.objects=={}


def test_oversized_file_is_not_silently_dropped():
    with pytest.raises(ValueError,match='byte budget'):choose([entry(1)],{},16,1)
