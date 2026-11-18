"""Opt-in local JSONL trace for reproducing an ETA request, never an ingest path."""
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import threading

request_id = ContextVar('eta_request_id', default=None)
_lock = threading.Lock()


def record(kind, **payload):
    directory = os.environ.get('ETA_TRACE_DIR')
    if not directory:
        return
    row = dict(kind=kind, request_id=request_id.get(), recorded_at=datetime.now(timezone.utc).isoformat(), **payload)
    path = Path(directory)/'trace.jsonl'
    try:
        encoded=json.dumps(row, ensure_ascii=False, allow_nan=False)+'\n'
        with _lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('a', encoding='utf-8') as stream:
                stream.write(encoded)
        return True
    except (OSError, ValueError, TypeError) as error:
        # Diagnostics must never turn a valid prediction into a model fallback.
        logging.getLogger(__name__).error('ETA trace failed (%s): %s',kind,error)
        return False
