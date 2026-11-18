"""Replay the recorded fleet to inspect speed history at a suspicious ETA jump."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.data_access import DataAccess,IncidentsProvider
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.dto import BusVehicleDTO
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.online_features import OnlineFeatureExtractor,_window_speed


def replay(session,case,output):
    if output.exists():raise ValueError('choose fresh output')
    pair=json.loads(case.read_text(encoding='utf-8'))['pair']
    wanted={pair[k]['request_id'] for k in ('before','after')}
    access=DataAccess(str(session/'artifacts/serving.db'))
    extractor=OnlineFeatureExtractor(access,IncidentsProvider(str(session/'local_lakehouse')))
    route,direction,station,ego=pair['group']; lead=8837137
    key=(route,direction,lead);events=[];checks=[];observations=0
    for ln in (session/'backend/trace.jsonl').open(encoding='utf-8'):
        r=json.loads(ln)
        if r['kind']=='route_observation':
            vehicles=[BusVehicleDTO(**v) for v in r['vehicles']]
            old=list(extractor._obs.get(key,[]))
            extractor.update_observation(r['route_id'],r['direction'],vehicles,r['query_epoch']);observations+=1
            new=list(extractor._obs.get(key,[]))
            if r['route_id']==route and r['direction']==direction and pair['before']['query_epoch']-30<=r['query_epoch']<=pair['after']['query_epoch']+15:
                vehicle=next((v for v in r['vehicles'] if v['id']==lead),None)
                if vehicle:
                    fleet=extractor._fleet[(route,direction)][lead]
                    value,dt=_window_speed(new,fleet[1],240.,10.)
                    if old!=new:
                        events.append(dict(request_id=r['request_id'],query_epoch=r['query_epoch'],vehicle=vehicle,
                                           previous_ring=old,ring=new,window_speed=value,window_dt=dt,
                                           fleet_speed=fleet[2],backward_reset=len(new)==1 and bool(old) and new[-1][1]<old[-1][1]-50))
        elif r['kind']=='eta_result' and r['request_id'] in wanted and r['vehicle']['id']==ego:
            f=extractor.build_features(route,direction,BusVehicleDTO(**r['vehicle']),station,r['s_target_m'],r['s_bus_m'],r['query_epoch'])
            mismatches={k:[v,f[k]] for k,v in r['features'].items() if not np.isclose(v,f[k],rtol=1e-5,atol=.05)}
            assert not mismatches,mismatches
            checks.append(dict(request_id=r['request_id'],all_54_features_match=True,lead_speed=f['lead_bus_speed_kmh'],ring=list(extractor._obs[key])))
    assert len(checks)==2
    # Independently enumerate segment distances around the reset, rather than
    # assuming a backwards projected coordinate proves a physical turnaround.
    shape=extractor._get_shape_model(route,'re' if direction else 'go')
    ambiguities=[];seen=set()
    for event in events:
        v=event['vehicle']
        if v['updated_at'] in seen:continue
        seen.add(v['updated_at'])
        px,py=v['lng']*shape.kx,v['lat']*shape.ky
        t=np.clip(((px-shape._x1)*shape._dx+(py-shape._y1)*shape._dy)/shape._safe_lens_sq,0,1)
        dist=np.hypot(px-shape._x1-t*shape._dx,py-shape._y1-t*shape._dy)
        s=shape._cum_starts+t*shape._seg_lens
        best=int(np.argmin(dist));other=[int(i) for i in np.argsort(dist) if abs(s[i]-s[best])>50]
        alternate=other[0]
        ambiguities.append(dict(updated_at=v['updated_at'],lat=v['lat'],lng=v['lng'],
                                best=dict(segment=best,distance_m=float(dist[best]),s_m=float(s[best])),
                                alternative=dict(segment=alternate,distance_m=float(dist[alternate]),s_m=float(s[alternate]))))
    sources={}
    for path in [Path(__file__),case,session/'backend/trace.jsonl',session/'artifacts/serving.db',
                 ROOT/'module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/online_features.py']:
        with path.open('rb') as stream:sources[str(path)]=hashlib.file_digest(stream,'sha256').hexdigest()
    result=dict(scope='exact feature-state replay of recorded observations; no changes to serving',
                lead_vehicle=lead,fleet_observations=observations,checks=checks,events=events,
                projection_candidates=ambiguities,source_hashes=sources)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(checks=checks,reset_events=[e for e in events if e['backward_reset']]),ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('session','case','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();replay(a.session,a.case,a.output)
