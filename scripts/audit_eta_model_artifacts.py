"""Read-only inventory of the actual serving/report model artifacts, not validation."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.model_runtime import MODEL_PATH, METADATA_PATH
from module_3_bus_eta_prediction.step_3_3_machine_learning_models.plot_eta_error_distributions import MODEL_PATH as REPORT_MODEL_PATH


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('choose a fresh output file')
    metadata_path = Path(METADATA_PATH)
    metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
    models = []
    for role, name in [('serving', MODEL_PATH), ('error_distribution_report', REPORT_MODEL_PATH)]:
        path = Path(name)
        learner = json.loads(path.read_text(encoding='utf-8'))['learner']
        features = learner['feature_names']
        expected = metadata['all_features' if role=='serving' else 'pruned_features']
        models.append(dict(role=role, file=path.relative_to(ROOT).as_posix(), sha256=sha256(path),
                           bytes=path.stat().st_size, feature_count=len(features), features=features,
                           metadata_feature_order_matches=features==expected,
                           metadata_feature_set_matches=set(features)==set(expected),
                           objective=learner['objective']['name'],
                           trees=len(learner['gradient_booster']['model']['trees'])))
    result = dict(collected_at=datetime.now(timezone.utc).isoformat(),
                  status='inventory_only_not_model_acceptance', models=models,
                  metadata=dict(file=metadata_path.relative_to(ROOT).as_posix(),sha256=sha256(metadata_path),
                                keys=sorted(metadata), calibrator_cells=len(metadata.get('calibrator',{})),
                                reported_test_rows=metadata.get('total_test_rows')),
                  unresolved=['training input/split provenance must be verified against original data',
                              'frozen route category mapping must be established, not inferred from a subset release',
                              'report/pruned scores do not certify the full serving model',
                              'label/leakage/calibration and live accuracy remain unverified'])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(status=result['status'],models=[{k:v for k,v in m.items() if k!='features'} for m in models],metadata=result['metadata'])))


if __name__ == '__main__':
    main()
