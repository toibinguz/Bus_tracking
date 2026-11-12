"""Plan a pinned whole-history HF import; subsequent execution is bounded and resumable."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor,as_completed
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from module_2_big_data_storage_and_lakehouse.step_2_4_hdfs_history.hf_bronze import atomic_write,encoded,digest,stage_batch,receive_batch


def plan(output,revision=None):
    from huggingface_hub import HfApi
    from config import HF_DATASET_ID,get_hf_token
    api=HfApi(token=get_hf_token() or None)
    revision=api.dataset_info(HF_DATASET_ID,revision=revision).sha
    entries=[]
    for entry in api.list_repo_tree(HF_DATASET_ID,repo_type='dataset',revision=revision,recursive=True):
        if hasattr(entry,'size') and entry.path.startswith('raw_data/'):
            lfs=getattr(entry,'lfs',None)
            sha=lfs.get('sha256') if isinstance(lfs,dict) else getattr(lfs,'sha256',None)
            entries.append(dict(path=entry.path,bytes=entry.size,sha256=sha,blob_id=entry.blob_id))
    entries.sort(key=lambda row:row['path'])
    result=dict(dataset=HF_DATASET_ID,revision=revision,files=entries,total_bytes=sum(row['bytes'] for row in entries),
                categories=dict(Counter(row['path'].split('/')[2] if len(row['path'].split('/'))>2 else 'unknown' for row in entries)))
    if Path(output).exists():
        raise ValueError('plan already exists; use it to resume rather than switching revision')
    atomic_write(output,encoded(result))
    print(json.dumps({k:v for k,v in result.items() if k!='files'}),flush=True)
    print('FILES='+str(len(entries)),flush=True)
    print('NON_JSONL='+json.dumps([row for row in entries if not row['path'].endswith('.jsonl')][:10]),flush=True)


def upload(index,workers):
    from module_2_big_data_storage_and_lakehouse.step_2_4_hdfs_history.artifact_transport import PrivateWebHdfs
    sources=json.loads(Path(index).read_text())
    store=PrivateWebHdfs()
    errors=[]
    started=time.monotonic()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures={pool.submit(receive_batch,Path('/import/stage'),Path('/import/stage')/source,store):source for source in sources}
        for future in as_completed(futures):
            try:
                print(json.dumps(future.result()),flush=True)
            except Exception as error:
                errors.append(dict(source=futures[future],error=str(error)))
    if errors:
        raise RuntimeError(json.dumps(errors))
    print('UPLOAD_STATS='+json.dumps(dict(batches=len(sources),elapsed_seconds=round(time.monotonic()-started,2))),flush=True)


def run(plan_path,workers,chunk_size):
    from huggingface_hub import hf_hub_download
    from config import get_hf_token
    root=Path(plan_path).resolve().parent
    if root!=ROOT/'runtime'/'hf_full_history':
        raise ValueError('run plan must be under runtime/hf_full_history for the private mount')
    inventory=json.loads(Path(plan_path).read_text())
    token=get_hf_token() or None
    def prepare(entry):
        local=hf_hub_download(inventory['dataset'],filename=entry['path'],repo_type='dataset',revision=inventory['revision'],token=token,cache_dir=root/'hf_cache')
        content=Path(local).read_bytes()
        if len(content)!=entry['bytes'] or (entry.get('sha256') and digest(content)!=entry['sha256']):
            raise ValueError('HF size/hash mismatch: '+entry['path'])
        if not entry.get('sha256') and entry.get('blob_id'):
            git_hash=hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest()
            if git_hash!=entry['blob_id']:
                raise ValueError('HF Git blob mismatch: '+entry['path'])
        metadata=stage_batch(root/'stage',inventory['dataset'],inventory['revision'],entry['path'],content)
        return metadata
    started=time.monotonic()
    all_metadata=[]
    for offset in range(0,len(inventory['files']),chunk_size):
        selected=inventory['files'][offset:offset+chunk_size]
        with ThreadPoolExecutor(max_workers=workers) as pool:
            metadata=list(pool.map(prepare,selected))
        all_metadata.extend(metadata)
        sources=[m['batch_id']+'/sources/'+inventory['revision']+'.json' for m in metadata]
        chunk_id=offset//chunk_size
        index=root/'chunks'/('%05d.json'%chunk_id)
        atomic_write(index,encoded(sources))
        receipts=[root/'stage'/m['batch_id']/'receipts'/(inventory['revision']+'.json') for m in metadata]
        if not all(path.exists() for path in receipts):
            command=['docker','compose','-f',str(ROOT/'docker-compose.hdfs.yml'),'--profile','import','run','--rm','--no-deps','history-import','python3','/workspace/scripts/hdfs_import_history.py','upload','--index','/import/chunks/'+index.name,'--workers',str(workers)]
            result=subprocess.run(command,capture_output=True,text=True,timeout=600)
            atomic_write(root/'logs'/('%05d.txt'%chunk_id),(result.stdout+result.stderr).encode())
            if result.returncode:
                raise RuntimeError('upload chunk failed; staging retained: '+str(root/'logs'/('%05d.txt'%chunk_id)))
        for m,path in zip(metadata,receipts):
            receipt=json.loads(path.read_text())
            if receipt.get('status')!='verified' or receipt['batch_id']!=m['batch_id'] or receipt['revision']!=inventory['revision'] or receipt['content_sha256']!=m['content_sha256']:
                raise ValueError('invalid chunk receipt')
        progress=dict(revision=inventory['revision'],completed=min(offset+chunk_size,len(inventory['files'])),total=len(inventory['files']),
                      verified_bytes=sum(m['bytes'] for m in all_metadata),total_bytes=inventory['total_bytes'],elapsed_seconds=round(time.monotonic()-started,1))
        atomic_write(root/'progress.json',encoded(progress))
        print('HISTORY_PROGRESS='+json.dumps(progress),flush=True)
    summary=dict(progress,dataset=inventory['dataset'],categories=inventory['categories'],status='all_planned_batches_received',
                 batch_ids=[m['batch_id'] for m in all_metadata],scope='HDFS Bronze only; no full Silver recomputation or model promotion')
    atomic_write(root/'complete.json',encoded(summary))
    print('HISTORY_COMPLETE='+json.dumps({k:v for k,v in summary.items() if k!='batch_ids'}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    inventory=sub.add_parser('plan')
    inventory.add_argument('--plan',type=Path,required=True)
    inventory.add_argument('--revision')
    execute=sub.add_parser('run')
    execute.add_argument('--plan',type=Path,required=True)
    execute.add_argument('--workers',type=int,default=4)
    execute.add_argument('--chunk-size',type=int,default=128)
    uploader=sub.add_parser('upload')
    uploader.add_argument('--index',type=Path,required=True)
    uploader.add_argument('--workers',type=int,default=4)
    args=parser.parse_args()
    if getattr(args,'workers',1)<1 or getattr(args,'chunk_size',1)<1:
        parser.error('worker/chunk limits must be positive')
    if args.command=='plan':
        plan(args.plan,args.revision)
    elif args.command=='upload':
        upload(args.index,args.workers)
    else:
        run(args.plan,args.workers,args.chunk_size)
