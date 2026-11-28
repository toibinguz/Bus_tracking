"""Executor-side raw validation and bounded, vehicle-independent projection."""

from .hf_bronze import descriptor
from modules.lakehouse.pipeline.silver import merge_bus, normalize_batch, project_vehicles


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
        for kind, row in normalize_batch(category, raw, manifest["batch_id"], reference):
            yield category + "_" + kind, row
        yield 'batch', dict(batch_id=manifest['batch_id'], bytes=len(raw))
