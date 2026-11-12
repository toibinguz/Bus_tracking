"""Pure HF event normalization and canonical route projection for U3."""
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


def project_group(pair, reference):
    import json
    from module_1_data_ingestion_and_preprocessing.step_1_4_frenet_spatial_projection.projection_boundary import ProjectableEvent, project_route_events
    route_id, values = pair
    rows = list(values)
    stations = defaultdict(set)
    for station in reference['stations']:
        if station['route_id'] == route_id:
            stations[(route_id, station['station_id'])].add(station['direction'])
    lookup = {key: next(iter(directions)) for key, directions in stations.items() if len(directions) == 1}
    events = []
    for row in rows:
        raw = json.loads(row['raw_json'])
        events.append(ProjectableEvent(event_id=row['event_id'], legacy_ping_id=None, route_id=route_id,
                      route_code=row['route_code'], vehicle_id=row['vehicle_id'], plate=raw.get('plate'),
                      device_update_time=raw['device_update_time'], device_epoch_s=row['observed_ms']/1000,
                      direction_hint={0:'go', 1:'re'}.get(raw.get('direction'), 'unknown'),
                      current_station_id=raw.get('current_station_id'), lat=row['lat'], lon=row['lon']))
    projected, diagnostics = project_route_events(events, reference['shapes'].get(str(route_id), {}), lookup)
    accepted = {row.event_id for row in projected}
    rejected = [dict(reason='projection_rejected', event_id=row['event_id'], batch_id=row['batch_id'], raw_json=row['raw_json']) for row in rows if row['event_id'] not in accepted]
    output = []
    for row in projected:
        value = asdict(row)
        value.update(provenance='observed', device_epoch=value['device_epoch_s'])
        output.append(value)
    return dict(rows=output, rejected=rejected, route_id=route_id, diagnostics=diagnostics)
