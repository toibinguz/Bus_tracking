"""Own an isolated local demo process for a bounded observed HTTP collection."""
import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

from collect_eta_live import collect

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--seconds',type=int,default=1800)
    parser.add_argument('--routes',nargs='+',default=['02','27'])
    parser.add_argument('--direction',type=int,choices=[0,1],default=0)
    args=parser.parse_args()
    if os.name!='nt' or args.seconds<=0 or args.output.exists():
        parser.error('requires Windows, positive seconds and a fresh output directory')
    args.output.mkdir(parents=True)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
    env=dict(os.environ)
    env.pop('ETA_RELEASE_POINTER',None)
    env['ETA_TRACE_DIR']=str((args.output/'backend').resolve())
    env['ETA_UPSTREAM_RAW_DIR']=str((args.output/'upstream').resolve())
    command=[sys.executable,'-m','uvicorn','module_3_bus_eta_prediction.step_3_5_web_demo.app:app',
             '--host','127.0.0.1','--port',str(port)]
    with (args.output/'server.log').open('wb') as log:
        process=subprocess.Popen(command,cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=log,
                                 stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        try:
            base=f'http://127.0.0.1:{port}'
            deadline=time.monotonic()+60
            while time.monotonic()<deadline:
                try:
                    with urlopen(base+'/api/health',timeout=1) as reply: json.load(reply)
                    break
                except OSError:
                    if process.poll() is not None: raise RuntimeError('demo startup failed')
                    time.sleep(.25)
            else: raise RuntimeError('demo startup timed out')
            print('COLLECTION_STARTED='+str(args.output.resolve()),flush=True)
            print(json.dumps(collect(base,args.output,args.seconds,args.routes,args.direction)),flush=True)
        finally:
            if process.poll() is None:
                process.send_signal(signal.CTRL_BREAK_EVENT)
                try: process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True)
                    process.wait(timeout=10)


if __name__=='__main__': main()
