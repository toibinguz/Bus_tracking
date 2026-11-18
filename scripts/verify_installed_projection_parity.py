"""Exact offline/serving parity on the same normalized recorded GPS stream."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from module_1_data_ingestion_and_preprocessing.step_1_4_frenet_spatial_projection.multi_route_projector import project_points_to_shape
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.online_features import OnlineFeatureExtractor
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.data_access import DataAccess
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.dto import BusVehicleDTO
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.live_feed import parse_ping_epoch
from evaluate_eta_candidate import fingerprint


def run(session,output):
    if output.exists():raise ValueError('choose fresh output')
    access=DataAccess(str(session/'artifacts/serving.db'));ex=OnlineFeatureExtractor(access)
    streams=defaultdict(list);last={};index=0;ignored=0
    with (session/'backend/trace.jsonl').open(encoding='utf-8') as file:
        for line in file:
            r=json.loads(line)
            if r['kind']!='route_observation':continue
            for raw in r['vehicles']:
                epoch,_=parse_ping_epoch(raw['updated_at'],r['query_epoch']);epoch=min(epoch,r['query_epoch'])
                key=(r['route_id'],raw['id'])
                if epoch<=last.get(key,float('-inf')):ignored+=1;continue
                last[key]=epoch
                streams[key].append((index,r['direction'],epoch,BusVehicleDTO(**raw)));index+=1
    records=[];runs=0;resets=0
    for (route,vid),items in streams.items():
        groups=[]
        for item in items:
            if not groups or groups[-1][0]!=item[1]:groups.append((item[1],[]))
            groups[-1][1].append(item)
        for direction,group in groups:
            runs+=1
            shape=access.get_shape_points(route,'go' if direction==0 else 're')
            expected={i:(s,ct) for i,s,ct in project_points_to_shape([(i,v.lat,v.lng,t) for i,d,t,v in group],shape)}
            for i,d,t,v in group:
                matched=ex.project_vehicle(route,d,v,t)
                actual=matched.matched_projection[:2] if matched.matched_projection else None
                assert actual==expected.get(i),(route,vid,i,actual,expected.get(i))
                records.append(dict(route=route,vehicle=vid,direction=d,epoch=t,projection=actual,status=matched.projection_status))
    result=dict(scope='exact same normalized arrival-ordered GPS and contiguous direction runs; tests shared projection, not source direction normalization',
                observations=index,vehicle_streams=len(streams),direction_runs=runs,duplicate_or_late_ignored=ignored,
                matched=sum(r['projection'] is not None for r in records),mismatches=0,
                direction_pending=sum(r['status']=='direction_change_pending' for r in records),
                sources={str(p):fingerprint(p) for p in [Path(__file__),session/'backend/trace.jsonl',ROOT/'module_1_data_ingestion_and_preprocessing/step_1_4_frenet_spatial_projection/route_matcher.py',ROOT/'module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/online_features.py']})
    output.write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--session',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();run(a.session,a.output)
