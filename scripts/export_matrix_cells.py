import sqlite3
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

conn = sqlite3.connect('data/hanoi_bus_system.db')
cur = conn.cursor()

# Query detailed cells for Route 02 (both directions) and high-density routes
query = """
SELECT 
    route_code,
    direction,
    from_station_order,
    to_station_order,
    from_station_name,
    to_station_name,
    round(segment_distance_m, 1) as dist_m,
    time_window,
    day_type,
    sample_count,
    round(median_transit_sec, 1) as p50,
    round(p10_transit_sec, 1) as p10,
    round(p90_transit_sec, 1) as p90,
    round(p90_transit_sec - p10_transit_sec, 1) as spread,
    round((p90_transit_sec - p10_transit_sec) / median_transit_sec * 100, 1) as rel_dispersion,
    round(commercial_speed_kmh, 1) as speed_kmh,
    is_interpolated
FROM agg_segment_travel_times
WHERE route_code IN ('02', 'E01', 'BRT01', '32', '27')
ORDER BY route_code, direction, from_station_order, time_window, day_type;
"""

rows = cur.execute(query).fetchall()
conn.close()

print(f"Loaded {len(rows):,} matrix cells.")

# Build interactive HTML
html_content = """<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <title>Bảng Ma Trận Thời Gian & Độ Phân Tán (Historical Baseline Matrix)</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; margin: 20px; background: #0d1117; color: #c9d1d9; }
        h1, h2 { color: #58a6ff; }
        .controls { margin-bottom: 20px; display: flex; gap: 15px; flex-wrap: wrap; background: #161b22; padding: 15px; border-radius: 8px; border: 1px solid #30363d; }
        select, input { background: #21262d; color: #c9d1d9; border: 1px solid #30363d; padding: 8px 12px; border-radius: 6px; font-size: 14px; }
        table { width: 100%; border-collapse: collapse; font-size: 13px; background: #161b22; border-radius: 8px; overflow: hidden; }
        th, td { padding: 10px 12px; text-align: left; border-bottom: 1px solid #21262d; }
        th { background: #21262d; color: #8b949e; font-weight: 600; position: sticky; top: 0; }
        tr:hover { background: #1c2128; }
        .badge-tier0 { background: #238636; color: #fff; padding: 2px 8px; border-radius: 12px; font-size: 11px; }
        .badge-tier1 { background: #9e6a03; color: #fff; padding: 2px 8px; border-radius: 12px; font-size: 11px; }
        .badge-tier2 { background: #8b949e; color: #fff; padding: 2px 8px; border-radius: 12px; font-size: 11px; }
        .high-spread { color: #f85149; font-weight: 600; }
        .low-speed { color: #d29922; font-weight: 600; }
        .good-speed { color: #3fb950; font-weight: 600; }
        .stat-box { display: flex; gap: 20px; margin-bottom: 20px; }
        .stat-card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 12px 20px; flex: 1; }
        .stat-val { font-size: 24px; font-weight: bold; color: #58a6ff; }
        .stat-lbl { font-size: 12px; color: #8b949e; text-transform: uppercase; }
    </style>
</head>
<body>
    <h1>BẢNG CHI TIẾT CÁC Ô MA TRẬN THỜI GIAN & ĐỘ PHÂN TÁN</h1>
    <p>Trích xuất từ <code>agg_segment_travel_times</code> (5.56M telemetry pings, 48 tuyến chính tắc, 9 khung giờ, 3 loại ngày).</p>
    
    <div class="stat-box">
        <div class="stat-card">
            <div class="stat-val" id="totalRows">""" + f"{len(rows):,}" + """</div>
            <div class="stat-lbl">Số ô đang hiển thị</div>
        </div>
        <div class="stat-card">
            <div class="stat-val">35 Phân Đoạn</div>
            <div class="stat-lbl">Tuyến 02 [Chiều đi]</div>
        </div>
        <div class="stat-card">
            <div class="stat-val">84.16%</div>
            <div class="stat-lbl">Độ phủ trực tiếp (Tier 0)</div>
        </div>
        <div class="stat-card">
            <div class="stat-val">100% Thuần delta_s/delta_t</div>
            <div class="stat-lbl">Độc lập Dwell Time</div>
        </div>
    </div>

    <div class="controls">
        <div>
            <label>Tuyến:</label>
            <select id="routeFilter" onchange="filterTable()">
                <option value="02" selected>Tuyến 02 (Bác Cổ - Yên Nghĩa)</option>
                <option value="E01">Tuyến E01 (Bến xe Mỹ Đình - Ocean Park)</option>
                <option value="BRT01">Tuyến BRT01 (Kim Mã - Yên Nghĩa)</option>
                <option value="32">Tuyến 32 (Giáp Bát - Nhổn)</option>
                <option value="27">Tuyến 27 (Bến xe Yên Nghĩa - Nam Thăng Long)</option>
            </select>
        </div>
        <div>
            <label>Chiều:</label>
            <select id="dirFilter" onchange="filterTable()">
                <option value="go" selected>Chiều đi (go)</option>
                <option value="re">Chiều về (re)</option>
            </select>
        </div>
        <div>
            <label>Khung Giờ:</label>
            <select id="windowFilter" onchange="filterTable()">
                <option value="ALL">Tất cả khung giờ (9 windows)</option>
                <option value="MORNING_PEAK" selected>Cao điểm sáng (07:00 - 08:30)</option>
                <option value="MIDDAY_LULL">Thấp điểm trưa (11:30 - 13:30)</option>
                <option value="EVENING_PEAK_CORE">Cao điểm chiều (17:00 - 18:30)</option>
                <option value="EARLY_MORNING">Sáng sớm (05:00 - 06:30)</option>
                <option value="MORNING_SURGE">Trước cao điểm sáng (06:30 - 07:00)</option>
                <option value="MID_MORNING">Giữa buổi sáng (08:30 - 11:30)</option>
                <option value="EARLY_AFTERNOON">Đầu giờ chiều (13:30 - 16:30)</option>
                <option value="PRE_EVENING_PEAK">Trước cao điểm chiều (16:30 - 17:00)</option>
                <option value="LATE_EVENING_NIGHT">Đêm (18:30 - 22:30)</option>
            </select>
        </div>
        <div>
            <label>Loại Ngày:</label>
            <select id="dayFilter" onchange="filterTable()">
                <option value="WEEKDAY" selected>Ngày thường (WEEKDAY)</option>
                <option value="SATURDAY">Thứ Bảy (SATURDAY)</option>
                <option value="SUNDAY">Chủ Nhật (SUNDAY)</option>
            </select>
        </div>
        <div>
            <label>Tìm kiếm trạm:</label>
            <input type="text" id="searchFilter" placeholder="Nhập tên trạm..." onkeyup="filterTable()">
        </div>
    </div>

    <table id="matrixTable">
        <thead>
            <tr>
                <th>Đoạn</th>
                <th>Từ Trạm &rarr; Đến Trạm</th>
                <th>Cự Ly (m)</th>
                <th>Khung Giờ</th>
                <th>Mẫu (N)</th>
                <th>P10 (s)</th>
                <th>P50 (Trung vị, s)</th>
                <th>P90 (s)</th>
                <th>Độ Tản (P90-P10)</th>
                <th>Tỉ Lệ Tản (%)</th>
                <th>V_thương mại</th>
                <th>Phân Tầng</th>
            </tr>
        </thead>
        <tbody>
"""

table_rows = []
for r in rows:
    rcode, rdir, f_ord, t_ord, f_name, t_name, dist, tw, dt, cnt, p50, p10, p90, spread, rel_disp, spd, is_interp = r
    
    tier_badge = '<span class="badge-tier0">Tier 0 (Trực tiếp)</span>' if is_interp == 0 else ('<span class="badge-tier1">Tier 1 (Nội suy)</span>' if is_interp == 1 else '<span class="badge-tier2">Tier 2 (Fallback)</span>')
    spread_class = 'high-spread' if spread >= 150 else ''
    spd_class = 'low-speed' if spd <= 12.0 else ('good-speed' if spd >= 22.0 else '')
    
    table_rows.append(f"""            <tr data-route="{rcode}" data-dir="{rdir}" data-window="{tw}" data-day="{dt}" data-name="{f_name.lower()} {t_name.lower()}">
                <td><b>{f_ord} &rarr; {t_ord}</b></td>
                <td>{f_name} &rarr; <b>{t_name}</b></td>
                <td>{dist:.0f}</td>
                <td><code>{tw}</code></td>
                <td>{cnt}</td>
                <td>{p10:.1f}</td>
                <td><b style="color: #58a6ff;">{p50:.1f}</b></td>
                <td>{p90:.1f}</td>
                <td class="{spread_class}">{spread:.1f}s</td>
                <td>{rel_disp:.1f}%</td>
                <td class="{spd_class}">{spd:.1f} km/h</td>
                <td>{tier_badge}</td>
            </tr>""")

html_content += "\n".join(table_rows)
html_content += """
        </tbody>
    </table>

    <script>
        function filterTable() {
            const route = document.getElementById('routeFilter').value;
            const dir = document.getElementById('dirFilter').value;
            const win = document.getElementById('windowFilter').value;
            const day = document.getElementById('dayFilter').value;
            const search = document.getElementById('searchFilter').value.toLowerCase();
            
            const rows = document.querySelectorAll('#matrixTable tbody tr');
            let visibleCount = 0;
            
            rows.forEach(r => {
                const matchRoute = r.getAttribute('data-route') === route;
                const matchDir = r.getAttribute('data-dir') === dir;
                const matchWin = (win === 'ALL' || r.getAttribute('data-window') === win);
                const matchDay = r.getAttribute('data-day') === day;
                const matchSearch = (!search || r.getAttribute('data-name').includes(search));
                
                if (matchRoute && matchDir && matchWin && matchDay && matchSearch) {
                    r.style.display = '';
                    visibleCount++;
                } else {
                    r.style.display = 'none';
                }
            });
            
            document.getElementById('totalRows').innerText = visibleCount.toLocaleString();
        }
        filterTable();
    </script>
</body>
</html>
"""

artifact_dir = Path("C:/Users/Giang/.gemini/antigravity/brain/dd345716-d2b2-4582-9170-7c73a3b6de73")
artifact_dir.mkdir(parents=True, exist_ok=True)
out_path = artifact_dir / "matrix_dispersion_cells_table.html"
with open(out_path, "w", encoding="utf-8") as f:
    f.write(html_content)

print(f"Exported interactive HTML table to {out_path}")

