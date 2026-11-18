"""
CLI Wrapper for Step 3.4: Train & Evaluate Multi-Route XGBoost ETA Models (TD-22).
"""

import os
import sys

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, BASE_DIR)

if __name__ == "__main__":
    import argparse
    parser=argparse.ArgumentParser(description='Train/evaluate with verified feature provenance and fresh output')
    parser.add_argument('--features',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--max-fit-rows-per-route',type=int,default=55000)
    parser.add_argument('--threads',type=int,default=2)
    args=parser.parse_args()
    if min(args.max_fit_rows_per_route,args.threads)<1:parser.error('fit-row/thread limits must be positive')
    os.environ['ETA_TRAIN_THREADS']=str(args.threads)
    from module_3_bus_eta_prediction.step_3_3_machine_learning_models import eta_model_trainer as trainer
    trainer.GOLD_FEATURE_DIR=args.features;trainer.MODEL_OUT_DIR=args.output
    trainer.ETA_MAX_FIT_ROWS_PER_ROUTE=args.max_fit_rows_per_route
    trainer.run_step_3_4_ml_training_and_evaluation()
