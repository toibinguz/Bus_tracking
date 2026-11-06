# BƯỚC 1.4: CHIẾU KHÔNG GIAN 1D FRENET & ĐỘNG HỌC KINEMATIC
> **Thư mục**: `module_1_data_ingestion_and_preprocessing/step_1_4_frenet_spatial_projection/`  
> **Nguyên tắc**: Linear Referencing dọc theo tim đường BusMap Canonical chính thức.  
> **Tuân thủ quy tắc**: [AGENTS.md](../../AGENTS.md) (Điều 5: Không dùng speed GPS thô).

---

## 1. MỤC TIÊU & MÔ HÌNH TOÁN

Chuyển đổi tọa độ 2D WGS84 $(lat, lon)$ rời rạc của các bản ghi xe buýt sang hệ quy chiếu cung 1D Frenet dọc tim đường:
- **$s$ (Along-Track Distance)**: Khoảng cách tích lũy tính bằng mét từ đầu bến xuất phát đến hình chiếu vuông góc của xe buýt trên tim đường.
- **$d_\perp$ (Cross-Track Error)**: Độ lệch vuông góc tính bằng mét từ tọa độ xe buýt đến đoạn tim đường gần nhất. Dùng để lọc các ping bất thường hoặc xe đi chệch tuyến ($d_\perp > 35\text{m}$).
- **$\bar{v}$ (Derived Speed)**: Vận tốc vi phân không gian - thời gian:
  $$\bar{v} = \frac{\Delta s}{\Delta t} \times 3.6 \quad (\text{km/h})$$

---

## 2. CÁC THÀNH PHẦN MÃ NGUỒN

| Tệp Mã Nguồn | Chức Năng Chính |
| :--- | :--- |
| [`multi_route_projector.py`](file:///z:/Desktop/Bus_tracking/module_1_data_ingestion_and_preprocessing/step_1_4_frenet_spatial_projection/multi_route_projector.py) | Module vector hóa (NumPy) chiếu trực giao pings GPS lên hình học tim đường `canonical_shape_master`. Lưu trữ vào bảng `route_projected_telemetry`. |

---

## 3. CÁCH CHẠY & KIỂM THỬ

```bash
python scripts/parallel_multi_route_projector.py
```

### Kết quả đầu ra:
- **Bảng `route_projected_telemetry`**: Dữ liệu telemetry đã được chiếu thành công tọa độ $s_{\text{bus}}$, $d_\perp$, vận tốc dẫn xuất $\bar{v}$.
- **View phân tích `v_bus_to_next_station`**: Tự động tính khoảng cách còn lại `remaining_m` đến trạm dừng tiếp theo cho mọi tuyến.
