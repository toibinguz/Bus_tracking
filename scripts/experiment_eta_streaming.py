"""Experimental feature replay only: compare motion projection and reset fallback.

Never installs a serving patch. Labels stay frozen, even when projection changes;
resulting accuracy is a sensitivity diagnostic, not independent acceptance.
"""
import argparse
from collections import Counter, defaultdict
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
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.live_feed import parse_ping_epoch
from module_3_bus_eta_prediction.step_3_3_machine_learning_models.eta_model_trainer import predict_eta_with_residual_model,apply_per_route_calibrator


def motion_projection(shape,lat,lng,previous,epoch,slack=10.):
    original=shape.project_point(lat,lng)
    if previous is None:return original
    t,old_lat,old_lng,old_projection=previous
    dt=epoch-t
    if dt<=0:return old_projection
    mx=(lng-old_lng)*shape.kx;my=(lat-old_lat)*shape.ky;distance=float(np.hypot(mx,my))
    if dt>30:return original
    px,py=lng*shape.kx,lat*shape.ky
    u=np.clip(((px-shape._x1)*shape._dx+(py-shape._y1)*shape._dy)/shape._safe_lens_sq,0,1)
    ct=np.hypot(px-shape._x1-u*shape._dx,py-shape._y1-u*shape._dy)
    if distance<8:
        # Small displacement cannot establish heading; retain the previous branch
        # only while it remains a spatially plausible candidate.
        i=old_projection[2]
        if ct[i]<=ct.min()+slack:
            s=float(shape._cum_starts[i]+u[i]*shape._seg_lens[i])
            return round(min(shape._total_len,max(0,s)),1),round(float(ct[i]),1),i
        return original
    cos=(mx*shape._dx+my*shape._dy)/(max(distance,1e-9)*np.maximum(shape._seg_lens,1e-9))
    valid=np.flatnonzero((ct<=ct.min()+slack)&(cos>=.5))
    if not len(valid):return original
    i=int(valid[np.argmin(ct[valid])]);s=float(shape._cum_starts[i]+u[i]*shape._seg_lens[i])
    return round(min(shape._total_len,max(0,s)),1),round(float(ct[i]),1),i


class PreparedShape:
    def __init__(self,base):self.base=base;self.resolved={}
    def project_point(self,lat,lng):return self.resolved.get((lat,lng),self.base.project_point(lat,lng))
    def __getattr__(self,key):return getattr(self.base,key)


class ExperimentalExtractor(OnlineFeatureExtractor):
    def __init__(self,*args,motion=False,carry=False,drop_unique=False,**kwargs):
        super().__init__(*args,**kwargs);self.motion=motion;self.carry=carry
        self.prior={};self.held={};self.stats=Counter();self.now=0
        self.drop_unique=drop_unique;self.seen_packets=set();self.delivered={}
    def update_observation(self,route,direction,vehicles,now):
        self.now=now;ds='go' if direction==0 else 're'
        if self.drop_unique:
            kept=[]
            for v in vehicles:
                key=(route,direction,v.id);packet=(*key,v.updated_at)
                if packet not in self.seen_packets:
                    self.seen_packets.add(packet);self.stats['unique_packets']+=1
                    # Seed each new vehicle before fault injection, rather than
                    # silently reading an unavailable packet at prediction time.
                    if self.stats['unique_packets']%5 or key not in self.delivered:
                        self.delivered[key]=v
                    else:self.stats['dropped_unique_packets']+=1
                if key in self.delivered:kept.append(self.delivered[key])
            vehicles=kept
        shape=self._get_shape_model(route,ds)
        if self.motion and shape is not None:
            if not isinstance(shape,PreparedShape):
                shape=PreparedShape(shape);self._shape_models[(route,ds)]=shape
            for v in vehicles:
                key=(route,direction,v.id);t,_=parse_ping_epoch(v.updated_at,now);t=min(now,t)
                old=self.prior.get(key)
                if old and t<=old[0]:
                    projection=old[3];self.stats['duplicate_or_late']+=1
                else:
                    projection=motion_projection(shape.base,v.lat,v.lng,old,t)
                    if projection!=shape.base.project_point(v.lat,v.lng):self.stats['projection_changed']+=1
                    self.prior[key]=(t,v.lat,v.lng,projection)
                shape.resolved[(v.lat,v.lng)]=projection
        old={v.id:(list(self._obs.get((route,direction,v.id),[])),self._fleet.get((route,direction),{}).get(v.id)) for v in vehicles}
        super().update_observation(route,direction,vehicles,now)
        for v in vehicles:
            key=(route,direction,v.id);ring=self._obs.get(key,[]);before,fleet=old[v.id]
            reset=bool(before and ring and len(ring)==1 and ring[-1][1]<before[-1][1]-50)
            if reset:
                self.stats['backward_resets']+=1
                if self.carry and fleet:self.held[key]=(now,float(fleet[2]))
            if self.carry and key in self.held:
                start,speed=self.held[key]
                span=ring[-1][0]-ring[0][0] if ring else 0
                if now-start>30 or span>=10:self.held.pop(key)
                else:
                    current=self._fleet[(route,direction)].get(v.id)
                    if current:
                        _,s,_,ratio=current
                        corridor=self._da.get_corridor_stations(route,ds)
                        day,hour,*_=self._calendar(now);profile=self._da.get_route_profile(route,ds)[0]
                        tt=self._segment_array(route,direction,corridor,day,hour,profile,index=1)
                        k=self._current_segment_index([r[3] for r in corridor],s)
                        baseline_speed=max(1,corridor[k+1][3]-corridor[k][3])/max(1,tt[k])*3.6
                        self._fleet[(route,direction)][v.id]=(now,s,speed,min(3,max(.1,speed/max(3,baseline_speed))))
                        self.stats['held_speed_uses']+=1
    def _speed_features(self,route,direction,vehicle,s,box):
        key=(route,direction,vehicle)
        if self.carry and key in self.held:
            speed=self.held[key][1];return speed,speed,speed,0.
        return super()._speed_features(route,direction,vehicle,s,box)


def run(session,analysis,output):
    if output.exists():raise ValueError('choose fresh output')
    labels={(r['request_id'],r['vehicle']):r for r in read(analysis/'evaluated.jsonl')}
    access=DataAccess(str(session/'artifacts/serving.db'))
    variants={'original':{},'carry30':dict(carry=True),'motion10':dict(motion=True),'motion10_carry30':dict(motion=True,carry=True),
              'duplicate_observations':{},'drop_every_fifth_observation':{},
              'drop_every_fifth_unique_packet':dict(drop_unique=True)}
    extractors={k:ExperimentalExtractor(access,IncidentsProvider(str(session/'local_lakehouse')),**v) for k,v in variants.items()}
    frames=defaultdict(list);info=[];mismatch=Counter();observations=0
    for r in read(session/'backend/trace.jsonl'):
        if r['kind']=='route_observation':
            observations+=1;vs=[BusVehicleDTO(**v) for v in r['vehicles']]
            for name,ex in extractors.items():
                if name=='drop_every_fifth_observation' and observations%5==0:continue
                ex.update_observation(r['route_id'],r['direction'],vs,r['query_epoch'])
                if name=='duplicate_observations':ex.update_observation(r['route_id'],r['direction'],vs,r['query_epoch'])
        elif r['kind']=='eta_result':
            v=BusVehicleDTO(**r['vehicle']);key=(r['request_id'],v.id)
            info.append(dict(request_id=r['request_id'],vehicle=v.id,route=r['route_id'],direction=r['direction'],station=r['station_order'],epoch=r['query_epoch'],observed_eta=r['result']['eta_seconds'],label=labels.get(key)))
            for name,ex in extractors.items():
                source_vehicle=ex.delivered[(r['route_id'],r['direction'],v.id)] if ex.drop_unique else v
                s=r['s_bus_m']
                if ex.motion or ex.drop_unique:s=ex._get_shape_model(r['route_id'],'go' if r['direction']==0 else 're').project_point(source_vehicle.lat,source_vehicle.lng)[0]
                f=ex.build_features(r['route_id'],r['direction'],source_vehicle,r['station_order'],r['s_target_m'],s,r['query_epoch'])
                frames[name].append(f)
                if name=='original':
                    for k,value in r['features'].items():
                        if not np.isclose(value,f[k],rtol=1e-5,atol=.05):mismatch[k]+=1
    assert not mismatch,dict(mismatch)
    model_path=session/'artifacts/model.json';metadata=session/'artifacts/metadata.json'
    manifest=json.loads((session/'session.json').read_text(encoding='utf-8'))
    assert fingerprint(model_path)==manifest['health']['serving']['model']['model_sha256']
    assert fingerprint(metadata)==manifest['health']['serving']['model']['metadata_sha256']
    model=xgb.XGBRegressor(n_jobs=2);model.load_model(model_path);model.set_params(n_jobs=2)
    cal={tuple(map(int,k.split('_'))):tuple(v) for k,v in json.loads(metadata.read_text(encoding='utf-8'))['calibrator'].items()}
    output.mkdir(parents=True);summary={};predictions={}
    for name,rows in frames.items():
        frame=pd.DataFrame(rows)
        for c in ('route_id_idx','direction_id','day_type','hour_slot'):frame[c]=frame[c].astype('int32')
        pred=apply_per_route_calibrator(frame,predict_eta_with_residual_model(model,frame,model.get_booster().feature_names),cal)
        predictions[name]=pred;eligible=np.array([i for i,r in enumerate(info) if r['label'] is not None])
        errors=metrics([info[i]['label']['actual_eta_sec'] for i in eligible],pred[eligible])
        jumps=[];last={}
        for i,r in enumerate(info):
            key=(r['route'],r['direction'],r['station'],r['vehicle']);old=last.get(key)
            if old is not None and 0<r['epoch']-info[old]['epoch']<=15 and pred[i]-pred[old]>=30:jumps.append(dict(before=info[old]['request_id'],after=r['request_id'],vehicle=r['vehicle'],jump_sec=float(pred[i]-pred[old])))
            last[key]=i
        replay_error=float(np.max(np.abs(pred-np.array([r['observed_eta'] for r in info]))))
        if name=='original':assert replay_error<=.051,replay_error
        summary[name]=dict(metrics_on_frozen_labels=errors,stats=dict(extractors[name].stats),jumps_ge30=len(jumps),replay_max_difference_sec=replay_error,original_http_row_scope=len(info),invalid_remaining_distance=sum(f['remaining_distance_m']<0 for f in rows))
        if name=='duplicate_observations':np.testing.assert_allclose(pred,predictions['original'],atol=1e-6)
        (output/(name+'_jumps.json')).write_text(json.dumps(jumps,indent=2),encoding='utf-8')
        frame.to_parquet(output/(name+'_features.parquet'),index=False)
    # Group input replacement: controlled sensitivity, not a causal traffic effect.
    base=pd.DataFrame(frames['original']);ablation={}
    groupcols={'fleet':[c for c in base if c.startswith(('lead_bus_','follow_bus_')) or c in ('n_active_buses_on_route','n_buses_in_corridor_ahead')],
               'ego_motion':[c for c in base if c.startswith(('ego_speed_','ego_accel_'))]+['physics_kinematic_eta_sec','physics_probe_corrected_eta_sec']}
    for group,cols in groupcols.items():
        replaced=base.copy();first={}
        for i,r in enumerate(info):
            key=(r['route'],r['direction'],r['station'],r['vehicle']);origin=first.setdefault(key,i)
            replaced.loc[i,cols]=base.loc[origin,cols]
        for c in ('route_id_idx','direction_id','day_type','hour_slot'):replaced[c]=replaced[c].astype('int32')
        p=apply_per_route_calibrator(replaced,predict_eta_with_residual_model(model,replaced,model.get_booster().feature_names),cal)
        diff=p-predictions['original'];ablation[group]=dict(median_abs_effect_sec=float(np.median(abs(diff))),p90_abs_effect_sec=float(np.quantile(abs(diff),.9)),max_abs_effect_sec=float(max(abs(diff))))
        predictions['freeze_'+group]=p
    effects=[]
    origins={};first_rows=[]
    for i,r in enumerate(info):
        key=(r['route'],r['direction'],r['station'],r['vehicle']);first_rows.append(origins.setdefault(key,i))
    for col in base:
        replacement=base[col].iloc[first_rows].to_numpy()
        if np.array_equal(replacement,base[col].to_numpy()):continue
        replaced=base.copy();replaced[col]=replacement
        for c in ('route_id_idx','direction_id','day_type','hour_slot'):replaced[c]=replaced[c].astype('int32')
        p=apply_per_route_calibrator(replaced,predict_eta_with_residual_model(model,replaced,model.get_booster().feature_names),cal)
        difference=p-predictions['original'];worst=int(np.argmax(abs(difference)))
        effects.append(dict(feature=col,median_abs_effect_sec=float(np.median(abs(difference))),p90_abs_effect_sec=float(np.quantile(abs(difference),.9)),
                            max_abs_effect_sec=float(abs(difference[worst])),worst_request=info[worst]['request_id'],vehicle=info[worst]['vehicle'],
                            original_value=float(base[col].iloc[worst]),frozen_value=float(replacement[worst]),
                            original_eta=float(predictions['original'][worst]),counterfactual_eta=float(p[worst])))
    (output/'field_effects.json').write_text(json.dumps(sorted(effects,key=lambda r:r['p90_abs_effect_sec'],reverse=True),indent=2),encoding='utf-8')
    with (output/'predictions.jsonl').open('w',encoding='utf-8') as stream:
        for i,r in enumerate(info):stream.write(json.dumps(dict(**r,predictions={k:float(v[i]) for k,v in predictions.items()}))+'\n')
    report=dict(scope='retrospective shadow replay, unchanged HTTP row set and frozen GPS labels; not independent acceptance',rows=len(info),fleet_observations=observations,original_feature_mismatches=dict(mismatch),variants=summary,group_sensitivity=ablation,sources={str(p):fingerprint(p) for p in [Path(__file__),session/'session.json',session/'backend/trace.jsonl',session/'artifacts/serving.db',model_path,metadata,analysis/'evaluated.jsonl']})
    (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))
    (output/'experiment_source.py').write_bytes(Path(__file__).read_bytes())


def read(path):
    with path.open(encoding='utf-8') as stream:
        for line in stream:yield json.loads(line)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('session','analysis','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();run(a.session,a.analysis,a.output)
