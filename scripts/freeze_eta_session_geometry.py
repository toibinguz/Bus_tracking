"""Freeze canonical cumulative distances after verifying captured API geometry."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.data_access import DataAccess


def freeze(session):
    session=Path(session)
    manifest=json.loads((session/'session.json').read_text(encoding='utf-8'))
    target=session/'geometry.json'
    if target.exists(): raise ValueError('geometry already frozen')
    access=DataAccess()
    geometry=[]
    for selected in manifest['selected']:
        direction='go' if selected['direction']==0 else 're'
        points=access.get_shape_points(selected['route_id'],direction)
        if [[p[1],p[2]] for p in points]!=selected['shape']['coordinates']:
            raise ValueError('catalog changed since collection: coordinates')
        stations=access.get_route_stations(selected['route_id'],direction).model_dump()['stations']
        if stations!=selected['stations']['stations']:
            raise ValueError('catalog changed since collection: stations')
        geometry.append(dict(route=selected['route'],route_id=selected['route_id'],direction=selected['direction'],points=points))
    value=dict(frozen_at=datetime.now(timezone.utc).isoformat(),api_geometry_exact_match=True,
               interpretation='canonical cumulative distances recovered from read-only DB; API coords/stations checked exactly',geometry=geometry)
    target.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')
    return value


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--session',type=Path,required=True)
    print(json.dumps({'routes':len(freeze(parser.parse_args().session)['geometry'])}))
