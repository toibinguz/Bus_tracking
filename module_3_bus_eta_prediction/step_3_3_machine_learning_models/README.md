# Step 3.3: Huấn luyện & Đánh giá Mô hình ML (`step_3_3_machine_learning_models`)

- **Vai trò:** Huấn luyện mô hình XGBoost dự báo phần dư (`residual = actual_eta - baseline_eta_p50_sec`) với ràng buộc đơn điệu (`interaction_constraints` / monotone theo khoảng cách còn lại), lưu bundle `causal-eta.v1` và đánh giá trên các phân chia theo ngày.
- **Đầu vào:** `CausalFeatures` replay từ dữ liệu Silver/TimBus và `data/splits/train_test_split_v1.json`.
- **Đầu ra:** Bundle `data/models/causal_eta_v1/` (`model.json` + `manifest.json`).

## Thành phần chính

| File / Symbol | Vai trò | Input -> Output |
| --- | --- | --- |
| `causal_eta_training.py` (`ResidualETA`, `TrainingReplay`, `fit_bundle`, `metrics`) | Replay gán nhãn ETA, xây DataFrame 40 feature (monotone `-1` tốc độ, `+1` trễ TomTom), huấn luyện XGBoost residual & lưu `causal-eta.v1` | Silver/Replay -> `data/models/causal_eta_v1/` |
| `silver_replay_trainer.py` (`select_partitions`, `replay_silver`, `run`, `main`) | Nạp Silver telemetry & TomTom incidents, chạy replay nhân quả và xuất checkpoint Parquet từng tuyến (`--export-checkpoints-dir`) | Silver Parquet -> `features/*.parquet` |
| `partition_checkpoint_fitter.py` (`load_split`, `run`) | Stream checkpoint theo tuyến qua `xgb.DataIter` + `QuantileDMatrix` (`--device cuda`, `--no-valid`) để huấn luyện & đối chiếu `--reference-model` | Route feature checkpoints -> `model.json` + `manifest.json` |
| `eta_model_trainer.py` (`train_xgb_residual_model`, `StreamingEvaluator`) | Pipeline huấn luyện & hiệu chuẩn Empirical Bayes cũ (tham chiếu/tương thích) | Gold Feature Store -> Metrics/Model |
| `plot_eta_error_distributions.py` | Vẽ biểu đồ phân phối sai số và xuất bảng quantile đánh giá | Test predictions -> Figures / CSV |

## Cách chạy & Kiểm thử

```bash
python -m module_3_bus_eta_prediction.step_3_3_machine_learning_models.silver_replay_trainer --help
python -m pytest tests/module_3/test_causal_eta_training.py --basetemp=runtime/pytest_tmp -q
```
