"""Controlled feature replay on recorded fleet observations; no source calls.

Comparison is a pilot sensitivity experiment, not a new model selection/test.
"""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import xgboost as xgb

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from evaluate_eta_candidate import fingerprint, metrics
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.data_access import DataAccess,IncidentsProvider
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.dto import BusVehicleDTO
from global_projection_reference import GlobalProjectionReference as OnlineFeatureExtractor
from module_3_bus_eta_prediction.step_3_3_machine_learning_models.eta_model_trainer import predict_eta_with_residual_model,apply_per_route_calibrator


def lag_features(ring,s,fallback):
    if not ring:return fallback,fallback,fallback,0.
    dt=ring[-1][0]-ring[-2][0] if len(ring)>1 else 0
    instant=min(80,max(0,(s-ring[-2][1])/dt*3.6)) if dt>0 else fallback
    def lag(n,minimum,default):
        ref=ring[max(0,len(ring)-1-n)];delta=ring[-1][0]-ref[0]
        return (min(80,max(0,(s-ref[1])/delta*3.6)) if delta>=minimum else default),delta
    roll3,_=lag(3,10,instant);roll5,dt5=lag(5,15,roll3)
    return instant,roll3,roll5,(roll3-roll5)/max(.5,dt5/60) if dt5>=15 else 0.


def compare(session,analysis,output):
    session,analysis,output=Path(session),Path(analysis),Path(output)
    if output.exists():raise ValueError('choose fresh output')
    labels={}
    for line in (analysis/'evaluated.jsonl').read_text().splitlines():
        row=json.loads(line);labels[(row['request_id'],row['vehicle'])]=row
    manifest=json.loads((session/'session.json').read_text(encoding='utf-8'))
    model_path=ROOT/'data/models/eta_xgb_global_full_54feat_r3_big.json';meta_path=ROOT/'data/models/eta_xgb_metadata_and_calibrator_r3_big.json'
    if (session/'artifact_bundle.json').is_file():
        bundle=json.loads((session/'artifact_bundle.json').read_text())['files']
        model_path=session/bundle['model']['path'];meta_path=session/bundle['metadata']['path']
    identity=manifest['health']['serving']['model']
    if fingerprint(model_path)!=identity['model_sha256'] or fingerprint(meta_path)!=identity['metadata_sha256']:
        raise ValueError('model identity changed')
    metadata=json.loads(meta_path.read_text());calibration={tuple(map(int,k.split('_'))):tuple(v) for k,v in metadata['calibrator'].items()}
    model=xgb.XGBRegressor(n_jobs=2);model.load_model(model_path);model.set_params(n_jobs=2)
    snapshot=session/'artifacts/serving.db'
    access=DataAccess(str(snapshot)) if snapshot.exists() else DataAccess()
    incident_root=session/'local_lakehouse' if (session/'local_inputs.json').exists() else None
    extractors={name:OnlineFeatureExtractor(access,IncidentsProvider(str(incident_root)) if incident_root else IncidentsProvider()) for name in ('time_windows','sample_lags')}
    lag=extractors['sample_lags']
    lag._speed_features=lambda route,direction,vehicle,s,fallback:lag_features(list(lag._obs.get((route,direction,vehicle),[])),s,fallback)
    records=defaultdict(list);actual=[];feature_mismatches=defaultdict(int);events=0
    for line in (session/'backend/trace.jsonl').read_text(encoding='utf-8').splitlines():
        row=json.loads(line)
        if row['kind']=='route_observation':
            events+=1;rid=row['route_id'];direction=row['direction'];now=row['query_epoch']
            vehicles=[BusVehicleDTO(**v) for v in row['vehicles']]
            for extractor in extractors.values():extractor.update_observation(rid,direction,vehicles,now)
            fleet=lag._fleet.get((rid,direction),{})
            corridor=access.get_corridor_stations(rid,'go' if direction==0 else 're')
            if len(corridor)>1:
                day,hour,*_=lag._calendar(now);base=access.get_route_profile(rid,'go' if direction==0 else 're')[0]
                baseline=lag._segment_array(rid,direction,corridor,day,hour,base,index=1)
                for bus in vehicles:
                    if bus.id not in fleet:continue
                    t,s,_,_=fleet[bus.id];_,speed,_,_=lag._speed_features(rid,direction,bus.id,s,bus.speed_kmh)
                    k=lag._current_segment_index([p[3] for p in corridor],s)
                    expected=(corridor[k+1][3]-corridor[k][3])/max(1,baseline[k])*3.6
                    fleet[bus.id]=(t,s,speed,min(3,max(.1,speed/max(3,expected))))
        elif row['kind']=='eta_result' and (row['request_id'],row['result']['vehicle_id']) in labels:
            key=(row['request_id'],row['result']['vehicle_id']);label=labels[key]
            vehicle=BusVehicleDTO(**row['vehicle'])
            if not extractors['time_windows']._obs.get((row['route_id'],row['direction'],vehicle.id)):continue
            actual.append(label['actual_eta_sec'])
            for name,extractor in extractors.items():
                features=extractor.build_features(row['route_id'],row['direction'],vehicle,row['station_order'],row['s_target_m'],row['s_bus_m'],row['query_epoch'])
                records[name].append(features)
                if name=='time_windows':
                    for column,value in row['features'].items():
                        if not np.isclose(value,features[column],rtol=1e-5,atol=.05):feature_mismatches[column]+=1
    if not events or not actual:raise ValueError('session lacks full fleet observation trace or usable labels')
    result=dict(rows=len(actual),fleet_observations=events,time_window_replay_feature_mismatches=dict(feature_mismatches),
                session_sha256=fingerprint(session/'session.json'),labels_sha256=fingerprint(analysis/'evaluated.jsonl'),
                model_sha256=identity['model_sha256'],replay_source_sha256=fingerprint(Path(__file__)),
                comparison={},scope='controlled fleet replay; pilot sensitivity, not independent model selection',
                caveat='feature mismatches with observed API must be inspected before treating replay as exact')
    for name,features in records.items():
        frame=pd.DataFrame(features)
        for c in ('route_id_idx','direction_id','day_type','hour_slot'):frame[c]=frame[c].astype('int32')
        predictions=apply_per_route_calibrator(frame,predict_eta_with_residual_model(model,frame,model.get_booster().feature_names),calibration)
        result['comparison'][name]=metrics(actual,predictions)
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--session',type=Path,required=True)
    parser.add_argument('--analysis',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(compare(args.session,args.analysis,args.output)))
