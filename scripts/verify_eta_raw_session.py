"""Verify every retained byte object and independently decode TimBus captures."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from experiments.timbus.timbus_tracker import TimBusClient


def verify(session,require_upstream=False):
    session=Path(session).resolve();manifest=json.loads((session/'session.json').read_text(encoding='utf-8'))
    requests={};http_raw=0;objects=set();upstreams=Counter();decoded=0;uncorrelated=0
    def read(root,reference):
        path=(root/reference['path']).resolve()
        if root not in path.parents:raise ValueError('capture path escapes session')
        content=path.read_bytes()
        if len(content)!=reference['bytes'] or hashlib.sha256(content).hexdigest()!=reference['sha256']:
            raise ValueError('raw object was modified: '+str(path))
        objects.add(str(path))
        return content
    for line in (session/'http.jsonl').read_text(encoding='utf-8').splitlines():
        row=json.loads(line)
        if row.get('request_id'):requests[row['request_id']]=row
        if row.get('raw_response'):
            raw=read(session,row['raw_response']);http_raw+=1
            if row['error'] is None and json.loads(raw)!=row['body']:raise ValueError('HTTP parsed body differs from raw bytes')
    index=session/'upstream/index.jsonl'
    if require_upstream and not index.is_file():raise ValueError('no upstream capture')
    if index.is_file():
        for line in index.read_text(encoding='utf-8').splitlines():
            row=json.loads(line);upstreams[row['source']]+=1
            if row.get('http_request_id') not in requests:uncorrelated+=1
            payloads={key:read(session/'upstream',value) for key,value in row['files'].items()}
            if row['source']=='busmap' and row['status']==200 and row['error'] is None:json.loads(payloads['response'])
            if row['source']=='timbus' and 'decoded_response' in payloads:
                actual=TimBusClient.decrypt_packet(payloads['response'].decode('utf-8'))
                if actual!=payloads['decoded_response']:raise ValueError('TimBus decoded bytes differ')
                TimBusClient.parse_bus_packet(actual,direction_fallback=row['params']['direction'])
                decoded+=1
    for relative,want in manifest['code'].items():
        frozen=session/'code'/relative
        if not frozen.is_file() or hashlib.sha256(frozen.read_bytes()).hexdigest()!=want:
            raise ValueError('frozen source missing/modified: '+relative)
    bundle=session/'artifact_bundle.json'
    if bundle.is_file():
        for reference in json.loads(bundle.read_text())['files'].values():read(session,reference)
    local_inputs=session/'local_inputs.json'
    if local_inputs.is_file():
        for relative,want in json.loads(local_inputs.read_text())['files'].items():
            path=session/relative
            read(session,dict(path=relative,sha256=want,bytes=path.stat().st_size))
    if require_upstream and (not http_raw or not upstreams['busmap'] or not upstreams['timbus'] or uncorrelated):
        raise ValueError('incomplete upstream/HTTP correlation')
    return dict(http_requests_with_ids=len(requests),http_raw_responses=http_raw,unique_byte_objects=len(objects),
                upstream_exchanges=dict(upstreams),timbus_decodes_verified=decoded,
                uncorrelated_upstreams=uncorrelated,frozen_source_files=len(manifest['code']),
                storage='all original objects retained; no sampling or deletion',
                legacy_http_parsed_only=not bool(http_raw),upstream_required=require_upstream)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--session',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--require-upstream',action='store_true')
    args=parser.parse_args()
    if args.output.exists():parser.error('choose fresh verification output')
    result=verify(args.session,args.require_upstream)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))
