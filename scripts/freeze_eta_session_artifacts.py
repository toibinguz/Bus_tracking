"""Retain model/metadata bytes whose hashes match a captured server identity."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.model_runtime import MODEL_PATH,METADATA_PATH


def freeze(session):
    session=Path(session)
    target=session/'artifact_bundle.json'
    if target.exists():return json.loads(target.read_text())
    manifest=json.loads((session/'session.json').read_text(encoding='utf-8'))
    identity=manifest['health']['serving'].get('model',{})
    files={}
    for role,source,key in [('model',MODEL_PATH,'model_sha256'),('metadata',METADATA_PATH,'metadata_sha256')]:
        if identity.get(key) is None:continue
        content=Path(source).read_bytes();sha=hashlib.sha256(content).hexdigest()
        if sha!=identity[key]:raise ValueError('model changed; do not archive a different model as the captured one')
        path=session/'artifacts'/(role+'.json');path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(content);files[role]=dict(path=path.relative_to(session).as_posix(),sha256=sha,bytes=len(content))
    result=dict(archived_at=datetime.now(timezone.utc).isoformat(),files=files,
                versions_observed_at_archival=dict(python=platform.python_version(),
                    **{name:importlib.metadata.version(name) for name in ('xgboost','numpy','pandas','pyarrow','fastapi')}))
    target.write_text(json.dumps(result,indent=2),encoding='utf-8');return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--session',type=Path,required=True)
    print(json.dumps(freeze(parser.parse_args().session)))
