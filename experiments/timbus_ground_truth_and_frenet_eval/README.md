# Thư Mục Thử Nghiệm: TimBus API Reverse-Engineering & Chiếu Hóa Frenet
> Thư mục này chứa các script thử nghiệm ad-hoc, thăm dò gói tin và phân tích số liệu không gian phục vụ việc phát hiện TimBus Ground Truth và đối soát hình học Tuyến 02.

## Danh Sách Các Script Thử Nghiệm:
1. `check_timbus.py`, `fetch_transerco_js.py`, `find_ashx_snippets.py`, `find_timbus_acts.py`: Giải mã gói tin AJAX và frontend `transerco2.js` của cổng `timbus.vn`.
2. `test_timbus_api.py`, `test_searchfull.py`: Kiểm thử các endpoint `fleetdetail` và `searchfull` của TimBus.
3. `compare_all_routes.py`: Đối soát danh mục 165 tuyến TimBus vs 230 tuyến BusMap.
4. `run_route_02_projection_and_audit.py`: Chạy chiếu hóa Frenet 23.258 pings và tái đánh giá sai số trạm / tim đường.
5. `check_station_dwell_detail.py`: Phân tích chuyên sâu 1.152 sự kiện dừng đỗ đón trả khách (dwell time).
6. `generate_comparison_map.py`: Tạo bản đồ tương tác Leaflet đối soát đa nguồn (`route_02_ground_truth_comparison.html`).
7. `verify_ingestion_audit.py`: Kiểm tra tính toàn vẹn và bảng kiểm toán dữ liệu SQLite.

