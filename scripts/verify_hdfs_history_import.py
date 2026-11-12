"""Read every planned HDFS batch and compare byte hashes plus receive lineage."""
from concurrent.futures import ThreadPoolExecutor,as_completed
import json
import hashlib
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from module_2_big_data_storage_and_lakehouse.step_2_4_hdfs_history.artifact_transport import PrivateWebHdfs
from module_2_big_data_storage_and_lakehouse.step_2_4_hdfs_history.hf_bronze import atomic_write,digest,encoded,LEDGER_ROOT


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',type=Path,required=True)
    parser.add_argument('--workers',type=int,default=8)
    args=parser.parse_args()
    inventory=json.loads(args.plan.read_text())
    root=args.plan.parent
    by_path={}
    for source in (root/'stage').glob('*/sources/'+inventory['revision']+'.json'):
        metadata=json.loads(source.read_text())
        if metadata['dataset']!=inventory['dataset']:
            continue
        if metadata['path'] in by_path:
            raise ValueError('duplicate source descriptor')
        by_path[metadata['path']]=metadata
    if {entry['path'] for entry in inventory['files']}!=set(by_path):
        raise ValueError('planned and staged path sets differ')
    store=PrivateWebHdfs()
    def verify(entry):
        metadata=by_path[entry['path']]
        content=store.read(metadata['hdfs_raw_path'])
        if len(content)!=entry['bytes'] or digest(content)!=metadata['content_sha256']:
            raise ValueError('HDFS bytes differ: '+entry['path'])
        if entry.get('sha256'):
            if digest(content)!=entry['sha256']:
                raise ValueError('HDFS/source LFS hash differs')
        elif entry.get('blob_id'):
            if hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest()!=entry['blob_id']:
                raise ValueError('HDFS/source Git blob differs')
        else:
            raise ValueError('source digest missing in plan')
        ledger=LEDGER_ROOT+'/'+metadata['batch_id']
        manifest=json.loads(store.read(ledger+'/manifest.json'))
        if {k:manifest[k] for k in metadata if k!='revision'}!={k:v for k,v in metadata.items() if k!='revision'}:
            raise ValueError('manifest differs: '+entry['path'])
        if json.loads(store.read(ledger+'/revisions/'+inventory['revision']+'.json'))!=metadata:
            raise ValueError('revision lineage differs')
        return len(content)
    started=time.monotonic()
    completed,total_bytes=0,0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures=[pool.submit(verify,entry) for entry in inventory['files']]
        for future in as_completed(futures):
            total_bytes+=future.result()
            completed+=1
            if completed%128==0:
                progress=dict(completed=completed,total=len(futures),verified_bytes=total_bytes)
                atomic_write(root/'verification_progress.json',encoded(progress))
                print('VERIFY_PROGRESS='+json.dumps(progress),flush=True)
    if total_bytes!=inventory['total_bytes']:
        raise ValueError('total byte count mismatch')
    objects={metadata['hdfs_raw_path']:metadata['bytes'] for metadata in by_path.values()}
    result=dict(status='verified_all_remote_bytes_and_lineage',dataset=inventory['dataset'],revision=inventory['revision'],
                files=completed,categories=inventory['categories'],logical_bytes=total_bytes,unique_raw_objects=len(objects),
                unique_raw_bytes=sum(objects.values()),source_digest_verified=True,elapsed_seconds=round(time.monotonic()-started,1),scope='Bronze raw history only')
    atomic_write(root/'verification.json',encoded(result))
    print('HISTORY_VERIFIED='+json.dumps(result),flush=True)


if __name__=='__main__':
    main()
