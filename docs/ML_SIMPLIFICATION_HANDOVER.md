# Bàn giao: thu gọn model ETA theo dữ liệu app có thật

Cập nhật 18/11/2026. Phiên vừa rồi kết thúc ở bước phân tích/tài liệu; **chưa triển khai model gọn**.

## 1. Yêu cầu hiện tại của người dùng

- Người dùng cho rằng model quá nhiều đầu vào phải suy đoán, offline/serving lệch; probe có chi phí thay đổi cấu trúc app, TomTom khó tích hợp. Yêu cầu phân tích sơ bộ, bổ sung doc và handover vì context quá tải.
- Không mặc định xây đủ producer cho 54 feature. Hướng cần thảo luận tiếp là model nhỏ hơn, dùng dữ liệu thực có; chưa chốt schema mới, chưa yêu cầu train ngay trong lần này.
- Đây là bài tập lớn sinh viên; không giả định máy chạy 24/7. Code và số liệu là căn cứ, docs có thể sai. Không dùng test xanh hoặc model trả số để tuyên bố feature có ý nghĩa.

## 2. Đọc gì trước

1. [ML_FEATURE_AUDIT.md](ML_FEATURE_AUDIT.md): đọc **mục 13 trước**, sau đó mục 10 về offline/HMM; tra từng feature khi cần. Mục 11 cũ đã được chú thích: cài đủ producer không còn là ưu tiên mặc định.
2. [Số liệu feature](evidence/spec41_20261117/ml_feature_importance.json): ledger train gốc + thống kê 678 cây + SHAP trên raw cũ.
3. [HMM đã cài và giới hạn](evidence/spec41_20261117/HMM_INSTALLED_20261118.md): tránh cài lại phần đã xong hoặc coi parity vị trí là parity toàn pipeline.
4. [Spec 41](specs/41_REMAINING_COMPLETION_AND_TESTING_ISSUES_SPEC.md): chỉ tham khảo backlog rộng. Hướng thu gọn mới nằm ở mục 13 của audit; chưa đồng bộ lại toàn bộ checklist 41. Không tự thực thi mục cũ về cứu đủ 54 feature.

Không cần đọc mọi báo cáo cũ để bắt đầu. Không sửa specs 38/39/40.

## 3. Kết luận đã có bằng chứng

- Full model: `data/models/eta_xgb_global_full_54feat_r3_big.json`, 54 feature, 708 vòng lưu nhưng predict dùng 678 vòng (`best_iteration=677`). Pruned có 53 feature, bỏ `n_active_buses_on_route`.
- Ledger `feature_importance`/`family_importance` có sẵn trong metadata. Đã đối chiếu tổng gain và số split của từng feature với toàn bộ 708 vòng: khớp. Không nhầm ledger đó với số liệu tính trên 678 vòng đang dùng.
- Probe chiếm **10,491% tổng gain train**, nhưng ON đặt coverage=0, congestion=1, next_ratio=1, TT=baseline P50. Không phải chỉ thiếu vài giây warm-up; code chưa tạo traversal.
- `ego_cum_delay_vs_baseline_sec` luôn 0, có **3,242% tổng gain train**. `ego_trip_elapsed_sec` ON lấy thời gian baseline tới vị trí xe, OFF lấy elapsed từ đầu trajectory: khác ý nghĩa.
- Incidents có logic lọc/tổng hợp thật, nhưng nguồn là Parquet local được cache; không phải feed live liên tục. Không mô tả là hoàn toàn không có code, cũng không mô tả là đã tích hợp live.
- Cập nhật observation hiện đi qua đường serving/sync; chưa có hợp đồng collector độc lập bảo đảm quan sát traversal. Có thể đo một số đoạn khi chạy đủ lâu, không thể bảo đảm thông tin đó cho mỗi lần mở demo.
- Không có ablation train lại đủ chặt để nói bỏ một feature làm MAE thay đổi bao nhiêu. Gain/SHAP không trả lời được câu hỏi đó.

## 4. Những phần đã làm, không làm lại

- HMM đã nối vào online và adapter offline; đổi chiều/reset sẽ xóa state cần thiết. Core nằm tại `module_1_data_ingestion_and_preprocessing/step_1_4_frenet_spatial_projection/route_matcher.py`.
- Replay cùng đầu vào: 5.264 normalized observations, 5.106 matched, 0 lệch vị trí lõi OFF/ON. Không chứng minh adapter nguồn, lịch sử speed hay feature giống nhau.
- HTTP replay raw: 1.440 response, 4.976 forecast mới so với 4.990 cũ; 14 bị từ chối. Ca ETA từng tăng 78,38 s giữa hai gói nay giảm 0,6 s. Đây là **biến động giữa gói**, không phải giảm sai số dự báo từ 78 xuống 0,6 s.
- Gold/model cũ chưa rebuild/retrain theo HMM. OFF còn ép `np.maximum.accumulate`, speed lùi 3/5 mẫu; ON sửa ring theo best_path, dùng cửa sổ 240/405 s. Đó là các lệch cần xử lý trước khi train mới.
- HDFS là kho lịch sử/batch → SQLite/Parquet phục vụ local; không query HDFS trong từng request demo, không bắt Docker online để test chức năng khác.

## 5. Hướng đề xuất, chưa chốt triển khai

Ưu tiên giảm hợp đồng dữ liệu, chưa có lý do phải bỏ XGBoost. Thử một model residual nhỏ: geometry/horizon + calendar + baseline + một vài tốc độ và chất lượng lịch sử thật sự quan sát được. Khoảng 10–15 feature chỉ là định hướng ban đầu, không phải tiêu chí nghiệm thu hay schema đã thống nhất.

Tạm loại probe, trip elapsed/cumulative delay theo nghĩa cũ, incidents và physics chứa chúng khỏi ứng viên đầu. Fleet là nhóm mở rộng cần đo lợi ích/coverage. Không xóa feature rồi dùng lại trọng số cũ; phải có schema/model mới. Không xóa raw, dataset hay model cũ.

Bước tiếp theo hợp lý:

1. Đề xuất schema tối thiểu cụ thể, từng trường có cách tính OFF/ON, fallback/missing và dependency rõ. Chốt cách xử lý timestamp/cold start/speed trước.
2. Chứng minh feature parity bằng replay cùng tiền tố raw; kiểm tra cả nhãn arrival, gap và reset. Không lấy tương lai tạo feature; crossing nội suy chỉ dùng làm probe sau khi nhận ping chứng minh nó.
3. Pilot nhỏ có split nhân quả; baseline chỉ fit train. So model gọn, baseline matrix và model cũ trên cùng tập có nhãn, công khai coverage và nhóm dữ liệu thiếu.
4. Báo sai số theo horizon, phân phối %, biến động ETA theo thời gian, nguồn và cold start. Sau đó mới quyết định rebuild/train global tốn thời gian.

## 6. Mã và dữ liệu để tiếp tục

Đọc chọn lọc các file sau trong `module_3_bus_eta_prediction/`:

- `step_3_4_eta_serving_and_evaluation/online_features.py`: toàn bộ producer hiện tại; `_speed_features`, `build_features`, `_incident_features`, `update_observation`.
- `step_3_4_eta_serving_and_evaluation/serving_service.py`: vòng đời request/sync, chuẩn bị projection và macro speed.
- `step_3_4_eta_serving_and_evaluation/data_access.py`: baseline, route mapping, catalog, profile và cache incidents.
- `step_3_4_eta_serving_and_evaluation/model_runtime.py`: residual + baseline + calibrator; route mapping phải cùng model.
- `step_3_2_feature_store_extractor/feature_store_builder.py`: tốc độ, chia lượt, arrival, probe và nhãn offline. Code hiện tại không chứng minh provenance model cũ.
- `step_3_3_machine_learning_models/eta_model_trainer.py` và `temporal_contract.py`: schema, ledger, split/cutoff guards cho lần train mới.

Raw giữ nguyên: `runtime/eta_live_session_20261117_raw/` gồm `http.jsonl`, `backend/trace.jsonl`, artifacts model/metadata/serving.db và upstream raw. Phiên feature audit gồm **4.990 vector trước HMM**, chỉ hai tuyến 02/27, chiều re, buổi tối; không phải tập kiểm chứng tổng quát.

`scripts/audit_ml_feature_importance.py` đọc trace/model frozen, kiểm hash, tính ledger và TreeSHAP. Phải dùng mapping category trong booster khi tạo DMatrix; category subset local có thể làm sai đóng góp. Tổng SHAP+bias khớp residual với sai khác tối đa 0,000145 s. Không gọi SHAP là sai số hay đóng góp nhân quả.

Model full SHA256: `eb524de9e2838880bc9d4cc4ce0bf8f8d77024665e36bbc70b99ebf0d3034ef2`.

## 7. Test, working tree và giới hạn bàn giao

- Lần chạy full cuối của giai đoạn HMM: **192 passed, 2 failed, 11 skipped** (`runtime/hmm_install_full_final_20261118.log`). Đây không phải lần chạy lại sau mọi thay đổi tương lai.
- Fail 1: `tests/acceptance/test_eta_live_information_contract.py::test_completed_preceding_bus_traversal_changes_probe_features`, phản ánh thiếu producer thật. Nếu đổi phạm vi model thì sửa hợp đồng/test minh bạch theo schema mới; không skip/xfail để làm xanh hoặc ngụy tạo probe.
- Fail 2: `tests/test_spec21_r3_browser_cors_blackbox.py::test_r3_hostile_provider_text_renders_as_literal_dom_text`; chưa xác định nguyên nhân đầy đủ. Không tự kết luận do môi trường.
- 11 test HDFS live opt-in chưa chạy trong lần đó. Không tuyên bố toàn dự án đã nghiệm thu.
- Working tree đang có nhiều thay đổi/untracked từ các giai đoạn trước. **Chưa commit/push lần kiểm kê này.** Kiểm tra `git status` trước khi sửa; không reset/clean, không gộp mọi thay đổi thành công việc của phiên mới.
- Ba file kiểm kê mới: `docs/ML_FEATURE_AUDIT.md`, `docs/evidence/spec41_20261117/ml_feature_importance.json`, `scripts/audit_ml_feature_importance.py`. File handover này và mục 13 là phần bổ sung cuối. Chưa sửa producer hay train mới trong bước bàn giao.
- Người dùng muốn ít nghi lễ, không tự sinh architect/auditor/tester; chỉ delegate khi được yêu cầu. Báo rõ bằng chứng, phần chưa biết và quyết định cần chốt, tránh lặp giải thích để che việc chưa có kết quả.

---

## 8. Cập nhật áp dụng `causal-eta.v1` (`New48 D6`) — 18/11/2026

Đã huấn luyện và đóng gói thành công mô hình rút gọn `causal-eta.v1` (`36` feature, `max_depth=6`, `rounds=600`, `early_stopping_rounds=30`, `selected=592`, `monotone_constraints=-1` cho `ego_speed_avg_3min_kmh`, `ego_speed_avg_5min_kmh`, `lead_bus_speed_kmh`) vào `data/models/causal_eta_v1/` và nối trực tiếp qua `CausalFeatures` + `ModelRuntime` trong `serving_service.py` (giữ `MAX_POSITION_AGE = 90.0s` theo timestamp thiết bị, tuyến ngoài 48 tuyến Silver fallback sang baseline).

### 8.1. Kết quả đối chiếu toàn mạng 47 tuyến (`4.000.961` mẫu held-out test `2026-11-02..07`, tuyến `40` không có test)

| Mô hình | MAE | MedAE | P90 AE | CB_MAE | Bias |
|---|---:|---:|---:|---:|---:|
| `Baseline P50` | 161.06s | 96.25s | 373.73s | 122.25s | -8.45s |
| `Old 54-feat (Calibrated)` | 146.45s | 92.44s | **333.83s** | 114.57s | +4.52s |
| **`New48 D6 36-feat`** | **141.26s** | **84.68s** | 336.82s | **105.77s** | **-3.26s** |

- `H=1` (`182.777`): `39.95s` (`Med=21.34s`) vs Old54 `50.75s` (`32.61s`)
- `H=2–5` (`958.689`): `70.09s` (`Med=43.98s`) vs Old54 `82.40s` (`60.61s`)
- `H=6–15` (`1.696.640`): `135.26s` (`Med=91.88s`) vs Old54 `138.90s` (`96.56s`)
- `H=16+` (`1.162.855`): `224.63s` (`Med=164.06s`) vs Old54 `225.33s` (`162.46s`)

### 8.2. Bảng đóng góp 36 feature (`Total gain = 20.135.316,7`, `37.568` splits)

| Hạng | Feature | Gain (%) | Splits | Hạng | Feature | Gain (%) | Splits |
|---:|---|---:|---:|---:|---|---:|---:|
| 1 | `route_id_idx` | 16.96% | 9.416 | 19 | `baseline_eta_p90_sec` | 1.30% | 262 |
| 2 | `baseline_eta_p50_sec` | 12.44% | 606 | 20 | `baseline_eta_p10_sec` | 1.04% | 375 |
| 3 | `hour_slot` | 10.17% | 5.067 | 21 | `s_bus_m` | 1.00% | 1.191 |
| 4 | `baseline_eta_mean_minus_p50_sec` | 6.96% | 1.054 | 22 | `ego_speed_avg_3min_kmh` | 0.95% | 636 |
| 5 | `n_buses_in_corridor_ahead` | 6.34% | 265 | 23 | `progress_ratio` | 0.95% | 1.012 |
| 6 | `lead_bus_dist_ahead_m` | 5.75% | 1.152 | 24 | `dist_to_next_station_m` | 0.94% | 875 |
| 7 | `sin_time` | 5.52% | 2.020 | 25 | `baseline_tier0_frac` | 0.62% | 288 |
| 8 | `day_of_week` | 3.53% | 1.377 | 26 | `current_station_order` | 0.50% | 555 |
| 9 | `baseline_eta_rss_std_sec` | 2.90% | 1.227 | 27 | `route_base_speed_kmh` | 0.47% | 408 |
| 10 | `cos_time` | 2.79% | 1.465 | 28 | `direction_id` | 0.41% | 322 |
| 11 | `baseline_max_seg_p90_sec` | 2.76% | 1.869 | 29 | `ego_speed_avg_5min_kmh` | 0.39% | 336 |
| 12 | `n_stations_ahead` | 2.56% | 271 | 30 | `route_station_spacing_m` | 0.35% | 302 |
| 13 | `lead_bus_speed_ratio` | 2.43% | 740 | 31 | `target_progress_ratio` | 0.31% | 366 |
| 14 | `follow_bus_dist_behind_m` | 2.24% | 533 | 32 | `s_target_m` | 0.28% | 343 |
| 15 | `day_type` | 2.07% | 675 | 33 | `lead_bus_speed_kmh` | 0.24% | 193 |
| 16 | `n_active_buses_on_route` | 1.55% | 506 | 34 | `baseline_eta_mean_sec` | 0.19% | 171 |
| 17 | `baseline_eta_p90_minus_p10_sec` | 1.41% | 608 | 35 | `follow_bus_speed_kmh` | 0.18% | 225 |
| 18 | `remaining_distance_m` | 1.35% | 593 | 36 | `target_station_order` | 0.16% | 264 |

### 8.3. Ghi chú việc làm sau
- **Tăng cường dữ liệu bản production:** Gộp `train + validation` cũ (`8.607.577` dòng) làm `train` và tuần `2026-11-02..07` (`4.000.961` dòng) làm `validation` để fit lại bản nâng cấp (hoãn thực hiện sau khi hoàn tất refactor/pipeline).
- **Pruning (tùy chọn sau):** 7–8 biến cuối có tổng gain ~`1.7%`; chỉ bỏ kèm retrain + ablation kiểm chứng trên tập test.
