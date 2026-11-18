"""Replay recorded merged GPS through installed service + HTTP, without network.

Only upstream transport and wall clock are replaced. Matcher, macro speed,
features, station filtering, model and HTTP serialization are production code.
This does not validate the upstream merge itself or provide new live evidence.
"""
import argparse
from collections import defaultdict,Counter
from datetime import datetime
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

from fastapi.testclient import TestClient

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation import serving_service as serving
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.dto import BusVehicleDTO,RouteLiveResponse
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.data_access import IncidentsProvider
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.model_runtime import ModelRuntime
from experiments.timbus.timbus_tracker import TimBusClient
from evaluate_eta_candidate import fingerprint


def rows(path):
    with path.open(encoding='utf-8') as f:
        for line in f:yield json.loads(line)


def run(session,output):
    if output.exists():raise ValueError('choose fresh output')
    output.mkdir(parents=True)
    events=[]
    for r in rows(session/'backend/trace.jsonl'):
        if r['kind']=='route_observation':events.append((datetime.fromisoformat(r['recorded_at']).timestamp(),0,r))
    for r in rows(session/'http.jsonl'):
        if r['endpoint']=='station-eta' and r['status']==200:events.append((datetime.fromisoformat(r['received_at']).timestamp(),1,r))
    events.sort(key=lambda x:(x[0],x[1]));clock=[events[0][0]]
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls,tz=None):return datetime.fromtimestamp(clock[0],tz)
    svc=serving.BusMapServingService(db_path=str(session/'artifacts/serving.db'))
    svc._incidents=IncidentsProvider(str(session/'local_lakehouse'));svc._extractor._incidents=svc._incidents
    svc._runtime=ModelRuntime.load(str(session/'artifacts/model.json'),str(session/'artifacts/metadata.json'))
    manifest=json.loads((session/'session.json').read_text(encoding='utf-8'))
    assert svc._runtime.identity['model_sha256']==manifest['health']['serving']['model']['model_sha256']
    latest={};counts=Counter();trace=[];generations={};resets=[];missing=Counter()
    def live(route_id,direction=0):
        vs=latest.get((route_id,direction),[])
        return RouteLiveResponse(route_id=route_id,direction=direction,timestamp=FrozenDateTime.now(serving.TZ_HANOI).isoformat(),count=len(vs),vehicles=vs)
    def cache_transport(cls,**kwargs):
        counts['timbus_cache_misses_without_network']+=1
        return {}
    from module_3_bus_eta_prediction.step_3_5_web_demo import app as web
    with patch.object(serving,'datetime',FrozenDateTime),patch.object(serving,'fetch_live_vehicles_for_route',live),patch.object(TimBusClient,'query_central_vehicles',classmethod(cache_transport)),patch.object(web,'service',svc),patch.dict(os.environ,{'ETA_TRACE_DIR':'','ETA_UPSTREAM_RAW_DIR':''}),TestClient(web.app) as client:
        with (output/'responses.jsonl').open('w',encoding='utf-8') as stream:
            for received,kind,r in events:
                clock[0]=received
                if kind==0:
                    rid,direction=r['route_id'],r['direction'];now=r['query_epoch']
                    vs=[BusVehicleDTO(**v) for v in r['vehicles']]
                    # Keep every recorded vehicle, including unmatched ones. The
                    # installed producer decides filtering, not this replay.
                    latest[(rid,direction)]=vs
                    shape=svc._get_shape_model(rid,'go' if direction==0 else 're')
                    stabilized=svc._apply_macro_speeds(rid,direction,'go' if direction==0 else 're',{},vs,shape,now)
                    svc._extractor.update_observation(rid,direction,stabilized,now)
                    with svc._tb_lock:
                        for v in stabilized:
                            if v.telemetry_source=='timbus':
                                t,_=serving.parse_ping_epoch(v.updated_at,now)
                                svc._tb_last_valid[(rid,direction,TimBusClient.normalize_plate(v.plate))]=(t,v.matched_projection[0],v)
                    counts['fleet_snapshots']+=1
                    for v in vs:
                        prepared=svc._extractor.project_vehicle(rid,direction,v,now)
                        identity=(rid,v.id)
                        if prepared.projection_generation!=generations.get(identity,0):
                            resets.append(dict(route=rid,vehicle=v.id,direction=direction,epoch=now,status=prepared.projection_status,generation=prepared.projection_generation))
                        generations[identity]=prepared.projection_generation
                        if v.id==8837137 and direction==1:
                            trace.append(dict(vehicle=v.id,epoch=min(serving.parse_ping_epoch(v.updated_at,now)[0],now),
                                              projection=prepared.matched_projection,status=prepared.projection_status,
                                              generation=prepared.projection_generation))
                else:
                    body=r['body'];clock[0]=datetime.fromisoformat(body['query_time']).timestamp()
                    response=client.get('/api/station-eta',params=r['params'])
                    assert response.status_code==200,(r['request_id'],response.text)
                    new=response.json();counts['http_requests']+=1
                    counts['original_forecasts']+=len(body['buses']);counts['installed_forecasts']+=len(new['buses'])
                    for bus in new['buses']:counts[bus['prediction_source']]+=1
                    previous_ids={b['vehicle_id'] for b in body['buses']};current_ids={b['vehicle_id'] for b in new['buses']}
                    counts['new_forecast_entries']+=len(current_ids-previous_ids)
                    counts['removed_forecast_entries']+=len(previous_ids-current_ids)
                    for vid in previous_ids-current_ids:
                        rid=body['route_id'];direction=body['direction'];state=svc._extractor._matched.get((rid,direction,vid))
                        reason=state[1]['projection_status'] if state else 'no_current_match'
                        if state and state[1]['matched_projection'] and state[1]['matched_projection'][0]>body['target_station']['cum_distance_m']:reason='passed_station'
                        missing[reason]+=1
                    stream.write(json.dumps(dict(original_request_id=r['request_id'],params=r['params'],original=body,installed=new),ensure_ascii=False)+'\n')
    case=[]
    for r in rows(output/'responses.jsonl'):
        if r['params']['route']=='27' and r['params']['station_order']==23:
            for b in r['installed']['buses']:
                if b['vehicle_id']==8837283:case.append(dict(epoch=datetime.fromisoformat(r['installed']['query_time']).timestamp(),eta=b['eta_seconds'],request=r['original_request_id']))
    after=[r for r in case if r['epoch']>=1794918060]
    jumps=[b['eta']-a['eta'] for a,b in zip(after,after[1:])]
    before=[r for r in case if r['request']=='566b878c-df71-476d-a33f-a922bda9b82a']
    next_=[r for r in case if r['request']=='51de6d7a-d5f3-4167-8f75-39387e9ffded']
    assert before and next_,'known case disappeared instead of being repaired'
    assert max(jumps)<30,('known-case jump persists',max(jumps))
    reset_log={str(k):dict(reason=e.reason,resets=e.resets,awaiting_direction=e.awaiting_direction) for k,e in svc._extractor._matchers.items() if e.resets or e.awaiting_direction}
    result=dict(scope='recorded merged-GPS boundary replay through installed HTTP; no upstream network, not a new live session',counts=dict(counts),
                known_case_pair_delta_sec=next_[0]['eta']-before[0]['eta'],known_case_forecasts_after_event=len(after),known_case_max_jump_after_event=max(jumps),
                lifecycle=reset_log,resets=resets,removed_forecast_reasons=dict(missing),sources={str(p):fingerprint(p) for p in [Path(__file__),session/'http.jsonl',session/'backend/trace.jsonl',ROOT/'module_1_data_ingestion_and_preprocessing/step_1_4_frenet_spatial_projection/route_matcher.py',ROOT/'module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/serving_service.py',ROOT/'module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/online_features.py']})
    (output/'report.json').write_text(json.dumps(result,indent=2),encoding='utf-8');(output/'lead_trace.json').write_text(json.dumps(trace,indent=2),encoding='utf-8')
    print(json.dumps(result))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--session',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();run(a.session,a.output)
