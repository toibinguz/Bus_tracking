"""Follow every packet at one station; preserve inputs and explain model changes.

This is a retrospective case study, not an independent accuracy benchmark.
Tree contributions describe the fitted model, not causes of real traffic.
"""
import argparse
import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import xgboost as xgb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def read_lines(path):
    with path.open(encoding='utf-8') as stream:
        for number, line in enumerate(stream, 1):
            yield number, json.loads(line)


def clock(epoch):
    return datetime.fromtimestamp(epoch, ZoneInfo('Asia/Ho_Chi_Minh')).strftime('%H:%M:%S')


def analyze(session, analysis, output, route, order, primary):
    session, analysis, output = map(Path, (session, analysis, output))
    if output.exists():
        raise ValueError('Choose a fresh output directory; keep earlier evidence')
    manifest = json.loads((session/'session.json').read_text(encoding='utf-8'))
    chosen = next(r for r in manifest['selected'] if r['route'] == route)
    route_id = chosen['route_id']
    station = next(s for s in chosen['stations']['stations'] if s['station_order'] == order)
    packets = [(n, r) for n, r in read_lines(session/'http.jsonl')
               if r['endpoint'] == 'station-eta' and r['params'].get('route') == route
               and r['params'].get('station_order') == order]
    request_ids = {r['request_id'] for _, r in packets}
    results, models, filtered = [], {}, []
    sources = {}
    for n, r in read_lines(session/'backend/trace.jsonl'):
        if r['kind'] == 'eta_result':
            key = r['result']['prediction_source']
            sources[key] = sources.get(key, 0) + 1
        if r['request_id'] not in request_ids:
            continue
        if r['kind'] == 'model_prediction':
            key = (r['request_id'], json.dumps(r['features'], sort_keys=True))
            models[key] = dict(trace_line=n, **r)
        elif r['kind'] == 'eta_result' and r['route_id'] == route_id and r['station_order'] == order:
            results.append(dict(trace_line=n, **r))
        elif r['kind'] in ('eta_filtered', 'station_filtered'):
            filtered.append(dict(trace_line=n, **r))
    results.sort(key=lambda r: (r['vehicle']['id'], r['query_epoch']))
    selected = [r for r in results if r['vehicle']['id'] == primary]
    arrival = next(a for a in json.loads((analysis/'arrivals.json').read_text(encoding='utf-8'))
                   if a['route'] == route and a['vehicle'] == primary and a['station_order'] == order and a['valid'])
    assert len(selected) > 1
    weights = session/'artifacts/model.json'
    model = xgb.XGBRegressor(n_jobs=2)
    model.load_model(weights)
    names = model.get_booster().feature_names
    frame = pd.DataFrame([r['features'] for r in results]).reindex(columns=names)
    for c in ('route_id_idx', 'direction_id', 'day_type', 'hour_slot'):
        frame[c] = frame[c].astype('int32').astype('category')
    # sklearn predict honors early stopping; use the same tree range for explanations.
    end = model.best_iteration + 1 if model.get_booster().attr('best_iteration') is not None else 0
    contributions = model.get_booster().predict(xgb.DMatrix(frame, enable_categorical=True),
                                               pred_contribs=True, iteration_range=(0, end))
    prediction = model.predict(frame)
    np.testing.assert_allclose(contributions.sum(axis=1), prediction, atol=0.001)
    changes, rows = [], []
    previous = {}
    for i, r in enumerate(results):
        key = (r['request_id'], json.dumps(r['features'], sort_keys=True))
        mp = models[key]
        assert abs(float(prediction[i]) - mp['delta']) < 0.001
        f, b = r['features'], r['result']
        pre = max(5., f['baseline_eta_p50_sec'] + mp['delta'])
        cal = mp['calibrator']
        post = max(5., .5 * pre * cal[0] + .5 * (pre + cal[1])) if cal else pre
        assert abs(post - b['eta_seconds']) <= .051
        item = dict(vehicle_id=r['vehicle']['id'], request_id=r['request_id'],
                    trace_line=r['trace_line'], time_hanoi=clock(r['query_epoch']),
                    query_epoch=r['query_epoch'], distance_m=f['remaining_distance_m'],
                    hops=f['n_stations_ahead'], baseline_sec=f['baseline_eta_p50_sec'],
                    model_delta_sec=mp['delta'], before_calibration_sec=pre,
                    calibration_change_sec=post-pre, eta_sec=b['eta_seconds'],
                    arrival_clock=b['estimated_arrival_time'], display=b['display_text'],
                    raw_speed=r['vehicle']['raw_speed_kmh'], display_speed=b['speed_kmh'],
                    ml_speed=f['ego_speed_roll3_kmh'], ping_age=b['ping_age_seconds'],
                    optimistic_eta=b['optimistic_eta_seconds'], p10=b['safe_window']['p10_seconds'],
                    p90=b['safe_window']['p90_seconds'], traffic=b['traffic_status'])
        if item['vehicle_id'] == primary:
            item['gps_remaining_sec'] = arrival['estimated_arrival_epoch'] - r['query_epoch']
            item['predicted_arrival_error_sec'] = b['eta_seconds'] - item['gps_remaining_sec']
        old = previous.get(item['vehicle_id'])
        if old is not None:
            oi, prior = old
            diffs = {k: [prior['features'][k], f[k]] for k in names if prior['features'][k] != f[k]}
            dc = contributions[i] - contributions[oi]
            top = sorted(zip(names, map(float, dc[:-1])), key=lambda kv: abs(kv[1]), reverse=True)[:8]
            dt = r['query_epoch'] - prior['query_epoch']
            item['dt_sec'] = dt
            item['eta_change_sec'] = b['eta_seconds'] - prior['result']['eta_seconds']
            item['arrival_revision_sec'] = dt + item['eta_change_sec']
            item['same_coordinates'] = (r['vehicle']['lat'], r['vehicle']['lng']) == (prior['vehicle']['lat'], prior['vehicle']['lng'])
            changes.append(dict(vehicle_id=item['vehicle_id'], before_request=prior['request_id'],
                                after_request=r['request_id'], time_hanoi=item['time_hanoi'],
                                eta_change_sec=item['eta_change_sec'], arrival_revision_sec=item['arrival_revision_sec'],
                                delta_change_sec=mp['delta']-models[(prior['request_id'], json.dumps(prior['features'], sort_keys=True))]['delta'],
                                changed_features=diffs, tree_contribution_changes=top,
                                note='additive model explanation, not physical causality; correlated features interact'))
        rows.append(item)
        previous[item['vehicle_id']] = (i, r)
    output.mkdir(parents=True)
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with (output/'timeline.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fields); writer.writeheader(); writer.writerows(rows)
    def save(name, value):
        (output/name).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    save('packets.json', [dict(http_line=n, **r) for n, r in packets])
    save('traces.json', dict(results=results, model_predictions=list(models.values()), filtered=filtered))
    save('changes.json', changes)
    prime = [r for r in rows if r['vehicle_id'] == primary]
    constants = {k: selected[0]['features'][k] for k in names
                 if all(r['features'][k] == selected[0]['features'][k] for r in selected)}
    features = {k: dict(first=selected[0]['features'][k], last=selected[-1]['features'][k],
                       unique=len({r['features'][k] for r in selected}),
                       min=min(r['features'][k] for r in selected), max=max(r['features'][k] for r in selected)) for k in names}
    nearest = [dict(time_hanoi=r['body']['query_time'], request_id=r['request_id'],
                    buses=[dict(vehicle_id=b['vehicle_id'], eta=b['eta_seconds']) for b in r['body']['buses']])
               for _, r in packets if r['status'] == 200]
    summary = dict(scope='retrospective one-station case; not representative accuracy acceptance',
                   session=str(session), station=station, route=route, direction=chosen['direction'],
                   primary_vehicle=primary, session_prediction_sources=sources,
                   station_requests=len(packets), station_forecasts=len(rows),
                   primary_rows=len(prime), primary_arrival=arrival,
                   primary_first=prime[0], primary_last=prime[-1],
                   primary_constants=constants, all_feature_ranges=features,
                   optimistic_later_than_crossing=sum(r['optimistic_eta']>r['gps_remaining_sec'] for r in prime),
                   optimistic_max_lateness_sec=max(r['optimistic_eta']-r['gps_remaining_sec'] for r in prime),
                   optimistic_later_than_bracket_right=sum(r['query_epoch']+r['optimistic_eta']>arrival['right'] for r in prime),
                   ml_closer_than_matrix=sum(abs(r['eta_sec']-r['gps_remaining_sec']) <
                                             abs(r['baseline_sec']-r['gps_remaining_sec']) for r in prime),
                   biggest_upward_change=max(changes, key=lambda x:x['eta_change_sec']),
                   same_coordinate_transitions=sum(r.get('same_coordinates', False) for r in prime),
                   all_weights_replayed=True, prediction_tree_range=[0, end],
                   model_sha256=hashlib.sha256(weights.read_bytes()).hexdigest())
    save('summary.json', summary); save('station_queue.json', nearest)
    inventory = {}
    for path in [session/'session.json', session/'http.jsonl', session/'backend/trace.jsonl',
                 analysis/'arrivals.json', weights, Path(__file__)]:
        with path.open('rb') as stream:
            inventory[str(path)] = hashlib.file_digest(stream, 'sha256').hexdigest()
    save('source_hashes.json', inventory)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(4, 1, figsize=(12, 11), sharex=True)
    x = [(r['query_epoch']-prime[0]['query_epoch'])/60 for r in prime]
    for key, label in [('eta_sec','ML + calibration'), ('baseline_sec','Historical matrix'), ('gps_remaining_sec','GPS crossing remaining')]:
        axes[0].plot(x, [r[key] for r in prime], label=label)
    axes[0].fill_between(x, [r['p10'] for r in prime], [r['p90'] for r in prime], alpha=.15, label='Policy P10-P90')
    axes[0].set_ylabel('Seconds remaining'); axes[0].legend()
    axes[1].plot(x, [r['predicted_arrival_error_sec'] for r in prime], label='ML arrival - GPS crossing')
    axes[1].plot(x, [r['baseline_sec']-r['gps_remaining_sec'] for r in prime], label='Matrix arrival - GPS crossing')
    axes[1].axhline(0,color='black',lw=.7); axes[1].set_ylabel('Seconds late (+)'); axes[1].legend()
    for key, label in [('raw_speed','Upstream speed'),('display_speed','Displayed smoothed speed'),('ml_speed','ML rolling speed')]:
        axes[2].plot(x,[r[key] for r in prime],label=label)
    axes[2].set_ylabel('km/h'); axes[2].legend()
    axes[3].plot(x,[r['model_delta_sec'] for r in prime],label='XGB residual')
    axes[3].plot(x,[r['calibration_change_sec'] for r in prime],label='Calibration adjustment')
    axes[3].set_ylabel('Seconds'); axes[3].set_xlabel('Minutes since first station forecast'); axes[3].legend()
    for ax in axes: ax.grid(alpha=.25)
    fig.suptitle(f'Route {route}, station order {order}, vehicle {primary}; observed 2026-11-17')
    fig.tight_layout(); fig.savefig(output/'timeline.png',dpi=160); plt.close(fig)
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session', type=Path, required=True)
    parser.add_argument('--analysis', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--route', required=True)
    parser.add_argument('--station-order', type=int, required=True)
    parser.add_argument('--vehicle', type=int, required=True)
    args = parser.parse_args()
    result = analyze(args.session, args.analysis, args.output, args.route, args.station_order, args.vehicle)
    print(json.dumps({k: result[k] for k in ('station_requests','station_forecasts','primary_rows','all_weights_replayed')}))
