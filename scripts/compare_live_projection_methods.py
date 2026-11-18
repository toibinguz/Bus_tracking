"""Recorded-live projection comparison: current global, actual offline, causal HMM.

No production patch. GPS labels remain frozen; error metrics are diagnostics.
"""
import argparse
from collections import Counter,defaultdict
import json
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd
import xgboost as xgb

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from route_projection_candidates import RouteHMM
from experiment_eta_streaming import PreparedShape
from evaluate_eta_candidate import fingerprint,metrics
from module_1_data_ingestion_and_preprocessing.step_1_4_frenet_spatial_projection.multi_route_projector import project_points_to_shape
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.data_access import DataAccess,IncidentsProvider
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.dto import BusVehicleDTO
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.online_features import _window_speed
from global_projection_reference import GlobalProjectionReference as OnlineFeatureExtractor
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.live_feed import parse_ping_epoch
from module_3_bus_eta_prediction.step_3_3_machine_learning_models.eta_model_trainer import predict_eta_with_residual_model,apply_per_route_calibrator


def read(path):
    with path.open(encoding='utf-8') as stream:
        for line in stream:yield json.loads(line)


class MatchedExtractor(OnlineFeatureExtractor):
    def __init__(self,*args,method,offline,**kwargs):
        super().__init__(*args,**kwargs);self.method=method;self.offline=offline
        self.engines={};self.latest={};self.observations={};self.stats=Counter();self.times=[];self.log=[]
    def update_observation(self,route,direction,vehicles,now):
        ds='go' if direction==0 else 're';shape=self._get_shape_model(route,ds)
        if shape is None:return
        if not isinstance(shape,PreparedShape):shape=PreparedShape(shape);self._shape_models[(route,ds)]=shape
        accepted=[];previous={};changed={}
        for v in vehicles:
            key=(route,direction,v.id);epoch,_=parse_ping_epoch(v.updated_at,now);epoch=min(now,epoch)
            identity=(*key,epoch);old=self.latest.get(key)
            if old and epoch<=old[0]:
                projection=old[1];self.stats['repeated_or_late']+=1
            else:
                before=time.perf_counter_ns()
                if self.method=='offline':
                    result=self.offline.get(identity)
                    segment=int(np.clip(np.searchsorted(shape.base._cum_starts,result[0],side='right')-1,0,len(shape.base._dx)-1)) if result else 0
                    projection=(result[0],result[1],segment) if result else None
                else:
                    engine=self.engines.setdefault(key,RouteHMM(shape.base,sigma=15 if self.method=='hmm15' else 25))
                    index=len(self.observations);self.observations[index]=(epoch,v.raw_speed_kmh if v.raw_speed_kmh is not None else v.speed_kmh)
                    match=engine.update(epoch,v.lat,v.lng,index)
                    projection=(match.s,match.cross_track,match.segment) if match else None
                    if match:changed[key]=list(engine.best_path)
                self.times.append((time.perf_counter_ns()-before)/1e6)
                self.latest[key]=(epoch,projection)
                self.log.append(dict(route=route,direction=direction,vehicle=v.id,epoch=epoch,lat=v.lat,lng=v.lng,
                                     projection=projection,raw_global=shape.base.project_point(v.lat,v.lng),
                                     reason=self.engines[key].reason if key in self.engines else 'offline_result',
                                     margin=self.engines[key].margin if key in self.engines else None))
            if projection is None:self.stats['unmatched_snapshot_entries']+=1;continue
            shape.resolved[(v.lat,v.lng)]=projection;accepted.append(v)
            previous[key]=list(self._obs.get(key,[]))
        super().update_observation(route,direction,accepted,now)
        # Correct recent speed history when Viterbi revises earlier branch choices.
        for key,path in changed.items():
            prefix=[] if self.engines[key].reason in ('initialized','terminal_reset') else [p for p in previous[key] if p[0]<path[0].epoch and p[0]>=now-600]
            corrected=prefix+[(p.epoch,p.s,self.observations[p.observation][1]) for p in path]
            self.stats['revised_past_positions']+=sum(any(t==p.epoch and abs(s-p.s)>.1 for t,s,_ in previous[key]) for p in path[:-1])
            self._obs[key]=corrected[-160:]
        for v in accepted:
            key=(route,direction,v.id);ring=self._obs[key];s=self.latest[key][1][0]
            if key in changed:
                speed,_=_window_speed(ring,s,240.,10.)
                if speed is None:speed,_=_window_speed(ring,s,75.,10.)
                if speed is None:speed=v.raw_speed_kmh if v.raw_speed_kmh is not None else v.speed_kmh
                corridor=self._da.get_corridor_stations(route,ds);day,hour,*_=self._calendar(now)
                tt=self._segment_array(route,direction,corridor,day,hour,self._da.get_route_profile(route,ds)[0],index=1)
                k=self._current_segment_index([p[3] for p in corridor],s)
                base=max(1,corridor[k+1][3]-corridor[k][3])/max(1,tt[k])*3.6
                self._fleet[(route,direction)][v.id]=(now,s,speed,min(3,max(.1,speed/max(3,base))))


def run(session,analysis,output):
    if output.exists():raise ValueError('choose fresh output')
    output.mkdir(parents=True)
    access=DataAccess(str(session/'artifacts/serving.db'));series=defaultdict(list);last={};index=0;counts=Counter()
    # Normalization is arrival-order causal; duplicates/late packets cannot become future evidence.
    for r in read(session/'backend/trace.jsonl'):
        if r['kind']!='route_observation':continue
        for v in r['vehicles']:
            key=(r['route_id'],r['direction'],v['id']);epoch,_=parse_ping_epoch(v['updated_at'],r['query_epoch']);epoch=min(epoch,r['query_epoch'])
            if epoch<=last.get(key,-np.inf):counts['duplicate_or_late']+=1;continue
            last[key]=epoch;series[key].append((index,v['lat'],v['lng'],epoch));index+=1
    offline={};offline_ns=0;global_times=[]
    for key,pings in series.items():
        points=access.get_shape_points(key[0],'go' if key[1]==0 else 're')
        from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.frenet import ShapeProjectionModel
        baseline_shape=ShapeProjectionModel.build(points)
        for _,lat,lng,epoch in pings:
            start=time.perf_counter_ns();baseline_shape.project_point(lat,lng);global_times.append((time.perf_counter_ns()-start)/1e6)
        start=time.perf_counter_ns();results=project_points_to_shape(pings,points);offline_ns+=time.perf_counter_ns()-start
        by_id={r[0]:r[1:] for r in results}
        for identity,lat,lng,epoch in pings:
            if identity in by_id:offline[(*key,epoch)]=by_id[identity]
    exs={'global':OnlineFeatureExtractor(access,IncidentsProvider(str(session/'local_lakehouse')))}
    for name in ['offline','hmm15','hmm25']:exs[name]=MatchedExtractor(access,IncidentsProvider(str(session/'local_lakehouse')),method=name,offline=offline)
    labels={(r['request_id'],r['vehicle']):r for r in read(analysis/'evaluated.jsonl')};rows=[];frames=defaultdict(list);valid=defaultdict(list);mismatch=Counter()
    update_times=defaultdict(list);feature_times=defaultdict(list)
    for r in read(session/'backend/trace.jsonl'):
        if r['kind']=='route_observation':
            vehicles=[BusVehicleDTO(**v) for v in r['vehicles']]
            for name,ex in exs.items():
                started=time.perf_counter_ns();ex.update_observation(r['route_id'],r['direction'],vehicles,r['query_epoch'])
                update_times[name].append((time.perf_counter_ns()-started)/1e6)
        elif r['kind']=='eta_result':
            v=BusVehicleDTO(**r['vehicle']);key=(r['route_id'],r['direction'],v.id)
            rows.append(dict(request_id=r['request_id'],vehicle=v.id,route=r['route_id'],direction=r['direction'],station=r['station_order'],epoch=r['query_epoch'],observed_eta=r['result']['eta_seconds'],label=labels.get((r['request_id'],v.id))))
            for name,ex in exs.items():
                if name=='global':s=r['s_bus_m'];ok=True
                else:
                    match=ex.latest.get(key);ok=bool(match and match[1] is not None)
                    s=match[1][0] if ok else r['s_bus_m']
                    ok=ok and s<=r['s_target_m']
                started=time.perf_counter_ns()
                f=ex.build_features(r['route_id'],r['direction'],v,r['station_order'],r['s_target_m'],s,r['query_epoch'])
                feature_times[name].append((time.perf_counter_ns()-started)/1e6)
                frames[name].append(f);valid[name].append(ok)
                if name=='global':
                    for col,value in r['features'].items():
                        if not np.isclose(value,f[col],rtol=1e-5,atol=.05):mismatch[col]+=1
    assert not mismatch,dict(mismatch)
    model_path=session/'artifacts/model.json';meta=session/'artifacts/metadata.json';manifest=json.loads((session/'session.json').read_text(encoding='utf-8'))
    assert fingerprint(model_path)==manifest['health']['serving']['model']['model_sha256']
    assert fingerprint(meta)==manifest['health']['serving']['model']['metadata_sha256']
    model=xgb.XGBRegressor(n_jobs=2);model.load_model(model_path);model.set_params(n_jobs=2)
    cal={tuple(map(int,k.split('_'))):tuple(v) for k,v in json.loads(meta.read_text(encoding='utf-8'))['calibrator'].items()}
    labelled=np.array([r['label'] is not None for r in rows]);common=labelled.copy()
    for mask in valid.values():common&=np.array(mask)
    pred={};report={}
    for name,fs in frames.items():
        frame=pd.DataFrame(fs)
        for c in ['route_id_idx','direction_id','day_type','hour_slot']:frame[c]=frame[c].astype('int32')
        p=apply_per_route_calibrator(frame,predict_eta_with_residual_model(model,frame,model.get_booster().feature_names),cal)
        pred[name]=p
        if name=='global':assert max(abs(p-np.array([r['observed_eta'] for r in rows])))<=.051
        ids=np.flatnonzero(common);own=np.flatnonzero(labelled&np.array(valid[name]))
        jumps=[];previous={}
        for i,r in enumerate(rows):
            k=(r['route'],r['direction'],r['station'],r['vehicle']);old=previous.get(k)
            if valid[name][i]:
                if old is not None and 0<r['epoch']-rows[old]['epoch']<=15 and p[i]-p[old]>=30:jumps.append(dict(before=rows[old]['request_id'],after=r['request_id'],vehicle=r['vehicle'],seconds=float(p[i]-p[old])))
                previous[k]=i
            else:previous.pop(k,None)
        ex=exs[name];log=ex.log if name!='global' else []
        by_vehicle=defaultdict(list)
        for point in log:
            if point['projection']:by_vehicle[(point['route'],point['direction'],point['vehicle'])].append(point)
        backwards=sum(b['projection'][0]<a['projection'][0]-50 for points in by_vehicle.values() for a,b in zip(points,points[1:]))
        timings=ex.times if name!='global' else global_times
        report[name]=dict(forecasts_available=int(sum(valid[name])),labelled_available=len(own),common_labelled=len(ids),
                          common_metrics=metrics([rows[i]['label']['actual_eta_sec'] for i in ids],p[ids]),
                          own_metrics=metrics([rows[i]['label']['actual_eta_sec'] for i in own],p[own]),
                          jumps_ge30=len(jumps),large_backwards=backwards if name!='global' else None,
                          matcher_p50_ms=float(np.median(timings)) if timings else None,
                          matcher_p95_ms=float(np.quantile(timings,.95)) if timings else None,
                          stats=dict(ex.stats) if name!='global' else {},
                          hmm_reinitializations=sum(e.resets for e in ex.engines.values()) if name.startswith('hmm') else None,
                          state_update_p95_ms=float(np.quantile(update_times[name],.95)),
                          feature_build_p95_ms=float(np.quantile(feature_times[name],.95)),
                          state_and_feature_cpu_total_ms=float(sum(update_times[name])+sum(feature_times[name])),
                          note='offline timing here is lookup only; actual batch timing is reported separately' if name=='offline' else '')
        frame.to_parquet(output/(name+'_features.parquet'),index=False)
        (output/(name+'_projections.jsonl')).write_text(''.join(json.dumps(r)+'\n' for r in log),encoding='utf-8')
        (output/(name+'_jumps.json')).write_text(json.dumps(jumps,indent=2),encoding='utf-8')
    with (output/'predictions.jsonl').open('w',encoding='utf-8') as stream:
        for i,r in enumerate(rows):stream.write(json.dumps(dict(**r,predictions={k:float(v[i]) if valid[k][i] else None for k,v in pred.items()}))+'\n')
    result=dict(scope='causal recorded-live shadow replay; frozen old-projection GPS labels are not independent map ground truth',
                forecasts=len(rows),unique_vehicle_pings=index,vehicle_streams=len(series),normalization=dict(counts),offline_rejected=index-len(offline),
                offline_actual_batch_total_ms=offline_ns/1e6,original_feature_mismatches=dict(mismatch),variants=report,
                limits=['No new live collection','No production changes','No completed incident/probe producer implied','Fixed original HTTP row set, not complete endpoint replay',
                        'HMM score margins are not calibrated confidence','No guarantee a smoother trace selects the physical correct branch'],
                sources={str(p):fingerprint(p) for p in [Path(__file__),ROOT/'scripts/route_projection_candidates.py',session/'backend/trace.jsonl',model_path,meta,analysis/'evaluated.jsonl']})
    (output/'report.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    for p in [Path(__file__),ROOT/'scripts/route_projection_candidates.py']:(output/p.name).write_bytes(p.read_bytes())
    print(json.dumps(result))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['session','analysis','output']:p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();run(a.session,a.analysis,a.output)
