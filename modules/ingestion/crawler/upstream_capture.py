"""Opt-in lossless response-byte capture for the local ETA validation session.

No credentials/request headers are stored. GPS payloads, public route parameters
and TimBus per-request encoding material remain available for independent decode.
"""
from datetime import datetime, timezone
from contextvars import ContextVar
import hashlib
import json
import logging
import os
from pathlib import Path
import threading
from uuid import uuid4

_lock=threading.Lock()
http_request_id=ContextVar('upstream_http_request_id',default=None)


def capture(source, params, body=None, status=None, headers=None, error=None, attachments=None, sent_at=None):
    directory=os.environ.get('ETA_UPSTREAM_RAW_DIR')
    if not directory:return
    try:
        root=Path(directory)
        files={}
        payloads=dict(attachments or {})
        if body is not None:payloads['response']=body
        with _lock:
            for kind,content in payloads.items():
                sha=hashlib.sha256(content).hexdigest()
                path=root/'objects'/source/(sha+'.bin')
                path.parent.mkdir(parents=True,exist_ok=True)
                if not path.exists():path.write_bytes(content)
                files[kind]=dict(path=path.relative_to(root).as_posix(),sha256=sha,bytes=len(content))
            excluded={'authorization','proxy-authorization','cookie','set-cookie','x-api-key'}
            safe_headers={str(k):str(v) for k,v in (headers or {}).items() if k.lower() not in excluded}
            row=dict(capture_id=str(uuid4()),source=source,params=params,sent_at=sent_at,
                     http_request_id=http_request_id.get(),
                     received_at=datetime.now(timezone.utc).isoformat(),status=status,headers=safe_headers,
                     error=error,files=files)
            root.mkdir(parents=True,exist_ok=True)
            with (root/'index.jsonl').open('a',encoding='utf-8') as stream:stream.write(json.dumps(row,ensure_ascii=False)+'\n')
        return row['capture_id']
    except (OSError,ValueError,TypeError) as exc:
        logging.getLogger(__name__).error('raw upstream capture failed: %s',exc)
        return None
