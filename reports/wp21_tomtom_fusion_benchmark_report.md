# BÁO CÁO THỰC NGHIỆM ĐỐI CHUẨN MÔ HÌNH V2.0 (HOTFIXED): TÍCH HỢP ĐA NGUỒN SỰ CỐ TOMTOM (WP 2.1)

> **Ngày cập nhật**: 02/11/2026 (Bản vá Contiguous Frenet Projection & Causal Snapshot Windows)  
> **Phạm vi**: Đối chuẩn **Model A** (24 Features v1.0, Residual XGB-CQR) vs **Model B** (27 Features v2.0, Staleness-Weighted TomTom Residual XGB-CQR) trên Golden Demo Routes (`02`, `27`) với chia tách chuyến nghiêm ngặt `70% Train / 10% Calib / 20% Unseen Test`.  

## I. BẢNG TỔNG HỢP TOÀN BỘ TẬP KIỂM THỬ ĐỘC LẬP (OVERALL UNSEEN TEST SET)

| Tuyến | Số Mẫu Test | Tỷ Lệ Mẫu Có Sự Cố | Model | Point MAE | Point MdAE | Hit@60s | Độ Phủ PICP [80%] | Độ Rộng MPIW | Winkler Score |
| :---: | :---: | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Tuyến 02** | 150,568 | 22.49% | Model A (Base 24) | 40.36s | 26.56s | 77.90% | 81.76% | 135.45s | 184.57s |
| | | | **Model B (TomTom 27)** | **40.25s** | **26.47s** | **77.89%** | **81.62%** | **135.25s** | **184.19s** |
| **Tuyến 27** | 155,770 | 27.05% | Model A (Base 24) | 42.09s | 26.27s | 77.09% | 81.11% | 135.64s | 194.79s |
| | | | **Model B (TomTom 27)** | **42.02s** | **26.29s** | **77.11%** | **80.85%** | **134.82s** | **194.25s** |

## II. BẢNG PHÂN TÍCH LÁT CẮT CÓ SỰ CỐ TRÊN LỘ TRÌNH PHÍA TRƯỚC (ACTIVE CONGESTION HORIZON SLICE)

| Tuyến | Mẫu Có Sự Cố | Model | Slice MAE | Slice MdAE | Hit@60s | Slice PICP [80%] | Slice MPIW | Slice Winkler | Dịch Chuyển $\Delta P_{50}$ / $\Delta P_{90}$ |
| :---: | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Tuyến 02** | 33,865 | Model A (Không TomTom) | 57.36s | 39.88s | 65.76% | 81.26% | 189.74s | 267.62s | — |
| | | **Model B (Có TomTom)** | **56.97s** | **39.75s** | **65.78%** | **81.40%** | **190.64s** | **265.90s** | **+4.04s / +4.03s** |
| **Tuyến 27** | 42,142 | Model A (Không TomTom) | 60.08s | 41.17s | 64.08% | 80.59% | 191.65s | 277.63s | — |
| | | **Model B (Có TomTom)** | **59.83s** | **41.38s** | **64.12%** | **80.33%** | **192.22s** | **276.52s** | **+5.06s / +5.55s** |

## III. BẢNG PHÂN TÍCH LÁT CẮT MÙ XE DẪN ĐƯỜNG (LEADER BLIND-SPOT CONGESTION: `leader_info_age_sec >= 900s`)

| Tuyến | Mẫu Mù Xe Dẫn Đường | Model | Blind-Spot MAE | Blind-Spot MdAE | Hit@60s | Blind-Spot PICP | Blind-Spot MPIW | Blind-Spot Winkler | Dịch Chuyển $\Delta P_{50}$ / $\Delta P_{90}$ |
| :---: | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Tuyến 02** | 6,921 | Model A (Không TomTom) | 55.87s | 37.07s | 68.53% | 82.52% | 190.65s | 272.20s | — |
| | | **Model B (Có TomTom)** | **55.22s** | **36.66s** | **68.37%** | **83.17%** | **193.97s** | **269.48s** | **+5.38s / +6.72s** |
| **Tuyến 27** | 13,611 | Model A (Không TomTom) | 66.90s | 43.46s | 61.49% | 79.32% | 202.19s | 318.71s | — |
| | | **Model B (Có TomTom)** | **66.17s** | **43.15s** | **62.00%** | **79.49%** | **204.30s** | **316.07s** | **+5.81s / +7.29s** |

## IV. KẾT LUẬN THỰC NGHIỆM ĐỊNH LƯỢNG (SINH TỰ ĐỘNG TỪ SỐ LIỆU THỰC THI)

- **Tuyến 02**: Sau khi loại bỏ hoàn toàn lỗi `s_min=0.0`, tỷ lệ mẫu có sự cố thực trên lộ trình phía trước là `22.49%` (33,865/150,568 mẫu test). Trên lát cắt có sự cố (`Active Congestion Slice`), Model B dịch chuyển dự báo trung vị `$\Delta P_{50} = +4.04\text{s}$` và cận trên `$\Delta P_{90} = +4.03\text{s}$`, thay đổi `Slice MAE` `-0.39s` (`57.36s -> 56.97s`), `Slice PICP` `+0.14%` (`81.26% -> 81.40%`), và `Winkler Score` `-1.72s`. Đặc biệt trong chế độ mù xe dẫn đường (`Leader Blind-Spot`, $N=6,921$), Model B dịch chuyển `$\Delta P_{50} = +5.38\text{s}$`, `$\Delta P_{90} = +6.72\text{s}$`, thay đổi `Blind-Spot MAE` `-0.65s` và `Winkler Score` `-2.72s`.
- **Tuyến 27**: Sau khi loại bỏ hoàn toàn lỗi `s_min=0.0`, tỷ lệ mẫu có sự cố thực trên lộ trình phía trước là `27.05%` (42,142/155,770 mẫu test). Trên lát cắt có sự cố (`Active Congestion Slice`), Model B dịch chuyển dự báo trung vị `$\Delta P_{50} = +5.06\text{s}$` và cận trên `$\Delta P_{90} = +5.55\text{s}$`, thay đổi `Slice MAE` `-0.25s` (`60.08s -> 59.83s`), `Slice PICP` `-0.26%` (`80.59% -> 80.33%`), và `Winkler Score` `-1.11s`. Đặc biệt trong chế độ mù xe dẫn đường (`Leader Blind-Spot`, $N=13,611$), Model B dịch chuyển `$\Delta P_{50} = +5.81\text{s}$`, `$\Delta P_{90} = +7.29\text{s}$`, thay đổi `Blind-Spot MAE` `-0.73s` và `Winkler Score` `-2.64s`.
