"""Bounded client collection of the same HTTP surface used by the demo FE."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def utc():
    return datetime.now(timezone.utc).isoformat()


def collect(base_url, output, seconds, routes, direction=0, orders=(8,13,18,23)):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    if (output/'http.jsonl').exists():
        raise ValueError('choose fresh collection output')
    lock = threading.Lock()
    counts = dict(requests=0, errors=0, vehicle_observations=0, eta_forecasts=0)

    def request(endpoint, **params):
        sent, start = utc(), time.monotonic()
        status, body, error, server_id = None, None, None, None
        raw_reference=None;response_headers={}
        url = base_url.rstrip('/')+'/api/'+endpoint+('?' + urlencode(params) if params else '')
        try:
            try:
                reply = urlopen(url, timeout=45)
            except HTTPError as response:
                reply = response
            with reply:
                status = reply.status
                server_id = reply.headers.get('X-Request-ID')
                raw_bytes=reply.read()
                response_headers={k:v for k,v in reply.headers.items() if k.lower()!='set-cookie'}
                sha=hashlib.sha256(raw_bytes).hexdigest()
                raw_path=output/'http_objects'/(sha+'.bin')
                with lock:
                    raw_path.parent.mkdir(parents=True,exist_ok=True)
                    if not raw_path.exists():raw_path.write_bytes(raw_bytes)
                raw_reference=dict(path=raw_path.relative_to(output).as_posix(),sha256=sha,bytes=len(raw_bytes))
                raw = raw_bytes.decode('utf-8')
                try:
                    body = json.loads(raw)
                except ValueError:
                    error = 'invalid_json'
                    body = raw
        except (OSError, URLError) as exc:
            error = type(exc).__name__+': '+str(exc)
        row = dict(sent_at=sent,received_at=utc(),elapsed_sec=time.monotonic()-start,
                   method='GET',url=url,endpoint=endpoint,params=params,status=status,request_id=server_id,
                   response_headers=response_headers,raw_response=raw_reference,body=body,error=error)
        with lock:
            with (output/'http.jsonl').open('a',encoding='utf-8') as stream:
                stream.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n')
            counts['requests'] += 1
            counts['errors'] += int(error is not None or status != 200)
            if isinstance(body,dict):
                counts['vehicle_observations'] += len(body.get('vehicles',[]))
                counts['eta_forecasts'] += len(body.get('buses',[]))
        return body if status==200 and isinstance(body,(dict,list)) else None

    health = request('health')
    if not health or 'serving' not in health:
        raise ValueError('server must expose serving identity; refuse unversioned collection')
    catalog = request('routes')
    if not isinstance(catalog,list):
        raise ValueError('no route catalog')
    selected = []
    for route in routes:
        item = next((r for r in catalog if r['route_no']==route),None)
        if item is None:
            raise ValueError('unknown route '+route)
        shape = request('route-shape',route=route,direction=direction)
        stations = request('route-stations',route=route,direction=direction)
        if not shape or not stations:
            raise ValueError('missing geometry for '+route)
        valid = [n for n in orders if 0<n<len(stations['stations'])]
        selected.append(dict(route=route,route_id=item['route_id'],direction=direction,orders=valid,
                             shape=shape,stations=stations))
    code = {}
    upstream=ROOT/'module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay'
    source_files=list((ROOT/'module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation').glob('*.py')) + [
        ROOT/'module_3_bus_eta_prediction/step_3_5_web_demo/app.py',Path(__file__),
        ROOT/'module_3_bus_eta_prediction/step_3_3_machine_learning_models/eta_model_trainer.py',
        upstream/'upstream_capture.py',upstream/'catalog_refresher.py',
        ROOT/'experiments/timbus/timbus_tracker.py',ROOT/'config/system_config.py']
    for path in source_files:
        code[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
        frozen = output/'code'/path.relative_to(ROOT)
        frozen.parent.mkdir(parents=True,exist_ok=True)
        frozen.write_bytes(path.read_bytes())
    commit = subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    manifest = dict(schema_version='eta-http-session.v1',started_at=utc(),base_url=base_url,seconds=seconds,
                    health=health,selected=selected,code=code,git_commit=commit,
                    working_tree_dirty=bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT)),
                    ground_truth_protocol=dict(method='last_before_first_after_station',max_gap_sec=40,
                                               reset_backwards_m=150,arrival_is_gps_estimate=True),
                    limitation='observed HTTP responses; upstream packets are not implicitly captured')
    (output/'session.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    from freeze_eta_session_artifacts import freeze
    freeze(output)
    deadline = time.monotonic()+seconds

    def poll(selection):
        while time.monotonic()<deadline:
            cycle = time.monotonic()
            live = request('live-vehicles',route=selection['route'],direction=direction)
            for order in selection['orders']:
                if time.monotonic()>=deadline:
                    break
                request('station-eta',route=selection['route'],direction=direction,station_order=order)
            interval = 15
            if isinstance(live,dict):
                interval = max(5,float(live.get('poll_interval_sec',15)))
            time.sleep(min(max(0,cycle+interval-time.monotonic()), max(0,deadline-time.monotonic())))

    with ThreadPoolExecutor(max_workers=len(selected)) as pool:
        list(pool.map(poll, selected))
    final_health = request('health')
    if final_health != health:
        raise ValueError('server identity changed during collection')
    summary = dict(ended_at=utc(),**counts)
    (output/'collection.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    return summary


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--seconds',type=int,default=1800)
    parser.add_argument('--routes',nargs='+',default=['02','27'])
    parser.add_argument('--direction',type=int,choices=[0,1],default=0)
    args = parser.parse_args()
    if args.seconds<=0: parser.error('seconds must be positive')
    print(json.dumps(collect(args.url,args.output,args.seconds,args.routes,args.direction)))
