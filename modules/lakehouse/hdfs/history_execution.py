"""Executor-side raw validation and bounded, vehicle-independent projection."""
from itertools import groupby
import sys

from .hf_bronze import descriptor
from .history_snapshot import normalize_bus, normalize_incident, project_group


def read_batches(manifests, reference, max_batch_bytes):
    from .artifact_transport import PrivateWebHdfs
    store = PrivateWebHdfs()
    for manifest in manifests:
        if manifest['bytes'] > max_batch_bytes:
            raise ValueError('batch exceeds configured byte limit')
        raw = store.read(manifest['hdfs_raw_path'], max_bytes=max_batch_bytes)
        expected = descriptor(manifest['dataset'], manifest['revision'], manifest['path'], raw)
        if any(manifest[k] != value for k, value in expected.items()):
            raise ValueError('received batch metadata/hash mismatch')
        category = manifest['category']
        if category != 'traffic':
            normalize = normalize_bus if category == 'bus' else normalize_incident
            for line in raw.decode('utf-8').splitlines():
                kind, row = (normalize(line, manifest['batch_id'], reference) if category == 'bus'
                             else normalize(line, manifest['batch_id']))
                yield category + '_' + kind, row
        yield 'batch', dict(batch_id=manifest['batch_id'], bytes=len(raw))


def merge_bus(left, right):
    selected = min((left, right), key=lambda row: (row['captured_ms'], row['raw_json'], row['batch_id']))
    return dict(selected, batch_ids=sorted(set(left['batch_ids']) | set(right['batch_ids'])))


def project_vehicles(sorted_rows, reference, max_session_events):
    """Split only at a gap beyond the canonical stale threshold, never at midnight."""
    import socket
    from config.system_config import STALE_DELTA_T_MAX_SEC
    if sys.platform != 'win32':
        import resource
    def project(route_id,vehicle_id,rows):
        result = project_group((route_id, rows), reference)
        result.update(vehicle_id=vehicle_id, input_events=len(rows), executor_host=socket.gethostname(),
                      session_start_ms=rows[0]['observed_ms'],session_end_ms=rows[-1]['observed_ms'],
                      worker_peak_rss_kib=(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss if sys.platform != 'win32' else None))
        return result
    for (route_id, vehicle_id), group in groupby(sorted_rows, key=lambda pair: pair[0][:2]):
        rows = []
        for _, row in group:
            if rows and row['observed_ms']-rows[-1]['observed_ms']>STALE_DELTA_T_MAX_SEC*1000:
                yield project(route_id,vehicle_id,rows)
                rows=[]
            if len(rows) >= max_session_events:
                raise ValueError('continuous vehicle session exceeds configured event limit: %s/%s' % (route_id, vehicle_id))
            rows.append(row)
        if rows:
            yield project(route_id,vehicle_id,rows)
