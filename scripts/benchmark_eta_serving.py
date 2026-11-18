"""TCP benchmark with a frozen observed GPS fixture, no upstream traffic."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import time
from urllib.request import urlopen

import numpy as np
import psutil

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def serve(session,port):
    from module_3_bus_eta_prediction.step_3_5_web_demo import app as web
    from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation import serving_service as serving
    from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.dto import RouteLiveResponse
    fixture=None
    for line in (session/'http.jsonl').read_text(encoding='utf-8').splitlines():
        row=json.loads(line)
        if row['endpoint']=='live-vehicles' and row['params']['route']=='02' and row['body'].get('count',0)>0:
            fixture=row;break
    if fixture is None:raise ValueError('fixture lacks route02 GPS')
    payload=RouteLiveResponse(**fixture['body'])
    now=datetime.fromisoformat(fixture['received_at']).timestamp()
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return datetime.fromtimestamp(now,tz=tz)
    serving.datetime=Clock
    serving.fetch_live_vehicles_for_route=lambda **kwargs:payload
    web.service._da._timbus_anchors={}
    web.service.source_info['telemetry_mode']='replayed_observed_fixture_no_upstream_calls'
    import uvicorn
    uvicorn.run(web.app,host='127.0.0.1',port=port,log_level='warning')


def benchmark(session,output,pointer=None,rounds=3):
    if output.exists():raise ValueError('choose fresh output')
    output.mkdir(parents=True);rows=[];peaks=[];starts=[];lock=threading.Lock()
    for run in range(rounds):
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        env=dict(os.environ)
        for key in ('ETA_RELEASE_POINTER','ETA_TRACE_DIR','ETA_UPSTREAM_RAW_DIR'):env.pop(key,None)
        if pointer:env['ETA_RELEASE_POINTER']=str(pointer.resolve())
        command=[sys.executable,str(Path(__file__).resolve()),'--serve','--session',str(session.resolve()),'--port',str(port)]
        with (output/f'server-{run}.log').open('wb') as log:
            started=time.monotonic();process=subprocess.Popen(command,cwd=ROOT,env=env,stdin=subprocess.DEVNULL,
                stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
            stop=threading.Event();peak=[0]
            def monitor():
                while not stop.wait(.1):
                    try:
                        root=psutil.Process(process.pid)
                        peak[0]=max(peak[0],sum(p.memory_info().rss for p in [root]+root.children(recursive=True) if p.is_running()))
                    except psutil.Error:pass
            thread=threading.Thread(target=monitor,daemon=True);thread.start()
            try:
                deadline=time.monotonic()+60
                while time.monotonic()<deadline:
                    try:
                        with urlopen(f'http://127.0.0.1:{port}/api/health',timeout=1) as reply:health=json.load(reply)
                        break
                    except OSError:
                        if process.poll() is not None:raise RuntimeError('fixture server exited')
                        time.sleep(.1)
                else:raise RuntimeError('fixture server startup timed out')
                starts.append(time.monotonic()-started)
                def request(kind):
                    t=time.monotonic()
                    with urlopen(f'http://127.0.0.1:{port}/api/station-eta?route=02&direction=0&station_order=13',timeout=30) as response:
                        raw=response.read();body=json.loads(raw)
                        row=dict(run=run,kind=kind,status=response.status,elapsed_sec=time.monotonic()-t,
                                 raw_body=raw.decode('utf-8'),raw_sha256=hashlib.sha256(raw).hexdigest(),
                                 headers=dict(response.headers),forecasts=body['approaching_count'])
                    with lock:rows.append(row)
                request('cold_eta')
                for _ in range(15):request('warm_sequential')
                with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(request,['warm_concurrent4']*20))
            finally:
                if process.poll() is None:
                    process.send_signal(signal.CTRL_BREAK_EVENT)
                    try:process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True);process.wait(timeout=10)
                stop.set();thread.join(timeout=2);peaks.append(peak[0])
    stats={}
    for kind in ('cold_eta','warm_sequential','warm_concurrent4'):
        chosen=[r for r in rows if r['kind']==kind];values=[r['elapsed_sec'] for r in chosen]
        stats[kind]=dict(n=len(chosen),p50_sec=float(np.median(values)),p95_sec=float(np.quantile(values,.95)),
                         max_sec=max(values),zero_forecast_responses=sum(r['forecasts']==0 for r in chosen))
    with (output/'responses.jsonl').open('w',encoding='utf-8') as stream:
        for row in rows:stream.write(json.dumps(row,ensure_ascii=False)+'\n')
    result=dict(rounds=rounds,startup_sec=starts,peak_process_tree_rss_bytes=peaks,metrics=stats,
                source=health['serving'],scope='real localhost TCP, fixed observed GPS fixture; no upstream calls; summed RSS is not physical RAM',
                limitation='3 cold starts are descriptive only; no claim about Internet GPS latency or multi-machine capacity')
    (output/'report.json').write_text(json.dumps(result,indent=2),encoding='utf-8');return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--session',type=Path,required=True)
    parser.add_argument('--output',type=Path);parser.add_argument('--pointer',type=Path);parser.add_argument('--rounds',type=int,default=3)
    parser.add_argument('--serve',action='store_true');parser.add_argument('--port',type=int)
    args=parser.parse_args()
    if args.serve:serve(args.session,args.port)
    elif args.output and args.rounds>0:print(json.dumps(benchmark(args.session,args.output,args.pointer,args.rounds)))
    else:parser.error('positive rounds and output required')
