# Giai đoạn 1 — Evidence Quét Tĩnh AST (Static Hygiene)

- **Thời điểm chạy:** `2026-11-26 18:02:44+0700`
- **Số file production đã parse AST:** `74` (lỗi cú pháp: `0`).
- **Self-test detector tổng hợp:** `{'s1_detected': True, 's2_detected': True, 's3_detected': True}`.

| Hạng mục | Tổng số phát hiện |
| :--- | ---: |
| S1. Magic numbers ngưỡng miền ngoài `config/system_config.py` | `97` |
| S2. Chuỗi đường dẫn / URL / enum domain hardcode ngoài SSOT | `101` |
| S3. Khối `except Exception` / bare `except` nuốt lỗi im lặng | `34` |
| S4. Hằng số `config/system_config.py` chưa dùng trong production (`module_1..3`) | `28 / 150` |
| S4b. Hằng số `config/system_config.py` chưa dùng ở cả `module_*`, `scripts/` và `tests/` | `27 / 150` |

---

## S1. Magic Numbers ngoài `config/system_config.py`

| File | Dòng | Giá trị | Ngữ cảnh | Đoạn mã |
| :--- | ---: | ---: | :---: | :--- |
| `module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/cloud_crawler_runner.py` | `75` | `5.0` | `Compare` | `is_morning_window = (5 <= hn_time.hour < 7)` |
| `module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/cloud_crawler_runner.py` | `154` | `0.5` | `BinOp` | `raw_res = fut.result(timeout=SOCKET_TIMEOUT_SEC + SOCKET_RETRY_TIMEOUT_SEC + 0.5)` |
| `module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/device_pool.py` | `36` | `5.0` | `BinOp` | `operating_hours = max(0, min(17, hn_time.hour - 5))` |
| `module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/hf_lake_sync.py` | `64` | `200.0` | `Compare` | `return resp.getcode() == 200` |
| `module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/hf_lake_sync.py` | `347` | `200.0` | `Compare` | `if resp.getcode() == 200:` |
| `module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/hf_lake_sync.py` | `461` | `200.0` | `Compare` | `if resp.getcode() == 200:` |
| `module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/local_production_crawler.py` | `78` | `75.0` | `BinOp` | `print("=" * 75, flush=True)` |
| `module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/local_production_crawler.py` | `87` | `75.0` | `BinOp` | `print("=" * 75, flush=True)` |
| `module_1_data_ingestion_and_preprocessing/step_1_4_frenet_spatial_projection/multi_route_projector.py` | `222` | `80.0` | `BinOp` | `print("=" * 80)` |
| `module_1_data_ingestion_and_preprocessing/step_1_4_frenet_spatial_projection/multi_route_projector.py` | `281` | `80.0` | `BinOp` | `print("=" * 80)` |
| `module_1_data_ingestion_and_preprocessing/step_1_4_frenet_spatial_projection/multi_route_projector.py` | `286` | `80.0` | `BinOp` | `print("=" * 80)` |
| `module_1_data_ingestion_and_preprocessing/step_1_4_frenet_spatial_projection/route_matcher.py` | `188` | `30.0` | `Compare` | `if old and dt<=30 and move>=self.sigma:` |
| `module_1_data_ingestion_and_preprocessing/step_1_4_frenet_spatial_projection/route_matcher.py` | `168` | `10.0` | `Compare` | `if any(abs(s[i]-p.s)<10 for p in out):continue` |
| `module_1_data_ingestion_and_preprocessing/step_1_4_frenet_spatial_projection/tomtom_incident_projector.py` | `189` | `80.0` | `BinOp` | `max_allowed_span = max(100.0, 1.4 * inc_length_m + 80.0)` |
| `module_1_data_ingestion_and_preprocessing/step_1_4_frenet_spatial_projection/tomtom_incident_projector.py` | `198` | `15.0` | `Compare` | `if len(run) >= 2 and 15.0 <= span <= max_allowed_span:` |
| `module_1_data_ingestion_and_preprocessing/step_1_4_frenet_spatial_projection/tomtom_incident_projector.py` | `200` | `80.0` | `Compare` | `elif len(run) == 1 and inc_length_m <= 80.0 and avg_d <= 20.0:` |
| `module_1_data_ingestion_and_preprocessing/step_1_4_frenet_spatial_projection/tomtom_incident_projector.py` | `200` | `20.0` | `Compare` | `elif len(run) == 1 and inc_length_m <= 80.0 and avg_d <= 20.0:` |
| `module_1_data_ingestion_and_preprocessing/step_1_4_frenet_spatial_projection/tomtom_incident_projector.py` | `336` | `15.0` | `Compare` | `and abs(w[4] - coalesced[-1][4]) <= 15` |
| `module_1_data_ingestion_and_preprocessing/step_1_4_frenet_spatial_projection/tomtom_incident_projector.py` | `418` | `5.0` | `Compare` | `if overlap_len >= 5.0:` |
| `module_1_data_ingestion_and_preprocessing/step_1_4_frenet_spatial_projection/tomtom_incident_projector.py` | `293` | `300.0` | `Compare` | `eff_mag = raw_mag if raw_mag in (1, 2, 3) else (3 if delay >= 300 else (2 if delay >= 120 else 1))` |
| `module_1_data_ingestion_and_preprocessing/step_1_4_frenet_spatial_projection/tomtom_incident_projector.py` | `293` | `120.0` | `Compare` | `eff_mag = raw_mag if raw_mag in (1, 2, 3) else (3 if delay >= 300 else (2 if delay >= 120 else 1))` |
| `module_1_data_ingestion_and_preprocessing/step_1_5_busmap_canonical_migration/ingest_busmap_canonical.py` | `107` | `200.0` | `Compare` | `if min_d > 200.0:` |
| `module_1_data_ingestion_and_preprocessing/step_1_5_busmap_canonical_migration/ingest_busmap_canonical.py` | `127` | `15.0` | `BinOp` | `best_s = max(min_s + 15.0, best_s)` |
| `module_1_data_ingestion_and_preprocessing/step_1_5_busmap_canonical_migration/ingest_busmap_canonical.py` | `398` | `80.0` | `BinOp` | `print("=" * 80)` |
| `module_1_data_ingestion_and_preprocessing/step_1_5_busmap_canonical_migration/ingest_busmap_canonical.py` | `400` | `80.0` | `BinOp` | `print("=" * 80)` |
| `module_1_data_ingestion_and_preprocessing/step_1_5_busmap_canonical_migration/ingest_busmap_canonical.py` | `411` | `80.0` | `BinOp` | `print("=" * 80)` |
| `module_2_big_data_storage_and_lakehouse/step_2_2_parquet_medallion_lakehouse/lakehouse_exporter.py` | `238` | `10.0` | `BinOp` | `if idx % 10 == 0 or idx == len(routes):` |
| `module_2_big_data_storage_and_lakehouse/step_2_2_parquet_medallion_lakehouse/lakehouse_exporter.py` | `62` | `10.0` | `Compare` | `dt_val = next((p for p in parts if len(p) == 10 and re.match(r"^\d{4}-\d{2}-\d{2}$", p)), None)` |
| `module_2_big_data_storage_and_lakehouse/step_2_2_parquet_medallion_lakehouse/silver_lakehouse_auditor.py` | `31` | `80.0` | `BinOp` | `print("=" * 80)` |
| `module_2_big_data_storage_and_lakehouse/step_2_2_parquet_medallion_lakehouse/silver_lakehouse_auditor.py` | `34` | `80.0` | `BinOp` | `print("=" * 80)` |
| `module_2_big_data_storage_and_lakehouse/step_2_2_parquet_medallion_lakehouse/silver_lakehouse_auditor.py` | `102` | `80.0` | `BinOp` | `print("=" * 80)` |
| `module_2_big_data_storage_and_lakehouse/step_2_2_parquet_medallion_lakehouse/silver_lakehouse_auditor.py` | `100` | `80.0` | `BinOp` | `print("\n" + "=" * 80)` |
| `module_2_big_data_storage_and_lakehouse/step_2_4_hdfs_history/history_snapshot.py` | `34` | `90.0` | `Compare` | `if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):` |
| `module_2_big_data_storage_and_lakehouse/step_2_4_hdfs_history/history_snapshot.py` | `34` | `180.0` | `Compare` | `if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):` |
| `module_3_bus_eta_prediction/step_3_1_historical_baseline_model/baseline_matrix_builder.py` | `562` | `5.0` | `Compare` | `if wd < 5` |
| `module_3_bus_eta_prediction/step_3_1_historical_baseline_model/baseline_matrix_builder.py` | `542` | `5.0` | `Compare` | `if wd < 5` |
| `module_3_bus_eta_prediction/step_3_1_historical_baseline_model/baseline_matrix_builder.py` | `563` | `5.0` | `Compare` | `else (DAY_TYPE_SATURDAY if wd == 5 else DAY_TYPE_SUNDAY)` |
| `module_3_bus_eta_prediction/step_3_1_historical_baseline_model/baseline_matrix_builder.py` | `599` | `5.0` | `Compare` | `elif 2 <= n_hops <= 5:` |
| `module_3_bus_eta_prediction/step_3_1_historical_baseline_model/baseline_matrix_builder.py` | `543` | `5.0` | `Compare` | `else (DAY_TYPE_SATURDAY if wd == 5 else DAY_TYPE_SUNDAY)` |
| `module_3_bus_eta_prediction/step_3_1_historical_baseline_model/baseline_matrix_builder.py` | `601` | `15.0` | `Compare` | `elif 6 <= n_hops <= 15:` |
| `module_3_bus_eta_prediction/step_3_1_historical_baseline_model/baseline_matrix_builder.py` | `314` | `5.0` | `Compare` | `if wd < 5` |
| `module_3_bus_eta_prediction/step_3_1_historical_baseline_model/baseline_matrix_builder.py` | `315` | `5.0` | `Compare` | `else (DAY_TYPE_SATURDAY if wd == 5 else DAY_TYPE_SUNDAY)` |
| `module_3_bus_eta_prediction/step_3_1_historical_baseline_model/baseline_matrix_builder.py` | `411` | `0.15` | `BinOp` | `std_v = float(np.std(arr)) if len(arr) > 1 else round(0.15 * mean_v, 2)` |
| `module_3_bus_eta_prediction/step_3_2_feature_store_extractor/causal_eta.py` | `211` | `80.0` | `Compare` | `if kmh > 80:` |
| `module_3_bus_eta_prediction/step_3_2_feature_store_extractor/causal_eta.py` | `126` | `90.0` | `Compare` | `or not -90 <= o.lat <= 90 or not -180 <= o.lng <= 180` |
| `module_3_bus_eta_prediction/step_3_2_feature_store_extractor/causal_eta.py` | `126` | `180.0` | `Compare` | `or not -90 <= o.lat <= 90 or not -180 <= o.lng <= 180` |
| `module_3_bus_eta_prediction/step_3_2_feature_store_extractor/causal_eta.py` | `304` | `20.0` | `Compare` | `ahead = sorted((d, other, v) for other, d, v in candidates if other != vehicle and d > 20)` |
| `module_3_bus_eta_prediction/step_3_2_feature_store_extractor/feature_store_builder.py` | `420` | `5.0` | `Compare` | `day_type = DAY_TYPE_WEEKDAY if wd < 5 else (DAY_TYPE_SATURDAY if wd == 5 else DAY_TYPE_SUNDAY)` |
| `module_3_bus_eta_prediction/step_3_2_feature_store_extractor/feature_store_builder.py` | `461` | `20.0` | `Compare` | `if ds_fleet > 20.0:` |
| `module_3_bus_eta_prediction/step_3_2_feature_store_extractor/feature_store_builder.py` | `550` | `0.35` | `BinOp` | `w_probe = 0.35 * rec_cov_ratio` |
| `module_3_bus_eta_prediction/step_3_2_feature_store_extractor/feature_store_builder.py` | `342` | `5.0` | `BinOp` | `i_5 = max(0, i_p - 5)` |
| `module_3_bus_eta_prediction/step_3_2_feature_store_extractor/feature_store_builder.py` | `346` | `15.0` | `Compare` | `dt_accel_min = max(0.5, dt_5 / 60.0) if dt_5 >= 15.0 else 1.0` |
| `module_3_bus_eta_prediction/step_3_2_feature_store_extractor/feature_store_builder.py` | `310` | `5.0` | `BinOp` | `if s_cur < st_s_vals[0] or s_cur >= st_s_vals[-1] - 5.0:` |
| `module_3_bus_eta_prediction/step_3_2_feature_store_extractor/feature_store_builder.py` | `329` | `5.0` | `Compare` | `if 5.0 <= act_eta <= 7200.0 and (st_s_vals[tk] - s_cur) >= 30.0:` |
| `module_3_bus_eta_prediction/step_3_2_feature_store_extractor/feature_store_builder.py` | `329` | `30.0` | `Compare` | `if 5.0 <= act_eta <= 7200.0 and (st_s_vals[tk] - s_cur) >= 30.0:` |
| `module_3_bus_eta_prediction/step_3_2_feature_store_extractor/feature_store_builder.py` | `487` | `0.6` | `BinOp` | `eff_ego_mps = max(2.0, min(18.0, (0.6 * v_roll3 + 0.4 * r_base_spd_kmh) / 3.6))` |
| `module_3_bus_eta_prediction/step_3_2_feature_store_extractor/feature_store_builder.py` | `487` | `0.4` | `BinOp` | `eff_ego_mps = max(2.0, min(18.0, (0.6 * v_roll3 + 0.4 * r_base_spd_kmh) / 3.6))` |
| `module_3_bus_eta_prediction/step_3_2_feature_store_extractor/feature_store_builder.py` | `340` | `10.0` | `Compare` | `v_roll3 = min(80.0, max(0.0, ((s_cur - tr_s[i_3]) / dt_3) * 3.6 if dt_3 >= 10.0 else v_inst))` |
| `module_3_bus_eta_prediction/step_3_2_feature_store_extractor/feature_store_builder.py` | `344` | `15.0` | `Compare` | `v_roll5 = min(80.0, max(0.0, ((s_cur - tr_s[i_5]) / dt_5) * 3.6 if dt_5 >= 15.0 else v_roll3))` |
| `module_3_bus_eta_prediction/step_3_3_machine_learning_models/causal_eta_training.py` | `140` | `5.0` | `Compare` | `if not 5 <= eta <= 7200:` |
| `module_3_bus_eta_prediction/step_3_3_machine_learning_models/eta_model_trainer.py` | `620` | `20.0` | `Compare` | `if len(pruned_features) < 20:` |
| `module_3_bus_eta_prediction/step_3_3_machine_learning_models/eta_model_trainer.py` | `176` | `15.0` | `Compare` | `b[n_stations_ahead > 15] = 3` |
| `module_3_bus_eta_prediction/step_3_3_machine_learning_models/eta_model_trainer.py` | `290` | `60.0` | `Compare` | `if mean_pred > 60.0:` |
| `module_3_bus_eta_prediction/step_3_3_machine_learning_models/eta_model_trainer.py` | `174` | `5.0` | `Compare` | `b[(n_stations_ahead >= 2) & (n_stations_ahead <= 5)] = 1` |
| `module_3_bus_eta_prediction/step_3_3_machine_learning_models/eta_model_trainer.py` | `175` | `15.0` | `Compare` | `b[(n_stations_ahead >= 6) & (n_stations_ahead <= 15)] = 2` |
| `module_3_bus_eta_prediction/step_3_3_machine_learning_models/eta_model_trainer.py` | `284` | `0.5` | `BinOp` | `blended_res = 0.5 * med_res + 0.5 * mean_res` |
| `module_3_bus_eta_prediction/step_3_3_machine_learning_models/eta_model_trainer.py` | `317` | `15.0` | `BinOp` | `d_v = int((uk >> 4) & 0xF)` |
| `module_3_bus_eta_prediction/step_3_3_machine_learning_models/eta_model_trainer.py` | `318` | `15.0` | `BinOp` | `h_v = int(uk & 0xF)` |
| `module_3_bus_eta_prediction/step_3_3_machine_learning_models/eta_model_trainer.py` | `324` | `0.5` | `BinOp` | `out[mask] = 0.5 * (out[mask] * scale_factor) + 0.5 * (out[mask] + bias_shift)` |
| `module_3_bus_eta_prediction/step_3_3_machine_learning_models/eta_model_trainer.py` | `693` | `0.35` | `BinOp` | `0.65 * p50 + 0.35 * tdf["recent_corridor_tt_sum_sec"].to_numpy(dtype=np.float64),` |
| `module_3_bus_eta_prediction/step_3_3_machine_learning_models/eta_model_trainer.py` | `402` | `60.0` | `Compare` | `st["within_60s"] += int(np.sum(ae_sub <= 60.0))` |
| `module_3_bus_eta_prediction/step_3_3_machine_learning_models/eta_model_trainer.py` | `403` | `120.0` | `Compare` | `st["within_120s"] += int(np.sum(ae_sub <= 120.0))` |
| `module_3_bus_eta_prediction/step_3_3_machine_learning_models/eta_model_trainer.py` | `404` | `180.0` | `Compare` | `st["within_180s"] += int(np.sum(ae_sub <= 180.0))` |
| `module_3_bus_eta_prediction/step_3_3_machine_learning_models/plot_eta_error_distributions.py` | `468` | `0.5` | `BinOp` | `bin_centers = 0.5 * (bins[:-1] + bins[1:])` |
| `module_3_bus_eta_prediction/step_3_3_machine_learning_models/plot_eta_error_distributions.py` | `834` | `90.0` | `BinOp` | `print("=" * 90)` |
| `module_3_bus_eta_prediction/step_3_3_machine_learning_models/plot_eta_error_distributions.py` | `836` | `90.0` | `BinOp` | `print("=" * 90)` |
| `module_3_bus_eta_prediction/step_3_3_machine_learning_models/plot_eta_error_distributions.py` | `960` | `90.0` | `BinOp` | `print("=" * 90)` |
| `module_3_bus_eta_prediction/step_3_3_machine_learning_models/plot_eta_error_distributions.py` | `636` | `0.5` | `BinOp` | `ax.set_ylabel("Mật độ xác suất (Probability Density)", fontsize=font_size_base + 0.5, fontweight="semibold")` |
| `module_3_bus_eta_prediction/step_3_3_machine_learning_models/plot_eta_error_distributions.py` | `958` | `90.0` | `BinOp` | `print("\n" + "=" * 90)` |
| `module_3_bus_eta_prediction/step_3_3_machine_learning_models/plot_eta_error_distributions.py` | `246` | `10.0` | `BinOp` | `if idx % 10 == 0 or idx == total_files:` |
| `module_3_bus_eta_prediction/step_3_3_machine_learning_models/plot_eta_error_distributions.py` | `327` | `60.0` | `Compare` | `within_1m_pct = np.mean(abs_delta_t <= 60.0) * 100.0` |
| `module_3_bus_eta_prediction/step_3_3_machine_learning_models/plot_eta_error_distributions.py` | `328` | `120.0` | `Compare` | `within_2m_pct = np.mean(abs_delta_t <= 120.0) * 100.0` |
| `module_3_bus_eta_prediction/step_3_3_machine_learning_models/plot_eta_error_distributions.py` | `627` | `0.5` | `BinOp` | `fontsize=font_size_base + 0.5,` |
| `module_3_bus_eta_prediction/step_3_3_machine_learning_models/plot_eta_error_distributions.py` | `633` | `0.5` | `BinOp` | `fontsize=font_size_base + 0.5,` |
| `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/eta_policy.py` | `197` | `60.0` | `BinOp` | `display_min = int(math.ceil(eta_core / 60.0))` |
| `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/eta_policy.py` | `199` | `60.0` | `BinOp` | `opt_min = max(0, int(math.ceil(optimistic_eta / 60.0)))` |
| `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/eta_policy.py` | `241` | `60.0` | `BinOp` | `eta_minutes_precise=round(eta_core / 60.0, 1),` |
| `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/model_runtime.py` | `29` | `5.0` | `Compare` | `if n_stations_ahead <= 5:` |
| `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/model_runtime.py` | `31` | `15.0` | `Compare` | `if n_stations_ahead <= 15:` |
| `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/serving_service.py` | `832` | `5.0` | `Compare` | `day_type = 0 if now_hn.weekday() < 5 else (1 if now_hn.weekday() == 5 else 2)` |
| `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/serving_service.py` | `903` | `2700.0` | `BinOp` | `inc_exp = inc_epoch + 2700.0` |
| `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/serving_service.py` | `215` | `30.0` | `Compare` | `if bm_speed_kmh > 0.0 and (t_sample - hist[0][0]) < 30.0:` |
| `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/serving_service.py` | `242` | `15.0` | `Compare` | `if used_dt < 15.0:` |
| `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/serving_service.py` | `1098` | `2700.0` | `Compare` | `if not raw_list or (now_ep - inc_epoch) > 2700.0:` |
| `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/speed_poller.py` | `51` | `45.0` | `BinOp` | `return (4 * 60 + 45) <= hhmm < (22 * 60 + 30)` |
| `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/speed_poller.py` | `51` | `30.0` | `BinOp` | `return (4 * 60 + 45) <= hhmm < (22 * 60 + 30)` |
| `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/speed_poller.py` | `239` | `30.0` | `BinOp` | `candidates.append((route_id, dir_int, primary_anchor, prev_v, self.stale_trigger_sec + 30.0, prev_v.matched_projection[1] if prev_v.matched_projection else 0.0)` |

---

## S2. Chuỗi Đường dẫn, URL và Enum Domain ngoài SSOT

| File | Dòng | Loại | Giá trị | Đoạn mã |
| :--- | ---: | :--- | :--- | :--- |
| `module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/catalog_refresher.py` | `47` | `path_or_url` | `data/metadata/vehicles_catalog.json` | `VEHICLES_CATALOG_FILE = "data/metadata/vehicles_catalog.json"` |
| `module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/catalog_refresher.py` | `72` | `path_or_url` | `https://api.busmap.city/v2/public/busmap/route_bus_gps?regionCode=hn&routeId=` | `url = f"https://api.busmap.city/v2/public/busmap/route_bus_gps?regionCode=hn&routeId={route_id}&direction={direction}"` |
| `module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/catalog_refresher.py` | `269` | `path_or_url` | `data/metadata` | `os.makedirs("data/metadata", exist_ok=True)` |
| `module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/catalog_refresher.py` | `270` | `path_or_url` | `data/metadata/daily_catalog_health.json` | `with open("data/metadata/daily_catalog_health.json", "w", encoding="utf-8") as f:` |
| `module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/hf_lake_sync.py` | `473` | `path_or_url` | `data/telemetry_sync/raw_batches` | `target_dir: str = "data/telemetry_sync/raw_batches",` |
| `module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/hf_lake_sync.py` | `490` | `path_or_url` | `data/telemetry_sync/.temp_download` | `temp_download_dir = "data/telemetry_sync/.temp_download"` |
| `module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/hf_lake_sync.py` | `44` | `path_or_url` | `https://huggingface.co/api/datasets/` | `commit_url = f"https://huggingface.co/api/datasets/{dataset_id}/commit/main"` |
| `module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/hf_lake_sync.py` | `76` | `path_or_url` | `https://huggingface.co/datasets/` | `url = f"https://huggingface.co/datasets/{dataset_id}/raw/main/{LATEST_INCIDENTS_HF_PATH}"` |
| `module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/hf_lake_sync.py` | `96` | `path_or_url` | `https://huggingface.co/api/datasets/` | `url = f"https://huggingface.co/api/datasets/{dataset_id}/tree/main/raw_data/{date_tag}/{category}"` |
| `module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/hf_lake_sync.py` | `123` | `path_or_url` | `https://huggingface.co/datasets/` | `url = f"https://huggingface.co/datasets/{dataset_id}/raw/main/metadata/tomtom_quota_tracker.json"` |
| `module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/hf_lake_sync.py` | `327` | `path_or_url` | `https://huggingface.co/api/datasets/` | `commit_url = f"https://huggingface.co/api/datasets/{dataset_id}/commit/main"` |
| `module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/hf_lake_sync.py` | `440` | `path_or_url` | `https://huggingface.co/api/datasets/` | `commit_url = f"https://huggingface.co/api/datasets/{dataset_id}/commit/main"` |
| `module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/incident_client.py` | `38` | `path_or_url` | `https://api.tomtom.com/traffic/services/4/flowSegmentData/relative0/10/json?key=` | `url = f"https://api.tomtom.com/traffic/services/4/flowSegmentData/relative0/10/json?key={api_key}&point={lat},{lon}&unit=KMPH"` |
| `module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/incident_client.py` | `57` | `path_or_url` | `https://api.tomtom.com/traffic/services/5/incidentDetails?key=` | `raw_url = f"https://api.tomtom.com/traffic/services/5/incidentDetails?key={api_key}&bbox={bbox}&language=en-GB&fields={{incidents{{type,geometry{{type,coordinat` |
| `module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/local_production_crawler.py` | `55` | `path_or_url` | `data/metadata` | `os.makedirs("data/metadata", exist_ok=True)` |
| `module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/local_production_crawler.py` | `157` | `path_or_url` | `data/hanoi_bus_system.db` | `route_codes=load_route_code_lookup(os.environ.get("HDFS_ROUTE_DB", "data/hanoi_bus_system.db")))` |
| `module_1_data_ingestion_and_preprocessing/step_1_4_frenet_spatial_projection/multi_route_projector.py` | `93` | `domain_enum` | `go` | `direction_hints = {0: "go", 1: "re"}` |
| `module_1_data_ingestion_and_preprocessing/step_1_4_frenet_spatial_projection/multi_route_projector.py` | `93` | `domain_enum` | `re` | `direction_hints = {0: "go", 1: "re"}` |
| `module_1_data_ingestion_and_preprocessing/step_1_4_frenet_spatial_projection/multi_route_projector.py` | `198` | `domain_enum` | `go` | `shapes_by_route[r_id] = {"go": [], "re": []}` |
| `module_1_data_ingestion_and_preprocessing/step_1_4_frenet_spatial_projection/multi_route_projector.py` | `198` | `domain_enum` | `re` | `shapes_by_route[r_id] = {"go": [], "re": []}` |
| `module_1_data_ingestion_and_preprocessing/step_1_4_frenet_spatial_projection/multi_route_projector.py` | `86` | `domain_enum` | `go` | `if not pings or (not shapes.get("go") and not shapes.get("re")):` |
| `module_1_data_ingestion_and_preprocessing/step_1_4_frenet_spatial_projection/multi_route_projector.py` | `86` | `domain_enum` | `re` | `if not pings or (not shapes.get("go") and not shapes.get("re")):` |
| `module_1_data_ingestion_and_preprocessing/step_1_4_frenet_spatial_projection/projection_boundary.py` | `19` | `domain_enum` | `go` | `VALID_DIRECTIONS = frozenset({"go", "re"})` |
| `module_1_data_ingestion_and_preprocessing/step_1_4_frenet_spatial_projection/projection_boundary.py` | `19` | `domain_enum` | `re` | `VALID_DIRECTIONS = frozenset({"go", "re"})` |
| `module_1_data_ingestion_and_preprocessing/step_1_4_frenet_spatial_projection/tomtom_incident_projector.py` | `230` | `domain_enum` | `go` | `route_shapes = defaultdict(lambda: {"go": [], "re": []})` |
| `module_1_data_ingestion_and_preprocessing/step_1_4_frenet_spatial_projection/tomtom_incident_projector.py` | `230` | `domain_enum` | `re` | `route_shapes = defaultdict(lambda: {"go": [], "re": []})` |
| `module_1_data_ingestion_and_preprocessing/step_1_4_frenet_spatial_projection/tomtom_incident_projector.py` | `257` | `domain_enum` | `go` | `route_stations = defaultdict(lambda: {"go": [], "re": []})` |
| `module_1_data_ingestion_and_preprocessing/step_1_4_frenet_spatial_projection/tomtom_incident_projector.py` | `257` | `domain_enum` | `re` | `route_stations = defaultdict(lambda: {"go": [], "re": []})` |
| `module_1_data_ingestion_and_preprocessing/step_1_5_busmap_canonical_migration/ingest_busmap_canonical.py` | `219` | `domain_enum` | `go` | `d_str = "go" if bm_dir == 0 else "re"` |
| `module_1_data_ingestion_and_preprocessing/step_1_5_busmap_canonical_migration/ingest_busmap_canonical.py` | `219` | `domain_enum` | `re` | `d_str = "go" if bm_dir == 0 else "re"` |
| `module_1_data_ingestion_and_preprocessing/step_1_5_busmap_canonical_migration/ingest_busmap_canonical.py` | `278` | `domain_enum` | `go` | `if d_str == "go":` |
| `module_1_data_ingestion_and_preprocessing/step_1_5_busmap_canonical_migration/ingest_busmap_canonical.py` | `345` | `domain_enum` | `go` | `d_str = "go" if bm_dir == 0 else "re"` |
| `module_1_data_ingestion_and_preprocessing/step_1_5_busmap_canonical_migration/ingest_busmap_canonical.py` | `345` | `domain_enum` | `re` | `d_str = "go" if bm_dir == 0 else "re"` |
| `module_1_data_ingestion_and_preprocessing/step_1_5_busmap_canonical_migration/ingest_busmap_canonical.py` | `229` | `domain_enum` | `go` | `d_str = "go"` |
| `module_1_data_ingestion_and_preprocessing/step_1_5_busmap_canonical_migration/ingest_busmap_canonical.py` | `232` | `domain_enum` | `re` | `d_str = "re"` |
| `module_2_big_data_storage_and_lakehouse/step_2_1_sqlite_operational_store/db_manager.py` | `106` | `domain_enum` | `go` | `def get_route_stations(self, route_code: str, direction: str = "go") -> List[Dict[str, Any]]:` |
| `module_2_big_data_storage_and_lakehouse/step_2_2_parquet_medallion_lakehouse/silver_lakehouse_auditor.py` | `76` | `domain_enum` | `go` | `go_count += int((dirs == "go").sum())` |
| `module_2_big_data_storage_and_lakehouse/step_2_2_parquet_medallion_lakehouse/silver_lakehouse_auditor.py` | `77` | `domain_enum` | `re` | `re_count += int((dirs == "re").sum())` |
| `module_2_big_data_storage_and_lakehouse/step_2_2_parquet_medallion_lakehouse/silver_lakehouse_auditor.py` | `78` | `domain_enum` | `go` | `invalid_directions += int(((dirs != "go") & (dirs != "re")).sum())` |
| `module_2_big_data_storage_and_lakehouse/step_2_2_parquet_medallion_lakehouse/silver_lakehouse_auditor.py` | `78` | `domain_enum` | `re` | `invalid_directions += int(((dirs != "go") & (dirs != "re")).sum())` |
| `module_2_big_data_storage_and_lakehouse/step_2_4_hdfs_history/artifact_transport.py` | `13` | `path_or_url` | `http://namenode:9870` | `self.client=WebHdfsUploader('http://namenode:9870')` |
| `module_2_big_data_storage_and_lakehouse/step_2_4_hdfs_history/history_snapshot.py` | `81` | `domain_enum` | `go` | `direction_hint={0:'go', 1:'re'}.get(raw.get('direction'), 'unknown'),` |
| `module_2_big_data_storage_and_lakehouse/step_2_4_hdfs_history/history_snapshot.py` | `81` | `domain_enum` | `re` | `direction_hint={0:'go', 1:'re'}.get(raw.get('direction'), 'unknown'),` |
| `module_2_big_data_storage_and_lakehouse/step_2_4_hdfs_history/p2_transform.py` | `33` | `domain_enum` | `go` | `return "go"` |
| `module_2_big_data_storage_and_lakehouse/step_2_4_hdfs_history/p2_transform.py` | `35` | `domain_enum` | `re` | `return "re"` |
| `module_2_big_data_storage_and_lakehouse/step_2_4_hdfs_history/p2_transform.py` | `32` | `domain_enum` | `go` | `if value == 0 or value == "0" or value == "go":` |
| `module_2_big_data_storage_and_lakehouse/step_2_4_hdfs_history/p2_transform.py` | `34` | `domain_enum` | `re` | `if value == 1 or value == "1" or value == "re":` |
| `module_3_bus_eta_prediction/step_3_1_historical_baseline_model/baseline_matrix_builder.py` | `345` | `domain_enum` | `go` | `for d_str in ("go", "re"):` |
| `module_3_bus_eta_prediction/step_3_1_historical_baseline_model/baseline_matrix_builder.py` | `345` | `domain_enum` | `re` | `for d_str in ("go", "re"):` |
| `module_3_bus_eta_prediction/step_3_2_feature_store_extractor/causal_eta.py` | `146` | `domain_enum` | `go` | `points = self.data.get_shape_points(o.route_id, ('go', 're')[o.direction])` |
| `module_3_bus_eta_prediction/step_3_2_feature_store_extractor/causal_eta.py` | `146` | `domain_enum` | `re` | `points = self.data.get_shape_points(o.route_id, ('go', 're')[o.direction])` |
| `module_3_bus_eta_prediction/step_3_2_feature_store_extractor/causal_eta.py` | `241` | `domain_enum` | `go` | `self._profiles[prof_key] = self.data.get_route_profile(route_id, ('go', 're')[direction])` |
| `module_3_bus_eta_prediction/step_3_2_feature_store_extractor/causal_eta.py` | `241` | `domain_enum` | `re` | `self._profiles[prof_key] = self.data.get_route_profile(route_id, ('go', 're')[direction])` |
| `module_3_bus_eta_prediction/step_3_2_feature_store_extractor/causal_eta.py` | `114` | `domain_enum` | `go` | `self._corridors[key] = self.data.get_corridor_stations(route_id, ('go', 're')[direction])` |
| `module_3_bus_eta_prediction/step_3_2_feature_store_extractor/causal_eta.py` | `114` | `domain_enum` | `re` | `self._corridors[key] = self.data.get_corridor_stations(route_id, ('go', 're')[direction])` |
| `module_3_bus_eta_prediction/step_3_2_feature_store_extractor/feature_store_builder.py` | `188` | `domain_enum` | `go` | `for d_str in ("go", "re"):` |
| `module_3_bus_eta_prediction/step_3_2_feature_store_extractor/feature_store_builder.py` | `188` | `domain_enum` | `re` | `for d_str in ("go", "re"):` |
| `module_3_bus_eta_prediction/step_3_2_feature_store_extractor/feature_store_builder.py` | `199` | `domain_enum` | `go` | `dir_id = 0 if d_str == "go" else 1` |
| `module_3_bus_eta_prediction/step_3_3_machine_learning_models/silver_replay_trainer.py` | `59` | `domain_enum` | `go` | `if row['direction'] not in ('go', 're'):` |
| `module_3_bus_eta_prediction/step_3_3_machine_learning_models/silver_replay_trainer.py` | `59` | `domain_enum` | `re` | `if row['direction'] not in ('go', 're'):` |
| `module_3_bus_eta_prediction/step_3_3_machine_learning_models/silver_replay_trainer.py` | `89` | `domain_enum` | `go` | `if direction_str not in ('go', 're'):` |
| `module_3_bus_eta_prediction/step_3_3_machine_learning_models/silver_replay_trainer.py` | `89` | `domain_enum` | `re` | `if direction_str not in ('go', 're'):` |
| `module_3_bus_eta_prediction/step_3_3_machine_learning_models/silver_replay_trainer.py` | `65` | `domain_enum` | `re` | `yield Observation(int(row['route_id']), int(row['direction'] == 're'),` |
| `module_3_bus_eta_prediction/step_3_3_machine_learning_models/silver_replay_trainer.py` | `94` | `domain_enum` | `re` | `timeline[(int(route_id), int(direction_str == 're'))].append(` |
| `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/data_access.py` | `413` | `domain_enum` | `go` | `dir_int = 0 if dir_str == "go" else 1` |
| `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/data_access.py` | `251` | `domain_enum` | `go` | `dir_int = 0 if str(dir_str).strip().lower() == "go" else 1` |
| `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/data_access.py` | `342` | `domain_enum` | `go` | `direction=0 if dir_str == "go" else 1,` |
| `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/data_access.py` | `386` | `domain_enum` | `go` | `direction=0 if dir_str == "go" else 1,` |
| `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/dto.py` | `173` | `domain_enum` | `BINH_THUONG` | `traffic_status: str = Field(default="BINH_THUONG", description="Điều kiện giao thông: THONG_THOANG, BINH_THUONG, UN_TAC")` |
| `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/dto.py` | `234` | `domain_enum` | `go` | `return 0, "go"` |
| `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/dto.py` | `245` | `domain_enum` | `go` | `if s in ("0", "go"):` |
| `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/dto.py` | `246` | `domain_enum` | `go` | `return 0, "go"` |
| `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/dto.py` | `239` | `domain_enum` | `go` | `return 0, "go"` |
| `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/dto.py` | `247` | `domain_enum` | `re` | `elif s in ("1", "re"):` |
| `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/dto.py` | `248` | `domain_enum` | `re` | `return 1, "re"` |
| `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/dto.py` | `241` | `domain_enum` | `re` | `return 1, "re"` |
| `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/eta_policy.py` | `204` | `domain_enum` | `UN_TAC` | `traffic_status = "UN_TAC"` |
| `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/eta_policy.py` | `206` | `domain_enum` | `THONG_THOANG` | `traffic_status = "THONG_THOANG"` |
| `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/eta_policy.py` | `208` | `domain_enum` | `BINH_THUONG` | `traffic_status = "BINH_THUONG"` |
| `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/projection_tracker.py` | `34` | `domain_enum` | `go` | `shape = self._get_shape_model(route_id, "go" if dir_int == 0 else "re")` |
| `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/projection_tracker.py` | `34` | `domain_enum` | `re` | `shape = self._get_shape_model(route_id, "go" if dir_int == 0 else "re")` |
| `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/serving_service.py` | `475` | `domain_enum` | `go` | `dir_str = "go" if dir_int == 0 else "re"` |
| `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/serving_service.py` | `475` | `domain_enum` | `re` | `dir_str = "go" if dir_int == 0 else "re"` |
| `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/serving_service.py` | `1007` | `domain_enum` | `THONG_THOANG` | `traffic_cond = "THONG_THOANG"` |
| `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/serving_service.py` | `1104` | `domain_enum` | `go` | `dir_str = "go" if dir_int == 0 else "re"` |
| `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/serving_service.py` | `1104` | `domain_enum` | `re` | `dir_str = "go" if dir_int == 0 else "re"` |
| `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/serving_service.py` | `1221` | `domain_enum` | `go` | `dir_str = "go" if dir_int == 0 else "re"` |
| `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/serving_service.py` | `1221` | `domain_enum` | `re` | `dir_str = "go" if dir_int == 0 else "re"` |
| `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/serving_service.py` | `839` | `domain_enum` | `THONG_THOANG` | `"THONG_THOANG", [], "Trạm đầu bến. Xe xuất bến theo nốt điều độ.",` |
| `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/serving_service.py` | `847` | `domain_enum` | `THONG_THOANG` | `"THONG_THOANG", [], "Tuyến nằm ngoài phạm vi dự báo ETA (chưa có dữ liệu baseline hoặc mô hình khả dụng).",` |
| `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/serving_service.py` | `855` | `domain_enum` | `THONG_THOANG` | `"THONG_THOANG", [],` |
| `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/serving_service.py` | `864` | `domain_enum` | `THONG_THOANG` | `"THONG_THOANG", [], "Hiện chưa có xe trực tiếp trên tuyến này.",` |
| `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/serving_service.py` | `874` | `domain_enum` | `THONG_THOANG` | `"THONG_THOANG", [], "Đang đồng bộ hình học tuyến...",` |
| `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/serving_service.py` | `1001` | `domain_enum` | `UN_TAC` | `traffic_cond = "UN_TAC"` |
| `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/serving_service.py` | `1003` | `domain_enum` | `BINH_THUONG` | `traffic_cond = "BINH_THUONG"` |
| `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/serving_service.py` | `1005` | `domain_enum` | `THONG_THOANG` | `traffic_cond = "THONG_THOANG"` |
| `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/speed_poller.py` | `298` | `domain_enum` | `go` | `dir_str = "go" if dir_int == 0 else "re"` |
| `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/speed_poller.py` | `298` | `domain_enum` | `re` | `dir_str = "go" if dir_int == 0 else "re"` |
| `module_3_bus_eta_prediction/step_3_5_web_demo/app.py` | `57` | `path_or_url` | `https://api.busmap.city/v2/public/busmap/route_bus_gps` | `"upstream": "https://api.busmap.city/v2/public/busmap/route_bus_gps",` |
| `module_3_bus_eta_prediction/step_3_5_web_demo/app.py` | `62` | `path_or_url` | `http://127.0.0.1:8000` | `"http://127.0.0.1:8000",` |
| `module_3_bus_eta_prediction/step_3_5_web_demo/app.py` | `63` | `path_or_url` | `http://localhost:8000` | `"http://localhost:8000",` |

---

## S3. Khối `except` Nuốt lỗi Im lặng (Silent Exception Handlers)

| File | Dòng | Kiểu ngoại lệ | Thân xử lý | Ngữ cảnh |
| :--- | ---: | :--- | :--- | :--- |
| `config/system_config.py` | `335` | `Exception` | `pass` | `except Exception:` |
| `config/system_config.py` | `324` | `Exception` | `pass` | `except Exception:` |
| `module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/catalog_manager.py` | `53` | `Exception` | `return []` | `except Exception:` |
| `module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/catalog_refresher.py` | `25` | `Exception` | `pass` | `except Exception:` |
| `module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/catalog_refresher.py` | `115` | `Exception` | `return None` | `except Exception:` |
| `module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/catalog_refresher.py` | `219` | `Exception` | `pass` | `except Exception:` |
| `module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/cloud_crawler_runner.py` | `16` | `Exception` | `pass` | `except Exception:` |
| `module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/dataset_sync.py` | `15` | `Exception` | `pass` | `except Exception:` |
| `module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/hf_lake_sync.py` | `106` | `Exception` | `pass` | `except Exception:` |
| `module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/hf_lake_sync.py` | `130` | `Exception` | `pass` | `except Exception:` |
| `module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/hf_lake_sync.py` | `171` | `Exception` | `pass` | `except Exception:` |
| `module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/hf_lake_sync.py` | `318` | `Exception` | `pass` | `except Exception:` |
| `module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/incident_client.py` | `49` | `Exception` | `return None` | `except Exception:` |
| `module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/incident_client.py` | `69` | `Exception` | `return []` | `except Exception:` |
| `module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/incident_client.py` | `200` | `Exception` | `pass` | `except Exception:` |
| `module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/incident_client.py` | `152` | `Exception` | `pass` | `except Exception:` |
| `module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/incident_client.py` | `165` | `Exception` | `pass` | `except Exception:` |
| `module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/local_production_crawler.py` | `18` | `Exception` | `pass` | `except Exception:` |
| `module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/socket_client.py` | `130` | `Exception` | `return None` | `except Exception:` |
| `module_1_data_ingestion_and_preprocessing/step_1_3_telemetry_kinematic_sanitizer/bulk_ping_ingester.py` | `19` | `Exception` | `pass` | `except Exception:` |
| `module_1_data_ingestion_and_preprocessing/step_1_3_telemetry_kinematic_sanitizer/bulk_ping_ingester.py` | `155` | `Exception` | `continue` | `except Exception:` |
| `module_1_data_ingestion_and_preprocessing/step_1_3_telemetry_kinematic_sanitizer/bulk_ping_ingester.py` | `118` | `Exception` | `continue` | `except Exception:` |
| `module_1_data_ingestion_and_preprocessing/step_1_3_telemetry_kinematic_sanitizer/telemetry_sanitizer.py` | `53` | `Exception` | `pass` | `except Exception:` |
| `module_1_data_ingestion_and_preprocessing/step_1_4_frenet_spatial_projection/multi_route_projector.py` | `22` | `Exception` | `pass` | `except Exception:` |
| `module_1_data_ingestion_and_preprocessing/step_1_4_frenet_spatial_projection/tomtom_incident_projector.py` | `300` | `Exception` | `pass` | `except Exception:` |
| `module_1_data_ingestion_and_preprocessing/step_1_5_busmap_canonical_migration/ingest_busmap_canonical.py` | `22` | `Exception` | `pass` | `except Exception:` |
| `module_2_big_data_storage_and_lakehouse/step_2_1_sqlite_operational_store/db_manager.py` | `134` | `Exception` | `pass` | `except Exception:` |
| `module_2_big_data_storage_and_lakehouse/step_2_2_parquet_medallion_lakehouse/lakehouse_exporter.py` | `104` | `Exception` | `pass` | `except Exception:` |
| `module_2_big_data_storage_and_lakehouse/step_2_2_parquet_medallion_lakehouse/silver_lakehouse_auditor.py` | `20` | `Exception` | `pass` | `except Exception:` |
| `module_3_bus_eta_prediction/step_3_1_historical_baseline_model/baseline_matrix_builder.py` | `37` | `Exception` | `pass` | `except Exception:` |
| `module_3_bus_eta_prediction/step_3_2_feature_store_extractor/feature_store_builder.py` | `35` | `Exception` | `pass` | `except Exception:` |
| `module_3_bus_eta_prediction/step_3_3_machine_learning_models/eta_model_trainer.py` | `36` | `Exception` | `pass` | `except Exception:` |
| `module_3_bus_eta_prediction/step_3_3_machine_learning_models/plot_eta_error_distributions.py` | `39` | `Exception` | `pass` | `except Exception:` |
| `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/live_feed.py` | `66` | `Exception` | `pass` | `except Exception:` |

---

## S4. Hằng số `config/system_config.py` Không dùng trong Production (`module_1..3`)

| Tên hằng số | Dòng | Dùng trong `scripts/`? | Dùng trong `tests/`? |
| :--- | ---: | :---: | :---: |
| `API_KEY_FILE` | `22` | `False` | `False` |
| `LEGACY_API_KEY_FILES` | `23` | `False` | `False` |
| `HF_TOKEN_FILE` | `27` | `False` | `False` |
| `LEGACY_AUDIT_DB_PATH` | `32` | `False` | `False` |
| `TOMTOM_INCIDENT_INTERVAL_SEC` | `53` | `False` | `False` |
| `TOTAL_BOTTLENECK_NODES` | `71` | `False` | `False` |
| `MAX_MONTHLY_TOMTOM_BATCHES` | `73` | `False` | `False` |
| `OSM_TILE_SERVERS` | `78` | `False` | `False` |
| `DEFAULT_TILE_SERVER` | `132` | `False` | `False` |
| `FRENET_MIN_FORWARD_WINDOW_M` | `162` | `True` | `False` |
| `CATALOG_SCAN_PREFIXES` | `198` | `False` | `False` |
| `OPERATING_START_HOUR` | `208` | `False` | `False` |
| `OPERATING_END_HOUR` | `209` | `False` | `False` |
| `DEAD_RECKONING_TAU_HALF_LIFE_S` | `364` | `False` | `False` |
| `DEAD_RECKONING_MAX_HORIZON_S` | `365` | `False` | `False` |
| `CENTRAL_VEHICLE_RESCAN_SEC` | `384` | `False` | `False` |
| `TIMBUS_DETOUR_TRACK_MAX_M` | `385` | `False` | `False` |
| `TIMBUS_FLEET_MAX_WORKERS` | `389` | `False` | `False` |
| `MIN_PHYSICAL_CRAWL_SPEED_MPS` | `399` | `False` | `False` |
| `EGO_SPEED_WEIGHT_OBS` | `409` | `False` | `False` |
| `CONGESTION_PROP_MAX` | `410` | `False` | `False` |
| `CONGESTION_PROP_EXP` | `411` | `False` | `False` |
| `PHYS_W_PROBE` | `419` | `False` | `False` |
| `PHYS_W_EGO` | `420` | `False` | `False` |
| `PHYS_DECAY_M` | `421` | `False` | `False` |
| `PHYS_INC_DELAY_FACTOR` | `422` | `False` | `False` |
| `PHYS_INC_DELAY_CAP` | `423` | `False` | `False` |
| `NEXT_BUS_HEADWAY_HINT_TEXT` | `429` | `False` | `False` |
