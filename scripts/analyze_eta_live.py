"""Observed-position arrival brackets and descriptive live ETA error analysis."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime
import json
from pathlib import Path
import sys

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from config.system_config import MAX_CORRIDOR_CROSS_TRACK_M
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.frenet import ShapeProjectionModel
from evaluate_eta_candidate import metrics


def epoch(value):
    return datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()


def crossing_events(samples, stations, max_gap=40, reset_m=150):
    """Samples are (timestamp, s_metres); crossing time is GPS-derived, not dwell."""
    samples=sorted(set(samples))
    events=[]; intervals=[]; trip=0; previous=None; seen=set(); start=None
    for timestamp,position in samples:
        if previous is not None and position<previous[1]-reset_m:
            intervals.append((trip,start,previous[0]))
            trip+=1; previous=None;seen=set();start=None
        if start is None: start=timestamp
        if previous is not None:
            old_t,old_s=previous
            if timestamp==old_t or position<old_s: continue
            dt=timestamp-old_t
            for order,target in stations.items():
                if order in seen or not old_s<=target<position: continue
                seen.add(order)
                if dt>max_gap or (position-old_s)/dt*3.6>80:
                    events.append(dict(trip=trip,station_order=order,valid=False,reason='gap_or_impossible_speed',left=old_t,right=timestamp))
                    continue
                arrival=old_t+(target-old_s)/(position-old_s)*dt
                events.append(dict(trip=trip,station_order=order,valid=True,left=old_t,right=timestamp,
                                   estimated_arrival_epoch=arrival,uncertainty_sec=dt))
        previous=(timestamp,position)
    if previous is not None: intervals.append((trip,start,previous[0]))
    return events,intervals


def analyze(session,output):
    session,output=Path(session),Path(output)
    if output.exists(): raise ValueError('choose fresh analysis output')
    output.mkdir(parents=True)
    manifest=json.loads((session/'session.json').read_text(encoding='utf-8'))
    geometry=json.loads((session/'geometry.json').read_text(encoding='utf-8'))
    models={g['route']:ShapeProjectionModel.build(g['points']) for g in geometry['geometry']}
    selected={r['route']:r for r in manifest['selected']}
    observations=defaultdict(list);traces={};http_rows=[]
    trace=session/'backend/trace.jsonl'
    if trace.exists():
        for line in trace.read_text(encoding='utf-8').splitlines():
            row=json.loads(line)
            if row['kind']=='eta_result':
                traces[(row['request_id'],row['result']['vehicle_id'])]=row
    rejected=Counter()
    def observe(route,vehicle):
        model=models[route]
        s,ct,segment=model.project_point(vehicle['lat'],vehicle['lng'])
        if ct>MAX_CORRIDOR_CROSS_TRACK_M:
            rejected['off_corridor']+=1;return
        ux,uy=model.segment_unit_tangent(segment)
        angle=np.radians(float(vehicle['deg']))
        if ux*np.sin(angle)+uy*np.cos(angle)<0:
            rejected['opposite_heading']+=1;return
        observations[(route,vehicle['id'])].append((epoch(vehicle['updated_at']),s))
    for line in (session/'http.jsonl').read_text(encoding='utf-8').splitlines():
        row=json.loads(line);http_rows.append(row)
        body=row.get('body')
        if row['status']!=200 or not isinstance(body,dict):continue
        route=row['params'].get('route')
        if row['endpoint']=='live-vehicles':
            for vehicle in body['vehicles']:observe(route,vehicle)
        elif row['endpoint']=='station-eta':
            for bus in body['buses']:
                trace=traces.get((row['request_id'],bus['vehicle_id']))
                if trace:observe(route,trace['vehicle'])
    arrivals=[]; trips={}
    for (route,vehicle),samples in observations.items():
        stations={s['station_order']:s['cum_distance_m'] for s in selected[route]['stations']['stations'] if s['station_order'] in selected[route]['orders']}
        events,intervals=crossing_events(samples,stations,manifest['ground_truth_protocol']['max_gap_sec'],manifest['ground_truth_protocol']['reset_backwards_m'])
        trips[(route,vehicle)]=intervals
        arrivals.extend(dict(route=route,vehicle=vehicle,**event) for event in events)
    lookup={(a['route'],a['vehicle'],a['trip'],a['station_order']):a for a in arrivals}
    evaluated=[];censored=Counter()
    for row in http_rows:
        if row['endpoint']!='station-eta' or row['status']!=200 or not isinstance(row['body'],dict):continue
        body=row['body'];route=row['params']['route'];order=row['params']['station_order']
        for bus in body['buses']:
            trace=traces.get((row['request_id'],bus['vehicle_id']))
            if not trace:
                censored['missing_trace']+=1;continue
            ping=epoch(trace['vehicle']['updated_at']);query=epoch(body['query_time'])
            candidates=[trip for trip,start,end in trips.get((route,bus['vehicle_id']),[]) if start<=ping<=end]
            arrival=lookup.get((route,bus['vehicle_id'],candidates[-1],order)) if candidates else None
            if not arrival or not arrival['valid']:
                censored['unobserved_or_invalid_crossing']+=1;continue
            actual=arrival['estimated_arrival_epoch']-query
            if actual<=0:
                censored['query_after_estimated_arrival']+=1;continue
            predicted=bus['eta_seconds'];error=predicted-actual
            lower=max(0,arrival['left']-query);upper=max(0,arrival['right']-query)
            evaluated.append(dict(route=route,vehicle=bus['vehicle_id'],trip=arrival['trip'],station_order=order,
                                  request_id=row['request_id'],actual_eta_sec=actual,predicted_eta_sec=predicted,
                                  baseline_eta_sec=trace['features']['baseline_eta_p50_sec'],error_sec=error,
                                  absolute_error_min_sec=max(0,lower-predicted,predicted-upper),
                                  absolute_error_max_sec=max(abs(predicted-lower),abs(predicted-upper)),
                                  uncertainty_sec=arrival['uncertainty_sec'],hops=bus['stops_remaining'],
                                  source=bus['telemetry_source'],prediction_source=bus['prediction_source'],
                                  interval_covered=bus['safe_window']['p10_seconds']<=actual<=bus['safe_window']['p90_seconds']))
    def summarize(rows):
        actual=[r['actual_eta_sec'] for r in rows]
        return dict(metrics=metrics(actual,[r['predicted_eta_sec'] for r in rows]),
                    baseline=metrics(actual,[r['baseline_eta_sec'] for r in rows]),
                    arrival_events=len({(r['route'],r['vehicle'],r['trip'],r['station_order']) for r in rows}),
                    vehicle_trips=len({(r['route'],r['vehicle'],r['trip']) for r in rows}),
                    window_coverage_pct=100*sum(r['interval_covered'] for r in rows)/len(rows),
                    median_gps_bracket_sec=float(np.median([r['uncertainty_sec'] for r in rows])))
    report=dict(http_requests=len(http_rows),http_errors=sum(r['status']!=200 for r in http_rows),
                gps_observations=sum(map(len,observations.values())),rejected_gps=dict(rejected),
                crossing_events=sum(a['valid'] for a in arrivals),invalid_crossings=sum(not a['valid'] for a in arrivals),
                forecasts_evaluated=len(evaluated),censored_forecasts=dict(censored),
                overall=summarize(evaluated) if evaluated else None,
                by_horizon={str(h):summarize(group) for h in (1,2,5,10,15) if (group:=[r for r in evaluated if r['hops']==h])},
                by_source={source:summarize(group) for source in sorted({r['source'] for r in evaluated}) if (group:=[r for r in evaluated if r['source']==source])},
                interpretation='descriptive GPS-position estimates, not physical dwell ground truth or independent IID forecasts',
                limitations=['TimBus timestamp is fetch time; unmeasured upstream caching may add arrival uncertainty',
                             'arrival events on the same vehicle trip are correlated','single session is not generalization evidence'])
    for name,value in [('report.json',report),('arrivals.json',arrivals)]:
        (output/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    with (output/'evaluated.jsonl').open('w',encoding='utf-8') as stream:
        for row in evaluated: stream.write(json.dumps(row)+'\n')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--session',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(analyze(args.session,args.output)))
