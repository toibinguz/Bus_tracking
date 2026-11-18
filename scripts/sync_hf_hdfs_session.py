"""Bounded HF-to-HDFS receiving session; no daemon and no automatic deletion."""
import argparse
from datetime import date, datetime, timezone
import json
import hashlib
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from module_2_big_data_storage_and_lakehouse.step_2_4_hdfs_history.hf_bronze import atomic_write, encoded, stage_batch, receive_batch, DockerHdfs


def choose(entries,state,max_files,max_bytes):
    """New/changed objects first; then rotate verified ones for remote rechecks."""
    entries=sorted(entries,key=lambda row:row['path'])
    known=state.get('objects',{})
    new=[r for r in entries if known.get(r['path'],{}).get('signature')!=r['signature']]
    old=[r for r in entries if r not in new]
    if old:
        cursor=state.get('cursor',0)%len(old);old=old[cursor:]+old[:cursor]
    selected=[];size=0
    for row in new+old:
        if row['bytes']>max_bytes: raise ValueError('source object exceeds session byte budget: '+row['path'])
        if len(selected)>=max_files or size+row['bytes']>max_bytes:break
        selected.append(row);size+=row['bytes']
    return selected


def once(root,dataset,revision,entries,download,store,max_files=16,max_bytes=33554432):
    root=Path(root)
    checkpoint=root/'checkpoint.json'
    state=json.loads(checkpoint.read_text()) if checkpoint.exists() else dict(objects={},cursor=0,dataset=dataset)
    if state['dataset']!=dataset:raise ValueError('checkpoint belongs to another dataset')
    selected=choose(entries,state,max_files,max_bytes)
    results=[]
    for row in selected:
        content=download(row['path'])
        if len(content)!=row['bytes']:raise ValueError('source size changed at pinned revision')
        if row.get('sha256') and hashlib.sha256(content).hexdigest()!=row['sha256']:
            raise ValueError('source SHA-256 mismatch')
        if row.get('git_blob_id') and hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest()!=row['git_blob_id']:
            raise ValueError('source Git blob mismatch')
        metadata=stage_batch(root/'stage',dataset,revision,row['path'],content)
        descriptor=root/'stage'/metadata['batch_id']/'sources'/(revision+'.json')
        receipt=receive_batch(root/'stage',descriptor,store)
        # Checkpoint only after a verified remote receipt; an interrupted pass resumes.
        state['objects'][row['path']]=dict(signature=row['signature'],batch_id=receipt['batch_id'],revision=revision)
        state['cursor']=state.get('cursor',0)+1
        atomic_write(checkpoint,encoded(state))
        results.append(receipt)
    result=dict(revision=revision,processed=len(results),already_received=sum(r['already_received'] for r in results),
                bytes=sum(r['bytes'] for r in selected),eligible_files=len(entries),
                remaining_new=sum(state['objects'].get(r['path'],{}).get('signature')!=r['signature'] for r in entries),
                verified_at=datetime.now(timezone.utc).isoformat())
    atomic_write(root/'last_pass.json',encoded(result))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date',type=date.fromisoformat,required=True)
    parser.add_argument('--state-dir',type=Path,required=True)
    parser.add_argument('--iterations',type=int,default=1)
    parser.add_argument('--interval',type=float,default=60)
    parser.add_argument('--max-files',type=int,default=16)
    parser.add_argument('--max-bytes',type=int,default=33554432)
    args=parser.parse_args()
    if min(args.iterations,args.max_files,args.max_bytes)<1 or args.interval<1:parser.error('limits must be positive')
    os.environ.setdefault('HF_HUB_DISABLE_XET','1')
    os.environ.setdefault('HF_HUB_DOWNLOAD_TIMEOUT','30')
    os.environ.setdefault('HF_HUB_ETAG_TIMEOUT','15')
    from huggingface_hub import HfApi,hf_hub_download
    from config import HF_DATASET_ID,get_hf_token
    token=get_hf_token() or None;api=HfApi(token=token)
    for iteration in range(args.iterations):
        revision=api.dataset_info(HF_DATASET_ID).sha
        prefix='raw_data/'+args.date.isoformat()
        entries=[]
        for item in api.list_repo_tree(HF_DATASET_ID,repo_type='dataset',revision=revision,path_in_repo=prefix,recursive=True):
            if getattr(item,'path','').endswith('.jsonl'):
                lfs=getattr(item,'lfs',None)
                raw_sha=getattr(lfs,'sha256',None) if lfs else None
                entries.append(dict(path=item.path,bytes=item.size,signature=raw_sha or item.blob_id,
                                    sha256=raw_sha,git_blob_id=None if raw_sha else item.blob_id))
        def download(path):
            local=hf_hub_download(HF_DATASET_ID,filename=path,repo_type='dataset',revision=revision,token=token,cache_dir=args.state_dir/'hf_cache')
            return Path(local).read_bytes()
        print(json.dumps(once(args.state_dir,HF_DATASET_ID,revision,entries,download,DockerHdfs(ROOT/'docker-compose.hdfs.yml'),args.max_files,args.max_bytes)),flush=True)
        if iteration+1<args.iterations:time.sleep(args.interval)
