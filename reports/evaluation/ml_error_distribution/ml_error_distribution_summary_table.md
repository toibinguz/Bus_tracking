# Báo cáo Đánh giá Phân phối Xác suất Sai số Mô hình ML ETA
## Held-Out Test Set (Tuần 2026-11-01 đến 2026-11-07, 47 Tuyến Xe Buýt)

Báo cáo này được sinh tự động bởi script `plot_eta_error_distributions.py` tuân thủ nghiêm ngặt đặc tả toán học tại [SPEC-32](file:///z:/Desktop/Bus_tracking/docs/specs/32_ML_EVALUATION_ERROR_DISTRIBUTION_PLOTS_SPEC.md).

### Bảng T1: Tổng hợp Tham số Thống kê và Sai số Trung tâm

| horizon_case | sample_count_N | actual_eta_median_sec | pred_eta_median_sec | time_error_mean_sec | time_error_std_sec | time_error_median_sec | mae_sec | medae_sec | pct_error_mean | pct_error_std | pct_error_median | wape_pct | pct_early_arrivals | pct_late_arrivals | within_tolerance_1m_pct | within_tolerance_2m_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| K=1 | 863,984 | 69.84 | 71.65 | -0.91 | 50.80 | -2.80 | 23.38 | 11.48 | -11.57 | 41.71 | -5.43 | 22.79 | 58.50 | 41.50 | 92.32 | 97.64 |
| K=2 | 124,490 | 194.64 | 195.44 | 2.31 | 80.43 | -3.39 | 40.69 | 23.12 | -3.58 | 25.99 | -1.83 | 15.43 | 54.46 | 45.54 | 81.71 | 94.32 |
| K=5 | 47,128 | 529.66 | 529.41 | 3.05 | 122.89 | -4.17 | 72.52 | 46.77 | -1.90 | 18.18 | -0.81 | 11.91 | 52.56 | 47.44 | 59.72 | 83.99 |
| K=10 | 50,040 | 1133.23 | 1134.41 | -9.36 | 173.91 | -12.96 | 115.79 | 80.28 | -2.03 | 14.60 | -1.18 | 9.50 | 54.57 | 45.43 | 39.23 | 66.59 |

### Bảng T2: Phân bố Phân vị Đầy đủ (Quantiles & Risk Tail Distribution)

| horizon_case | metric_variable | unit | P1 | P5 | P10 | P25 | P50 | P75 | P90 | P95 | P99 | IQR |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| K=1 | time_error_sec | seconds | -125.99 | -47.28 | -30.19 | -13.08 | -2.80 | 9.07 | 32.76 | 55.08 | 136.98 | 22.15 |
| K=1 | pct_error | % | -156.03 | -80.91 | -55.78 | -26.56 | -5.43 | 11.58 | 28.41 | 39.45 | 60.99 | 38.13 |
| K=2 | time_error_sec | seconds | -170.43 | -80.25 | -53.65 | -24.58 | -3.39 | 21.20 | 59.69 | 97.60 | 237.19 | 45.78 |
| K=2 | pct_error | % | -78.36 | -41.06 | -28.93 | -14.00 | -1.83 | 9.65 | 21.29 | 29.32 | 48.58 | 23.64 |
| K=5 | time_error_sec | seconds | -288.51 | -143.62 | -100.64 | -49.15 | -4.17 | 43.78 | 109.91 | 167.70 | 375.90 | 92.93 |
| K=5 | pct_error | % | -53.02 | -27.65 | -20.06 | -10.01 | -0.81 | 7.67 | 16.10 | 21.99 | 37.31 | 17.68 |
| K=10 | time_error_sec | seconds | -471.41 | -262.11 | -181.73 | -90.78 | -12.96 | 67.05 | 162.59 | 241.28 | 491.16 | 157.83 |
| K=10 | pct_error | % | -40.49 | -22.74 | -16.54 | -8.48 | -1.18 | 5.70 | 12.18 | 16.60 | 27.42 | 14.18 |

### Diễn giải Nghiệp vụ Giao thông Công cộng:
- **Quy ước dấu:** Độ lệch có dấu $\Delta = y_{\text{actual}} - \hat{y}_{\text{pred}}$. Xe đến trễ mang dấu dương ($+$), xe đến sớm mang dấu âm ($-$).
- **K=1 Trạm (Chuẩn bị cập bến):** MAE đạt mức cực kỳ chuẩn xác, phần lớn chuyến xe rơi vào dung sai $\pm 60$ giây.
- **K=2, K=5, K=10 Trạm:** MAE tăng dần theo số trạm do bất định tích lũy tại các giao lộ và đèn tín hiệu, nhưng tỷ lệ sai số có trọng số WAPE duy trì ổn định.
