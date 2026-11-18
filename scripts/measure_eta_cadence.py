"""Measure timestamp spacing from Silver and captured live observations."""
import argparse
from collections import defaultdict
from datetime import datetime
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.dataset as ds


def quantiles(values):
    a=np.asarray(values,dtype=float)
    return dict(n=len(a),p05=float(np.quantile(a,.05)),median=float(np.median(a)),p95=float(np.quantile(a,.95))) if len(a) else dict(n=0)


def spans(groups):
    result={lag:[] for lag in (1,3,5)}
    for values in groups:
        values=np.unique(values)
        # Overnight/large outages are not a rolling observation window.
        cuts=np.where(np.diff(values)>300)[0]+1
        for run in np.split(values,cuts):
            for lag in result:
                if len(run)>lag:result[lag].extend((run[lag:]-run[:-lag]).tolist())
    return {str(lag):quantiles(values) for lag,values in result.items()}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--silver',type=Path,default=Path('data/lakehouse/silver/route_projected_telemetry'))
    parser.add_argument('--sessions',nargs='+',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():parser.error('choose fresh output')
    result=dict(offline={},live={})
    for route in ('02','27'):
        table=ds.dataset(args.silver/('route_code='+route),format='parquet',partitioning='hive').to_table(columns=['vehicle_id','direction','device_epoch'])
        frame=table.to_pandas().sort_values('device_epoch')
        result['offline'][route]=spans([group.device_epoch.to_numpy() for _,group in frame.groupby(['vehicle_id','direction'])])
    groups=defaultdict(lambda:defaultdict(list))
    for session in args.sessions:
        for line in (session/'http.jsonl').read_text(encoding='utf-8').splitlines():
            row=json.loads(line)
            if row['endpoint']!='live-vehicles' or row['status']!=200 or not isinstance(row['body'],dict):continue
            for vehicle in row['body']['vehicles']:
                key=(row['params']['route'],row['params']['direction'],vehicle['id'])
                groups[vehicle['telemetry_source']][key].append(datetime.fromisoformat(vehicle['updated_at']).timestamp())
    result['live']={source:spans(list(vehicles.values())) for source,vehicles in groups.items()}
    result['interpretation']='Silver uses observed device epochs; TimBus live timestamps are fetch-based and do not establish hardware heartbeat'
    result['method']='unique timestamps per vehicle/direction, split gaps >300s; lag spans describe spacing, not an assertion of every training trip window'
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))


if __name__=='__main__':main()
