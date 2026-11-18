"""Pool nonoverlapping observed sessions without inflating repeated forecasts."""
import argparse
from collections import defaultdict
from datetime import datetime
import json
from pathlib import Path

import numpy as np

from evaluate_eta_candidate import metrics


def summarize(pairs,output):
    output=Path(output)
    if output.exists():raise ValueError('choose fresh report output')
    pooled=[];sessions=[];windows=[]
    for session,analysis in pairs:
        session,analysis=Path(session),Path(analysis)
        manifest=json.loads((session/'session.json').read_text(encoding='utf-8'))
        completed=json.loads((session/'collection.json').read_text())
        start=datetime.fromisoformat(manifest['started_at']).timestamp();end=datetime.fromisoformat(completed['ended_at']).timestamp()
        keys={(r['route'],r['direction']) for r in manifest['selected']}
        for old_start,old_end,old_keys in windows:
            if max(start,old_start)<min(end,old_end) and keys&old_keys:
                raise ValueError('overlapping sessions for the same route/direction cannot be pooled as independent data')
        windows.append((start,end,keys))
        directions={r['route']:r['direction'] for r in manifest['selected']}
        for line in (analysis/'evaluated.jsonl').read_text().splitlines():
            row=json.loads(line);row['direction']=directions[row['route']];row['session']=session.name;pooled.append(row)
        sessions.append(dict(session=str(session),analysis=str(analysis),**completed))
    if not pooled:raise ValueError('no evaluable forecasts')

    def summary(rows):
        actual=[r['actual_eta_sec'] for r in rows]
        events=defaultdict(list)
        for row in rows:events[(row['session'],row['route'],row['direction'],row['vehicle'],row['trip'],row['station_order'])].append(row)
        event_differences=[];clusters=defaultdict(list)
        for event in events.values():
            delta=float(np.mean([abs(r['predicted_eta_sec']-r['actual_eta_sec'])-abs(r['baseline_eta_sec']-r['actual_eta_sec']) for r in event]))
            event_differences.append(delta)
            # A vehicle is a cluster across stations, trips and directions in this pilot day.
            clusters[(event[0]['route'],event[0]['vehicle'])].append(delta)
        groups=list(clusters.values());rng=np.random.default_rng(42);bootstrap=[]
        for _ in range(2000):
            selected=rng.integers(0,len(groups),len(groups));values=[v for i in selected for v in groups[i]]
            bootstrap.append(np.mean(values))
        return dict(forecast_metrics=metrics(actual,[r['predicted_eta_sec'] for r in rows]),
                    baseline_metrics=metrics(actual,[r['baseline_eta_sec'] for r in rows]),
                    arrival_events=len(events),vehicle_clusters=len(clusters),
                    event_balanced_mae_delta_sec=float(np.mean(event_differences)),
                    vehicle_cluster_bootstrap95_delta_sec=[float(np.quantile(bootstrap,q)) for q in (.025,.975)],
                    window_coverage_pct=100*sum(r['interval_covered'] for r in rows)/len(rows),
                    uncertainty_median_sec=float(np.median([r['uncertainty_sec'] for r in rows])))
    result=dict(sessions=sessions,overall=summary(pooled),
                by_horizon={str(h):summary(group) for h in (1,2,5,10,15) if (group:=[r for r in pooled if r['hops']==h])},
                by_route_direction={str(key):summary(group) for key in sorted({(r['route'],r['direction']) for r in pooled}) if (group:=[r for r in pooled if (r['route'],r['direction'])==key])},
                by_source={key:summary(group) for key in sorted({r['source'] for r in pooled}) if (group:=[r for r in pooled if r['source']==key])},
                interpretation='single-day pilot; bootstrap clusters vehicles, does not establish multi-day generalization; negative delta favors model',
                limitations=['GPS-derived brackets, not physical dwell measurement','forecast counts are not independent sample sizes',
                             'unobserved/censored forecasts remain in per-session reports','overlapping raw-capture session intentionally excluded'])
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(result,indent=2),encoding='utf-8');return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--pair',nargs=2,action='append',required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(summarize(args.pair,args.output)))
