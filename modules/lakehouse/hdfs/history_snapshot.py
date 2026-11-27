"""Pure HF event normalization and canonical route projection for U3."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from datetime import datetime
import math

from .contract import canonical_event_id
from .hf_bronze import encoded, digest


def normalize_bus(raw, batch_id, reference):
    import json
    try:
        value = json.loads(raw)
        if not isinstance(value,dict):
            raise ValueError('bus record must be an object')
        if value.get('provenance','observed')!='observed':
            return 'reject',dict(reason='non_observed_source',batch_id=batch_id,raw_json=raw)
        for field in ('route_id','vehicle_id'):
            candidate=value[field]
            if isinstance(candidate,bool) or int(candidate)<=0 or (not isinstance(candidate,str) and int(candidate)!=candidate):
                raise ValueError('identifiers must be positive integral values')
        route_id, vehicle_id = int(value['route_id']), int(value['vehicle_id'])
        routes = {int(k): v for k, v in reference['routes'].items()}
        if route_id not in routes:
            return 'reject', dict(reason='unknown_route', batch_id=batch_id, raw_json=raw)
        if not isinstance(value.get('device_update_time'),str) or not isinstance(value.get('crawled_at'),str):
            raise ValueError('timestamp must be an offset string')
        observed = datetime.fromisoformat(value['device_update_time'].replace('Z', '+00:00'))
        captured = datetime.fromisoformat(value['crawled_at'].replace('Z', '+00:00'))
        if observed.tzinfo is None or captured.tzinfo is None:
            raise ValueError('timezone missing')
        lat, lon = float(value['lat']), float(value['lon'])
        if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError('invalid coordinates')
        event_id = canonical_event_id(source_name='busmap', source_record_id=None, route_id=route_id,
                                     vehicle_id=vehicle_id, observed_at_epoch_ms=int(observed.timestamp()*1000), lat=lat, lon=lon)
        return 'event', dict(event_id=event_id, route_id=route_id, route_code=routes[route_id], vehicle_id=vehicle_id,
                             observed_ms=int(observed.timestamp()*1000), captured_ms=int(captured.timestamp()*1000),
                             lat=lat, lon=lon, batch_id=batch_id, raw_json=encoded(value).decode())
    except (ValueError, TypeError, KeyError, OverflowError):
        return 'reject', dict(reason='invalid_bus_fields_or_timestamp', batch_id=batch_id, raw_json=raw)


def normalize_incident(raw, batch_id):
    import json
    try:
        value = json.loads(raw)
        timestamp = datetime.fromisoformat(value['timestamp'].replace('Z','+00:00'))
        if timestamp.tzinfo is None or not value['incident_id']:
            raise ValueError('incident identity/time missing')
        canonical = encoded(value).decode()
        return 'event', dict(observation_id=digest(canonical.encode()),raw_json=canonical,batch_id=batch_id)
    except (ValueError,TypeError,KeyError,AttributeError):
        return 'reject',dict(reason='invalid_incident_fields_or_timestamp',batch_id=batch_id,raw_json=raw)


def merge_event(pair):
    event_id, observations = pair
    values = list(observations)
    selected = min(values, key=lambda row: (row['captured_ms'], row['raw_json'], row['batch_id']))
    return dict(selected, batch_ids=sorted({row['batch_id'] for row in values}))


_REFERENCE_CACHE: list[tuple[dict, dict]] = []


def _get_reference_cache(reference):
    for ref_obj, cache in _REFERENCE_CACHE:
        if ref_obj is reference:
            return cache

    stations_by_route_dir = defaultdict(lambda: defaultdict(set))
    for station in reference.get('stations', ()):
        rid = station['route_id']
        stations_by_route_dir[rid][(rid, station['station_id'])].add(station['direction'])

    lookup_by_route = {
        rid: {key: next(iter(dirs)) for key, dirs in key_map.items() if len(dirs) == 1}
        for rid, key_map in stations_by_route_dir.items()
    }
    cache = {'lookup_by_route': lookup_by_route, 'shape_models_by_route': {}}
    _REFERENCE_CACHE.append((reference, cache))
    if len(_REFERENCE_CACHE) > 2:
        _REFERENCE_CACHE.pop(0)
    return cache


def project_group(pair, reference):
    import json
    from core_cpp.native_bridge import (
        is_native_available,
        project_route_pings_native,
    )
    from modules.ingestion.projection.projection_boundary import (
        ProjectableEvent,
        ShapeProjectionModel,
        project_route_events,
    )

    route_id, values = pair
    rows = sorted(values, key=lambda r: (r['vehicle_id'], r['observed_ms'], r['event_id']))
    if not rows:
        return dict(rows=[], rejected=[], route_id=route_id, diagnostics={})

    cache = _get_reference_cache(reference)
    lookup = cache['lookup_by_route'].get(route_id, {})
    raw_shapes = reference['shapes'].get(str(route_id), {})

    parsed_raws = [json.loads(row['raw_json']) for row in rows]
    route_code = rows[0]['route_code']

    if is_native_available() and getattr(project_route_events, '__module__', '') == ProjectableEvent.__module__:
        pings = [
            (
                idx,
                row['vehicle_id'],
                raw.get('plate'),
                raw['device_update_time'],
                row['observed_ms'] / 1000.0,
                raw.get('direction'),
                row['lat'],
                row['lon'],
                raw.get('current_station_id'),
            )
            for idx, (row, raw) in enumerate(zip(rows, parsed_raws))
        ]
        native_rows = project_route_pings_native(route_id, route_code, pings, raw_shapes, lookup)
        if native_rows is not None:
            accepted_indices = {int(r[0]) for r in native_rows}
            rejected = [
                dict(reason='projection_rejected', event_id=row['event_id'], batch_id=row['batch_id'], raw_json=row['raw_json'])
                for idx, row in enumerate(rows)
                if idx not in accepted_indices
            ]
            output = []
            for r in native_rows:
                src_row = rows[int(r[0])]
                output.append(
                    {
                        'event_id': src_row['event_id'],
                        'legacy_ping_id': None,
                        'route_code': r[1],
                        'route_id': r[2],
                        'vehicle_id': r[3],
                        'plate': r[4],
                        'device_update_time': r[5],
                        'device_epoch_s': r[6],
                        'direction': r[7],
                        'lat': r[8],
                        'lon': r[9],
                        's_bus_m': r[10],
                        'cross_track_m': r[11],
                        'derived_speed_kmh': r[12],
                        'provenance': 'observed',
                        'device_epoch': r[6],
                    }
                )
            return dict(rows=output, rejected=rejected, route_id=route_id, diagnostics={})

    shape_models_by_route = cache['shape_models_by_route']
    if route_id not in shape_models_by_route:
        shape_models_by_route[route_id] = {
            direction: ShapeProjectionModel.build(shape)
            for direction, shape in raw_shapes.items()
            if shape and len(shape) >= 2
        }
    shape_models = shape_models_by_route[route_id]
    events = []
    for row, raw in zip(rows, parsed_raws):
        events.append(ProjectableEvent(event_id=row['event_id'], legacy_ping_id=None, route_id=route_id,
                      route_code=row['route_code'], vehicle_id=row['vehicle_id'], plate=raw.get('plate'),
                      device_update_time=raw['device_update_time'], device_epoch_s=row['observed_ms']/1000,
                      direction_hint={0:'go', 1:'re'}.get(raw.get('direction'), 'unknown'),
                      current_station_id=raw.get('current_station_id'), lat=row['lat'], lon=row['lon']))
    projected, diagnostics = project_route_events(
        events,
        raw_shapes,
        lookup,
        precomputed_shape_models=shape_models,
    )
    accepted = {row.event_id for row in projected}
    rejected = [dict(reason='projection_rejected', event_id=row['event_id'], batch_id=row['batch_id'], raw_json=row['raw_json']) for row in rows if row['event_id'] not in accepted]
    output = []
    for row in projected:
        value = asdict(row)
        value.update(provenance='observed', device_epoch=value['device_epoch_s'])
        output.append(value)
    return dict(rows=output, rejected=rejected, route_id=route_id, diagnostics=diagnostics)
