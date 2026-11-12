"""Pinned HF raw batches, immutable HDFS objects and retryable receive ledger."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
from uuid import uuid4

RAW_ROOT = '/bus-eta/v1/bronze/hf_raw'
LEDGER_ROOT = '/bus-eta/v1/_received/hf_batch'


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def digest(content):
    return hashlib.sha256(content).hexdigest()


def atomic_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + str(uuid4()) + '.tmp')
    with temporary.open('wb') as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def descriptor(dataset, revision, path, content):
    parts = PurePosixPath(path).parts
    if len(parts) != 4 or parts[0] != 'raw_data' or parts[2] not in ('bus', 'incidents') or not parts[3].endswith('.jsonl'):
        raise ValueError('unsupported HF batch path')
    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('revision must be a pinned HF commit')
    datetime.strptime(parts[1], '%Y-%m-%d')
    identity = dict(dataset=dataset, path=path, content_sha256=digest(content))
    return dict(identity, schema_version='hf-batch.v1', revision=revision,
                batch_id=digest(encoded(identity)), category=parts[2], bytes=len(content),
                hdfs_raw_path=f'{RAW_ROOT}/category={parts[2]}/sha256={digest(content)}/batch.jsonl')


def stage_batch(root, dataset, revision, path, content):
    metadata = descriptor(dataset, revision, path, content)
    target = Path(root) / metadata['batch_id']
    raw = target / 'batch.jsonl'
    if raw.exists() and raw.read_bytes() != content:
        raise ValueError('staged content collision')
    if not raw.exists():
        atomic_write(raw, content)
    # Retain each pinned revision as an observation of this same logical batch.
    observed = target / 'sources' / (revision + '.json')
    if observed.exists() and observed.read_bytes() != encoded(metadata):
        raise ValueError('source metadata collision')
    atomic_write(observed, encoded(metadata))
    return metadata


class DockerHdfs:
    """Host CLI transport: keep HDFS private and avoid additional exposed ports."""
    def __init__(self, compose):
        self.prefix = ['docker', 'compose', '-f', str(compose), 'exec', '-T', 'namenode', 'hdfs', 'dfs']

    def call(self, *args, content=None):
        result = subprocess.run(self.prefix + list(args), input=content, capture_output=True, timeout=40)
        if result.returncode:
            raise RuntimeError(result.stderr.decode('utf-8', errors='replace').strip())
        return result.stdout

    def exists(self, path):
        # -stat errors must not be interpreted as not-found during an outage.
        try:
            self.call('-stat', '%b', path)
            return True
        except RuntimeError as error:
            if 'No such file or directory' in str(error):
                return False
            raise

    def read(self, path):
        return self.call('-cat', path)

    def create(self, path, content):
        self.call('-mkdir', '-p', str(PurePosixPath(path).parent))
        # A killed stdin upload may leave ._COPYING_; a unique temporary name
        # prevents that partial artifact from blocking retries or becoming visible.
        temporary = path + '.upload-' + str(uuid4())
        self.call('-put', '-', temporary, content=content)
        self.call('-mv', temporary, path)


def ensure_object(store, path, content):
    if not store.exists(path):
        try:
            store.create(path, content)
        except RuntimeError:
            # Concurrent writer or interrupted response: verify before treating as success.
            if not store.exists(path):
                raise
    if store.read(path) != content:
        raise ValueError('immutable HDFS object differs: ' + path)


def receive_batch(root, metadata_path, store, failpoint=None):
    metadata_path = Path(metadata_path)
    if not metadata_path.resolve().is_relative_to(Path(root).resolve()):
        raise ValueError('source descriptor outside staging root')
    metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
    target = metadata_path.parent.parent
    content = (target / 'batch.jsonl').read_bytes()
    expected = descriptor(metadata['dataset'], metadata['revision'], metadata['path'], content)
    if metadata != expected or target.name != expected['batch_id']:
        raise ValueError('staged descriptor/hash mismatch')
    ensure_object(store, metadata['hdfs_raw_path'], content)
    if failpoint == 'after_raw':
        raise RuntimeError('injected interruption after raw upload')
    ledger = f"{LEDGER_ROOT}/{metadata['batch_id']}"
    manifest_path = ledger + '/manifest.json'
    was_received = store.exists(manifest_path)
    if was_received:
        manifest = json.loads(store.read(manifest_path))
        if {k: manifest[k] for k in metadata if k != 'revision'} != {k: v for k, v in metadata.items() if k != 'revision'}:
            raise ValueError('received manifest conflicts with batch')
    else:
        manifest = dict(metadata, received_at_utc=datetime.now(timezone.utc).isoformat())
        try:
            store.create(manifest_path, encoded(manifest))
        except RuntimeError:
            if not store.exists(manifest_path):
                raise
            manifest = json.loads(store.read(manifest_path))
            if {k: manifest[k] for k in metadata if k != 'revision'} != {k: v for k, v in metadata.items() if k != 'revision'}:
                raise ValueError('concurrent received manifest conflict')
        ensure_object(store, manifest_path, encoded(manifest))
    # Revision sightings are immutable, independent of first-received metadata.
    ensure_object(store, ledger + '/revisions/' + metadata['revision'] + '.json', encoded(metadata))
    if failpoint == 'before_receipt':
        raise RuntimeError('injected interruption before local receipt')
    receipt = dict(batch_id=metadata['batch_id'], revision=metadata['revision'], manifest_path=manifest_path,
                   content_sha256=metadata['content_sha256'], status='verified')
    atomic_write(target / 'receipts' / (metadata['revision'] + '.json'), encoded(receipt))
    return dict(receipt, already_received=was_received)
