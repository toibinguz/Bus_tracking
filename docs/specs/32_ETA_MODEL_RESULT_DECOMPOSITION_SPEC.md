# SPEC-32: Diễn giải kết quả ETA theo khoảng trạm và phân phối sai số

**Status:** proposed; no implementation is implied by this document.  
**Date:** 2026-11-10  
**Owner:** `@architect`  
**Scope:** Đánh giá offline trên feature-store test độc lập. Không thay đổi cách train, không đổi model, và không suy diễn năng lực online từ kết quả này.

## 1. Quyết định và câu hỏi được trả lời

MAE toàn cục không trả lời được người dùng sẽ nhận ETA tốt đến đâu khi xe còn một, hai, hay nhiều trạm. Báo cáo đánh giá phải được mở rộng từ một số tổng hợp thành một **bảng sai số có điều kiện** theo số đoạn trạm thực sự còn lại.

Mỗi dòng feature-store đã có:

- `actual_eta_sec`: nhãn ETA quan sát dùng để chấm điểm;
- `n_stations_ahead = target_station_order - current_station_order`: số **đoạn giữa hai trạm liên tiếp** còn phải đi, không phải số kilomet và không phải số lần GPS ping;
- `remaining_distance_m`, `route_code`, `direction`, `dt`, đặc trưng thời gian và các dự báo của model.

Do đó có thể nói chính xác: “còn `k` đoạn trạm theo canonical station order”. Không được gọi `k` là “k trạm” nếu không giải thích quy ước này; trong phần trình bày cho người dùng có thể dùng “còn k chặng/trạm kế tiếp”, kèm chú thích kỹ thuật trên.

## 2. Nguồn chân lý, phạm vi và điều kiện đủ

| Thành phần | Nguồn bắt buộc | Trạng thái hiện tại |
| --- | --- | --- |
| Test rows | `data/lakehouse/gold/eta_feature_store/split=test/route_code=*/part-00000.snappy.parquet` | Có; split độc lập từ 2026-11-01 đến 2026-11-07 theo `config/system_config.py` |
| Nhãn/bucket | `actual_eta_sec`, `n_stations_ahead`, `remaining_distance_m` trong Parquet | Có |
| Model 6 | `data/models/eta_xgb_global_pruned.json` và metadata tương ứng | Có, **global**, không phải model riêng từng tuyến |
| Cách suy luận | `predict_eta_with_residual_model` trong `eta_model_trainer.py` | Có |
| Bảng tổng hợp đang có | `summary_metrics` trong metadata model | Có 4 bucket rộng; chưa có phân rã 1, 2, 3--5, 6--10, 11--15 hay phân phối đầy đủ |
| Prediction-level ledger | Parquet/CSV chứa `actual`, `prediction`, signed error cho từng hàng test | Chưa có; phải sinh trước khi công bố bảng mới |

Một báo cáo số mới chỉ hợp lệ khi lưu cả prediction ledger có khóa tái lập (model SHA-256, hash input file manifest, version script, thời điểm chạy) và số dòng ledger đúng với số dòng đã chấm điểm. Không chạy lại training để làm phân tích này.

## 3. Cách chia horizon

Các bucket là rời nhau, phủ hết các hàng đủ điều kiện (`n_stations_ahead >= 1`):

| Mã | Điều kiện | Nhãn trình bày |
| --- | --- | --- |
| H1 | `n_stations_ahead == 1` | 1 chặng còn lại |
| H2 | `== 2` | 2 chặng còn lại |
| H3_5 | `3 <= n_stations_ahead <= 5` | 3--5 chặng |
| H6_10 | `6 <= n_stations_ahead <= 10` | 6--10 chặng |
| H11_15 | `11 <= n_stations_ahead <= 15` | 11--15 chặng |
| HGT15 | `> 15` | trên 15 chặng |
| ALL | tất cả hàng hợp lệ | toàn bộ |

H1 và H2 là các câu trả lời trực tiếp cho “một/hai trạm”; H3_5, H6_10, H11_15 trả lời các mốc 5/10/15 mà không tự ý coi 5, 10, 15 là một quan sát đơn lẻ. Có thể thêm hàng đúng `== 5`, `== 10`, `== 15` **chỉ khi** mỗi hàng có ít nhất 1,000 quan sát và vẫn phải báo `N`.

## 4. Định nghĩa số liệu (dùng một quy ước duy nhất)

Với một hàng `i`, `y_i = actual_eta_sec`, `p_i = prediction_sec`, `e_i = p_i - y_i`, `a_i = |e_i|`:

| Nhóm | Công thức / quy tắc | Ý nghĩa |
| --- | --- | --- |
| N | số hàng trong bucket | độ lớn bằng chứng; luôn in cùng metric |
| MAE (s) | `mean(a_i)` | lệch tuyệt đối trung bình theo giây |
| MdAE, P75/P90/P95 AE (s) | percentile của `a_i` trên **toàn bộ** rows bucket | lỗi điển hình và rủi ro đuôi; không dùng reservoir 10% như evaluator cũ |
| RMSE (s) | `sqrt(mean(e_i^2))` | nhạy với sai số rất lớn |
| Bias (s) | `mean(e_i)` | dương = dự báo trễ hơn thực tế; âm = dự báo sớm hơn thực tế |
| Signed median (s) | `median(e_i)` | hướng lệch điển hình, ít nhạy ngoại lệ |
| WAPE (%) | `100 * sum(a_i) / sum(y_i)` | tỷ lệ sai lệch toàn bucket, có trọng số ETA thực; metric phần trăm chính |
| sMAPE (%) | `100 * mean(2*a_i/(abs(y_i)+abs(p_i)))` | phần trăm theo từng hàng, chặn tại 200%; báo bổ sung |
| MAPE-30 (%) | `100 * mean(a_i/max(30,y_i))` | chỉ để so sánh continuity với evaluator hiện hữu; **không** gọi là MAPE thuần |
| Coverage t (%, t=30/60/120/180 s) | `100 * mean(a_i <= t)` | xác suất ETA rơi trong ngưỡng người dùng hiểu được |
| Over/under (%) | `100 * mean(e_i>0)` / `100 * mean(e_i<0)` | phát hiện lệch hệ thống; bằng 0 không tính hai lần |
| R² | `1 - sum(e_i²)/sum((y_i-mean(y))²)` | chỉ báo độ giải thích trong bucket; ghi N/A nếu mẫu không có phương sai |

Không chia phần trăm lỗi cho ETA thực khi `y_i` nhỏ mà không nêu điều kiện: MAPE-30 là quy ước hiện hữu nhằm tránh mẫu ETA rất ngắn chi phối. WAPE và sMAPE là hai số liệu chính cho thông điệp “lệch bao nhiêu phần trăm”.

## 5. Bảng, hình bắt buộc trong báo cáo

### T1 — Hiệu năng Model 6 theo số chặng

Mỗi hàng H1, H2, H3_5, H6_10, H11_15, HGT15, ALL; cột: `N`, median actual ETA (s), MAE, MdAE, P90 AE, P95 AE, bias, WAPE, sMAPE, coverage 60/120/180 s. Đây là bảng chính để chuyển MAE thành ý nghĩa vận hành.

### T2 — Phân phối toàn test

Phân phối `a_i` với các bin cố định `[0,15]`, `(15,30]`, `(30,60]`, `(60,120]`, `(120,180]`, `(180,300]`, `(300,600]`, `>600` giây: đếm, phần trăm, phần trăm tích lũy. Bảng này không được thay bằng biểu đồ nếu người đọc cần số.

### T3 — Bias và coverage theo tuyến/horizon

Chỉ liệt kê `(route_code, direction, horizon)` có `N >= 1,000`; cột N, MAE, WAPE, bias, coverage 120 s. Sắp theo MAE giảm dần, báo top/bottom 10 và thêm file phụ lục đầy đủ. Không kết luận một tuyến “tệ” khi N dưới ngưỡng.

### T4 — So sánh mô hình có ý nghĩa

Với cùng ledger rows và từng horizon: Baseline P50, Model 4 global full, Model 6 global pruned. Báo MAE/WAPE/coverage 120 s và chênh `Model6 - Baseline`; không so sánh Model 6 với một model train khác split.

### F1/F2/F3

1. ECDF của absolute error cho H1, H2, H3_5, H6_10, H11_15, HGT15.
2. Stacked bar theo T2 (toàn test và theo horizon) để thấy đuôi sai số.
3. Reliability plot: decile dự báo ETA `p_i`, trung bình actual `y_i`, kèm N mỗi decile; đường `y=x` chỉ là tham chiếu.

Hình phải xuất PNG/SVG và bảng dữ liệu CSV tương ứng. Không dùng biểu đồ smoothing làm thay đổi giá trị.

## 6. Bất định, kiểm tra và ngưỡng công bố

1. Report MAE/WAPE 95% CI bootstrap theo **vehicle-trip hoặc route-day**, không bootstrap độc lập từng hàng ping (các hàng trong một hành trình phụ thuộc). Nếu không có trip key đủ tin cậy, ghi `CI: N/A — correlation-aware unit not materialized`; không công bố CI giả.
2. Bucket/tuyến có `N < 1,000` được in nhưng metric là `insufficient N`; không xếp hạng, không diễn giải phần trăm.
3. Kiểm tra accounting: tổng N sáu bucket bằng ALL; không có `prediction < 5`; không có `actual <= 0`; prediction ledger row count bằng input count sau điều kiện rõ ràng.
4. Kiểm tra cùng snapshot: hash model, list/hash mọi Parquet source, model feature list và `eta_model_trainer.py` SHA-256 phải vào manifest.
5. Rà trước khi xuất: zero/negative elapsed, NaN/Inf, directions không hợp lệ, data leakage qua split date. Rows bị loại phải có `rejection_reason` và đếm theo lý do.

## 7. Phân tích phụ được phép (không thay bảng chính)

- **Khoảng cách:** bucket `remaining_distance_m` theo các quantile tính trên test (`Q1..Q4`), không hard-code kilomet vì tuyến không đồng nhất. Báo ngưỡng m thực tế trong manifest.
- **Thời gian:** weekday/weekend và hour slot đã có; chỉ công bố cell `N >= 1,000`.
- **Dữ liệu động:** `recent_seg_coverage_ratio` thấp/cao theo median được tính từ test; xem hiệu năng khi probe ít/có dữ liệu.
- **Sự cố:** `inc_ahead_count==0` so với `>0`; chỉ nếu cả hai nhóm vượt ngưỡng N.
- **Feature attribution:** gain ledger mô tả cách XGBoost dùng feature, không chứng minh quan hệ nhân quả và không phải độ quan trọng đối với ETA ngoài tập này.

Không được báo “lệch theo % mỗi trạm” bằng `MAE / n_stations_ahead`: đó là chỉ số không có ý nghĩa vì thời gian chờ/độ dài đoạn không tuyến tính. Nếu cần trực giác, báo median actual ETA và WAPE theo bucket.

## 8. Kế hoạch đo tái lập

### 8.1 Artifact mới bắt buộc

Một evaluator đọc từng `split=test/route_code=*/part-00000.snappy.parquet`, gọi đúng model/feature preprocessing đã lưu, và ghi:

```text
data/evaluation/eta_model6/<run_id>/
  manifest.json
  predictions.parquet              # route, direction, dt, vehicle/time key nếu có,
                                   # n_stations_ahead, remaining_distance_m,
                                   # actual_eta_sec, prediction_sec, signed_error_sec, abs_error_sec
  horizon_metrics.csv              # T1
  error_distribution.csv           # T2
  route_direction_horizon.csv      # T3
  model_comparison.csv             # T4
  calibration_deciles.csv
  plots/*.png or *.svg
  run.log
```

`run_id` chứa UTC timestamp + 8 ký tự SHA model. Artifact này là output đánh giá, không là output huấn luyện và không được ghi đè artifact cũ.

### 8.2 Pseudocode bắt buộc

```text
load model metadata and SHA-256 model file
for each sorted test route parquet:
    validate required columns and split date
    predict Model 6 using saved pruned_features
    append one ledger row per valid input row
validate count/buckets/finite values
derive T1..T4, calibration and distribution from ledger
write immutable manifest with input file list/hash and all counts
```

Model 6 pruned feature list phải lấy từ metadata artifact, không import danh sách features đang có trong source rồi giả định nó trùng artifact.

## 9. Những gì hiện có thể nói, và những gì chưa thể nói

Hiện metadata có 4 bucket rộng `1`, `2--5`, `6--15`, `>15`, có N, MAE/MdAE/RMSE/P90 AE, MAPE-30, R² và coverage cho nhiều estimator. Đây là bằng chứng rằng số đoạn trạm và full held-out evaluation đã tồn tại.

Tuy nhiên evaluator hiện tại lấy MdAE/P90 từ reservoir subsample, không viết prediction ledger, và không có H2/3--5/6--10/11--15, bias, WAPE, sMAPE, phân phối đầy đủ hoặc CI. Vì vậy các số chi tiết người dùng yêu cầu hiện là **N/A — not measured**, không được nội suy từ MAE toàn cục.

## 10. Acceptance criteria

1. Prediction ledger cho Model 6 có manifest, model/input hashes, source split và đủ số row kiểm toán.
2. T1--T4/F1--F3 xuất được từ ledger; mọi bảng có N và ghi rõ bucket/đơn vị.
3. Accounting, finite-value, no-leakage và rejection checks pass; kết quả nói rõ mẫu loại bỏ.
4. Mọi cell dưới `N=1,000` bị đánh dấu và không bị xếp hạng.
5. Báo cáo và UI (nếu có) dùng các thuật ngữ “global Model 6” và “số đoạn trạm còn lại”; không khẳng định production/online accuracy.

