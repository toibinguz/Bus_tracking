"""Behavioral probes on frozen packets, with complete event lists and no model changes."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import pyarrow.parquet as pq

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def lead_sensitivity(session, pair):
    """Locate a model-input cause; hybrid inputs are not new observed samples."""
    import pandas as pd
    import xgboost as xgb
    from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.frenet import ShapeProjectionModel
    from experiments.timbus.timbus_tracker import TimBusClient
    a,b=pair['before'],pair['after']
    speed=['lead_bus_speed_kmh','lead_bus_speed_ratio']
    fleet=[k for k in a['features'] if k.startswith(('lead_bus_','follow_bus_')) or k in ('n_active_buses_on_route','n_buses_in_corridor_ahead')]
    samples={'before_observed':a['features'],'after_observed':b['features']}
    for name,keys in [('after_with_previous_lead_speed',speed),('after_with_previous_fleet',fleet)]:
        f=dict(b['features']);f.update({k:a['features'][k] for k in keys});samples[name]=f
    f=dict(a['features']);f.update({k:b['features'][k] for k in speed});samples['before_with_new_lead_speed']=f
    path=session/'artifacts/model.json';m=xgb.XGBRegressor(n_jobs=2);m.load_model(path);m.set_params(n_jobs=2)
    x=pd.DataFrame(list(samples.values())).reindex(columns=m.get_booster().feature_names)
    for c in ('route_id_idx','direction_id','day_type','hour_slot'):x[c]=x[c].astype('int32').astype('category')
    assert a['model']['calibrator']==b['model']['calibrator']
    variants=[]
    for (name,f),delta in zip(samples.items(),m.predict(x)):
        pre=max(5.,f['baseline_eta_p50_sec']+float(delta));cal=a['model']['calibrator']
        eta=max(5.,.5*pre*cal[0]+.5*(pre+cal[1])) if cal else pre
        variants.append(dict(variant=name,delta=float(delta),eta=eta))
    assert abs(variants[0]['eta']-a['result']['eta_seconds'])<.051
    assert abs(variants[1]['eta']-b['result']['eta_seconds'])<.051
    manifest=json.loads((session/'session.json').read_text(encoding='utf-8'))
    route=next(r['route'] for r in manifest['selected'] if r['route_id']==pair['group'][0])
    g=next(g for g in json.loads((session/'geometry.json').read_text(encoding='utf-8'))['geometry'] if g['route']==route)
    shape=ShapeProjectionModel.build(g['points']);observed=[];lead_id=None;plate=None
    for r in records(session/'backend/trace.jsonl'):
        if r['kind']=='route_observation' and r['route_id']==pair['group'][0] and r['direction']==pair['group'][1] and r['request_id']==b['request_id']:
            candidates=[(shape.project_point(v['lat'],v['lng'])[0],v) for v in r['vehicles']]
            ahead=[v for s,v in candidates if s>b['features']['s_bus_m']+20]
            lead=min(ahead,key=lambda v:shape.project_point(v['lat'],v['lng'])[0]);lead_id=lead['id'];plate=TimBusClient.normalize_plate(lead['plate'])
            break
    if lead_id is not None:
        for r in records(session/'backend/trace.jsonl'):
            if r['kind']!='route_observation' or r['route_id']!=pair['group'][0] or r['direction']!=pair['group'][1]:continue
            if not a['query_epoch']-30<=r['query_epoch']<=b['query_epoch']+15:continue
            for v in r['vehicles']:
                if v['id']==lead_id:
                    s,ct,seg=shape.project_point(v['lat'],v['lng'])
                    observed.append(dict(request_id=r['request_id'],query_epoch=r['query_epoch'],vehicle=v,s_m=s,cross_track_m=ct,segment=seg))
    raw=[];base=session/'upstream'
    for r in records(base/'index.jsonl'):
        if r['source']!='timbus' or r['params'].get('vehicle')!=plate:continue
        t=datetime.fromisoformat(r['sent_at']).timestamp()
        if not a['query_epoch']-30<=t<=b['query_epoch']+15:continue
        file=r['files'].get('decoded_response')
        if not file:continue
        payload=(base/file['path']).read_bytes();assert hashlib.sha256(payload).hexdigest()==file['sha256']
        for bus in TimBusClient.parse_bus_packet(payload,direction_fallback=r['params']['direction']):
            if TimBusClient.normalize_plate(bus.plate)==plate:
                raw.append(dict(time_hanoi=stamp(t),request_id=r['http_request_id'],params=r['params'],record=bus.to_dict(),decoded=file))
    return dict(scope='input sensitivity, not physical causality or accuracy evidence',pair=pair,
                variants=variants,lead_observations=observed,lead_upstream_records=raw)


def transition(before, after):
    """An arrival revision is elapsed wall time plus change in remaining ETA."""
    if before['result']['vehicle_id'] != after['result']['vehicle_id']:
        raise ValueError('Cannot compare different vehicles as one countdown')
    dt = after['query_epoch'] - before['query_epoch']
    change = after['result']['eta_seconds'] - before['result']['eta_seconds']
    return dict(dt_sec=dt, eta_change_sec=change, arrival_revision_sec=dt+change,
                distance_advance_m=before['features']['remaining_distance_m']-after['features']['remaining_distance_m'])


def recommendation_check(query, optimistic, left, right):
    """Compare with GPS crossing bracket, not an asserted physical departure."""
    when = query + optimistic
    return dict(later_than_latest_gps_crossing=when > right,
                later_than_earliest_gps_crossing=when > left,
                lateness_beyond_right_sec=max(0., when-right))


def records(path):
    with path.open(encoding='utf-8') as stream:
        for line in stream:
            yield json.loads(line)


def stamp(value):
    return datetime.fromtimestamp(value, ZoneInfo('Asia/Ho_Chi_Minh')).strftime('%H:%M:%S')


def main(session, analysis, output, features):
    if output.exists():
        raise ValueError('choose fresh output')
    groups = defaultdict(list)
    model_rows = {}
    trace = session/'backend/trace.jsonl'
    placeholders = Counter()
    total = 0
    for r in records(trace):
        if r['kind'] == 'model_prediction':
            model_rows[(r['request_id'], json.dumps(r['features'], sort_keys=True))] = r
        if r['kind'] != 'eta_result':
            continue
        total += 1
        f = r['features']
        for name, condition in dict(probe_coverage_zero=f['recent_seg_coverage_ratio']==0,
                                    probe_ratio_one=f['recent_corridor_congestion_ratio']==1,
                                    probe_time_equals_matrix=f['recent_corridor_tt_sum_sec']==f['baseline_eta_p50_sec'],
                                    cumulative_delay_zero=f['ego_cum_delay_vs_baseline_sec']==0,
                                    incidents_zero=f['inc_ahead_count']==0).items():
            placeholders[name] += bool(condition)
        groups[(r['route_id'], r['direction'], r['station_order'], r['vehicle']['id'])].append(r)
    pairs, still = [], []
    def point(r):
        return dict(request_id=r['request_id'], time_hanoi=stamp(r['query_epoch']),
                    query_epoch=r['query_epoch'], vehicle=r['vehicle'], features=r['features'], result=r['result'],
                    model=model_rows.get((r['request_id'], json.dumps(r['features'], sort_keys=True))))
    for key, rows in groups.items():
        rows.sort(key=lambda r:r['query_epoch'])
        for a, b in zip(rows, rows[1:]):
            change = transition(a,b)
            if 0 < change['dt_sec'] <= 15 and change['distance_advance_m'] >= -20:
                pairs.append(dict(group=key, **change, before=point(a), after=point(b)))
        start = 0
        for i in range(1, len(rows)+1):
            same = i < len(rows) and (rows[i]['vehicle']['lat'], rows[i]['vehicle']['lng']) == (rows[start]['vehicle']['lat'], rows[start]['vehicle']['lng'])
            contiguous = i < len(rows) and 0 < rows[i]['query_epoch']-rows[i-1]['query_epoch'] <= 15
            if same and contiguous:
                continue
            a, b = rows[start], rows[i-1]
            duration = b['query_epoch']-a['query_epoch']
            if duration >= 30:
                still.append(dict(group=key, duration_sec=duration, polls=i-start,
                                  before=point(a), after=point(b), **transition(a,b)))
            start = i
    # Labels come from separate GPS crossing analysis, never from predicted ETA.
    arrivals = {(a['route'],a['vehicle'],a['trip'],a['station_order']):a
                for a in json.loads((analysis/'arrivals.json').read_text(encoding='utf-8')) if a['valid']}
    by_request = {(r['request_id'],r['vehicle']['id']):r for rows in groups.values() for r in rows}
    recommendations = []
    comparison = []
    for label in records(analysis/'evaluated.jsonl'):
        r = by_request[(label['request_id'],label['vehicle'])]
        a = arrivals[(label['route'],label['vehicle'],label['trip'],label['station_order'])]
        check = recommendation_check(r['query_epoch'],r['result']['optimistic_eta_seconds'],a['left'],a['right'])
        event_key = [label['route'],label['vehicle'],label['trip'],label['station_order']]
        recommendations.append(dict(request_id=r['request_id'], event=event_key,
                                    query_time=stamp(r['query_epoch']), **check))
        f = r['features']; model = model_rows.get((r['request_id'],json.dumps(f,sort_keys=True)))
        if model:
            actual = label['actual_eta_sec']
            before = max(5.,f['baseline_eta_p50_sec']+model['delta'])
            comparison.append(dict(request_id=r['request_id'],event=event_key,
                                   baseline_error_sec=f['baseline_eta_p50_sec']-actual,
                                   uncalibrated_error_sec=before-actual,
                                   calibrated_error_sec=r['result']['eta_seconds']-actual))
    # Read every existing partition, bounded batches. This audits feature meaning,
    # not the provenance or correctness of the historical labels.
    cols=['ego_trip_elapsed_sec','ego_cum_delay_vs_baseline_sec','recent_seg_coverage_ratio',
          'recent_corridor_congestion_ratio','recent_next_seg_congestion_ratio']
    offline = defaultdict(Counter); feature_inputs=[]; examples=[]
    for path in sorted(features.glob('split=*/route_code=*/*.parquet')):
        split=path.parent.parent.name
        for batch in pq.ParquetFile(path).iter_batches(batch_size=32768,columns=cols):
            frame=batch.to_pandas(); stats=offline[split];stats['rows']+=len(frame)
            for col in cols:
                reference = 1 if 'congestion_ratio' in col else 0
                stats[col+'_not_default']+=int((frame[col]!=reference).sum())
            if len(examples)<8:
                for row in frame[(frame.recent_seg_coverage_ratio>0)&(frame.ego_cum_delay_vs_baseline_sec!=0)].head(1).to_dict('records'):
                    examples.append(dict(path=str(path),values=row))
        with path.open('rb') as stream:
            feature_inputs.append(dict(path=str(path),sha256=hashlib.file_digest(stream,'sha256').hexdigest()))
    large = [p for p in pairs if p['eta_change_sec']>=30]
    advancing = [p for p in large if p['distance_advance_m']>0]
    bad = [r for r in recommendations if r['later_than_latest_gps_crossing']]
    summary=dict(scope='retrospective behavioral probes; flags are review candidates, not automatic bugs',
                 session=str(session), forecasts=total, vehicle_station_groups=len(groups),
                 feature_placeholder_counts=dict(placeholders), offline_feature_domains={k:dict(v) for k,v in offline.items()},
                 offline_examples=examples, adjacent_pairs=len(pairs), upward_jumps_ge30=len(large),
                 upward_jumps_ge30_while_advancing=len(advancing), unchanged_coordinate_runs_ge30sec=len(still),
                 stationary_runs_with_fresh_fetch_age=sum(r['after']['result']['ping_age_seconds']<2 for r in still),
                 labelled_forecasts=len(recommendations), recommendation_after_bracket_right=len(bad),
                 affected_arrival_events=len({tuple(r['event']) for r in bad}),
                 labelled_arrival_events=len({tuple(r['event']) for r in recommendations}),
                 max_recommendation_lateness_beyond_right_sec=max((r['lateness_beyond_right_sec'] for r in bad),default=0),
                 ml_closer_than_matrix=sum(abs(r['calibrated_error_sec'])<abs(r['baseline_error_sec']) for r in comparison),
                 calibration_closer_than_uncalibrated=sum(abs(r['calibrated_error_sec'])<abs(r['uncalibrated_error_sec']) for r in comparison),
                 comparison_rows=len(comparison),
                 limitations=['GPS crossing is not dwell/departure','repeated forecasts and same-vehicle events are correlated',
                              'unchanged coordinates do not establish physical standstill','raw session overlaps earlier pilot; do not pool'])
    sensitivity=lead_sensitivity(session,max(large,key=lambda p:p['eta_change_sec'])) if large else None
    output.mkdir(parents=True)
    for name,value in [('summary.json',summary),('upward_jumps.json',sorted(large,key=lambda p:p['eta_change_sec'],reverse=True)),
                       ('unchanged_coordinate_runs.json',sorted(still,key=lambda p:p['duration_sec'],reverse=True)),
                       ('recommendations.json',recommendations),('paired_errors.json',comparison),('feature_inputs.json',feature_inputs),
                       ('lead_speed_sensitivity.json',sensitivity)]:
        (output/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    sources={}
    for path in [trace,analysis/'arrivals.json',analysis/'evaluated.jsonl',Path(__file__)]:
        with path.open('rb') as stream:sources[str(path)]=hashlib.file_digest(stream,'sha256').hexdigest()
    (output/'source_hashes.json').write_text(json.dumps(sources,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('session','analysis','output','features'):p.add_argument('--'+name,type=Path,required=True)
    args=p.parse_args();main(args.session,args.analysis,args.output,args.features)
