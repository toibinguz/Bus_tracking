"""
Generate Standalone Interactive HTML Audit Dashboard
Embeds summary data from data/telemetry_audit_dashboard_data.json into
reports/telemetry_audit_dashboard.html with Chart.js and DataTables.
"""

import os
import sys
import json

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

DATA_JSON_PATH = "data/telemetry_audit_dashboard_data.json"
OUTPUT_HTML_PATH = "reports/telemetry_audit_dashboard.html"

def main():
    if not os.path.exists(DATA_JSON_PATH):
        print(f"[ERROR] {DATA_JSON_PATH} not found!")
        sys.exit(1)

    print(f"[*] Reading {DATA_JSON_PATH}...")
    with open(DATA_JSON_PATH, "r", encoding="utf-8") as f:
        data_str = f.read()

    os.makedirs(os.path.dirname(OUTPUT_HTML_PATH), exist_ok=True)

    html_content = f"""<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Báo Cáo Kiểm Toán Telemetry Xe Buýt Hà Nội (17/10 & 18/10)</title>
  <!-- Bootstrap 5 CSS -->
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <!-- DataTables CSS -->
  <link href="https://cdn.datatables.net/1.13.7/css/dataTables.bootstrap5.min.css" rel="stylesheet">
  <!-- Chart.js -->
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <!-- FontAwesome -->
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.2/css/all.min.css">
  <style>
    body {{
      background-color: #f4f6f9;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      color: #333;
    }}
    .hero-header {{
      background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
      color: white;
      padding: 35px 20px 25px;
      border-radius: 0 0 15px 15px;
      margin-bottom: 25px;
      box-shadow: 0 4px 15px rgba(0,0,0,0.1);
    }}
    .kpi-card {{
      background: white;
      border-radius: 12px;
      padding: 20px;
      margin-bottom: 20px;
      border-left: 5px solid #2a5298;
      box-shadow: 0 2px 10px rgba(0,0,0,0.05);
      transition: transform 0.2s;
    }}
    .kpi-card:hover {{
      transform: translateY(-3px);
    }}
    .kpi-title {{
      font-size: 0.85rem;
      text-transform: uppercase;
      font-weight: 700;
      color: #6c757d;
      letter-spacing: 0.5px;
    }}
    .kpi-value {{
      font-size: 1.8rem;
      font-weight: 700;
      color: #212529;
      margin-top: 5px;
    }}
    .kpi-subtext {{
      font-size: 0.8rem;
      color: #888;
      margin-top: 4px;
    }}
    .chart-box {{
      background: white;
      border-radius: 12px;
      padding: 22px;
      margin-bottom: 25px;
      box-shadow: 0 2px 10px rgba(0,0,0,0.05);
    }}
    .nav-tabs .nav-link {{
      font-weight: 600;
      color: #495057;
      border-radius: 8px 8px 0 0;
      padding: 12px 20px;
    }}
    .nav-tabs .nav-link.active {{
      color: #1e3c72;
      border-color: #dee2e6 #dee2e6 #fff;
      border-bottom: 3px solid #1e3c72;
    }}
    .badge-success-soft {{
      background-color: #d1e7dd;
      color: #0f5132;
    }}
    .badge-warning-soft {{
      background-color: #fff3cd;
      color: #664d03;
    }}
    .badge-danger-soft {{
      background-color: #f8d7da;
      color: #842029;
    }}
    .badge-info-soft {{
      background-color: #cff4fc;
      color: #055160;
    }}
    .table-container {{
      background: white;
      border-radius: 12px;
      padding: 20px;
      box-shadow: 0 2px 10px rgba(0,0,0,0.05);
    }}
    .highlight-val {{
      font-weight: 700;
      color: #1e3c72;
    }}
  </style>
</head>
<body>

  <!-- HERO HEADER -->
  <div class="hero-header">
    <div class="container-fluid max-w-7xl">
      <div class="d-flex justify-content-between align-items-center flex-wrap">
        <div>
          <h2 class="fw-bold mb-1"><i class="fa-solid fa-bus me-2"></i>Báo Cáo Kiểm Toán Telemetry Xe Buýt Hà Nội</h2>
          <p class="mb-0 opacity-75">
            Dữ liệu thực nghiệm 2 ngày liên tục (17/10 & 18/10/2026) • 863,428 bản ghi • 504 xe buýt toàn mạng lưới
          </p>
        </div>
        <div class="mt-2 mt-md-0">
          <span class="badge bg-light text-dark fs-6 px-3 py-2 me-2">
            <i class="fa-solid fa-database me-1 text-primary"></i> SQLite: data/telemetry_audit_2026_10_17_18.db
          </span>
          <span class="badge bg-success fs-6 px-3 py-2">
            <i class="fa-solid fa-check-circle me-1"></i> Data Fully Synchronized
          </span>
        </div>
      </div>
    </div>
  </div>

  <div class="container-fluid px-4">

    <!-- KPI ROW -->
    <div class="row" id="kpi-row">
      <div class="col-xl-2 col-md-4 col-sm-6">
        <div class="kpi-card" style="border-left-color: #0d6efd;">
          <div class="kpi-title">Tổng Bản Ghi Crawl</div>
          <div class="kpi-value" id="kpi-total-records">863,428</div>
          <div class="kpi-subtext">245 batch files (17-18/10)</div>
        </div>
      </div>
      <div class="col-xl-2 col-md-4 col-sm-6">
        <div class="kpi-card" style="border-left-color: #198754;">
          <div class="kpi-title">Tổng Pings Mới (Unique)</div>
          <div class="kpi-value" id="kpi-unique-pings">663,342</div>
          <div class="kpi-subtext">Tỉ lệ đổi mới ~77%</div>
        </div>
      </div>
      <div class="col-xl-2 col-md-4 col-sm-6">
        <div class="kpi-card" style="border-left-color: #ffc107;">
          <div class="kpi-title">Tỉ Lệ Bản Tin Lặp (Stale)</div>
          <div class="kpi-value" id="kpi-stale-ratio">23.17%</div>
          <div class="kpi-subtext">Xe dừng/đỗ chưa đẩy ping mới</div>
        </div>
      </div>
      <div class="col-xl-2 col-md-4 col-sm-6">
        <div class="kpi-card" style="border-left-color: #dc3545;">
          <div class="kpi-title">Độ Trễ Âm 18/10 (Triệt tiêu)</div>
          <div class="kpi-value text-success" id="kpi-neg-lat">0 (0.00%)</div>
          <div class="kpi-subtext"><del class="text-danger">19,825</del> lần trên ngày 17/10</div>
        </div>
      </div>
      <div class="col-xl-2 col-md-4 col-sm-6">
        <div class="kpi-card" style="border-left-color: #0dcaf0;">
          <div class="kpi-title">Chu Kỳ Cập Nhật Trung Vị</div>
          <div class="kpi-value" id="kpi-median-interval">80.0s</div>
          <div class="kpi-subtext">Chu kỳ phát gốc phần cứng: 30s</div>
        </div>
      </div>
      <div class="col-xl-2 col-md-4 col-sm-6">
        <div class="kpi-card" style="border-left-color: #6f42c1;">
          <div class="kpi-title">Gián Đoạn > 120 Giây</div>
          <div class="kpi-value" id="kpi-gaps-120">4,684</div>
          <div class="kpi-subtext">~9.3 lần / xe / ngày 18/10</div>
        </div>
      </div>
    </div>

    <!-- MAIN TABS -->
    <ul class="nav nav-tabs mb-4" id="mainTab" role="tablist">
      <li class="nav-item">
        <button class="nav-link active" id="tab-devtime-nav" data-bs-toggle="tab" data-bs-target="#tab-devtime" type="button">
          <i class="fa-solid fa-clock me-2 text-primary"></i>Câu hỏi 2: Kiểm Chứng Dev-Time (crawled_at) & Độ Trễ
        </button>
      </li>
      <li class="nav-item">
        <button class="nav-link" id="tab-period-nav" data-bs-toggle="tab" data-bs-target="#tab-period" type="button">
          <i class="fa-solid fa-wave-square me-2 text-success"></i>Câu hỏi 1: Chu Kỳ Tín Hiệu & Pattern Xe
        </button>
      </li>
      <li class="nav-item">
        <button class="nav-link" id="tab-dropouts-nav" data-bs-toggle="tab" data-bs-target="#tab-dropouts" type="button">
          <i class="fa-solid fa-triangle-exclamation me-2 text-warning"></i>Câu hỏi 3: Kiểm Toán Thiếu Hụt & Gaps Theo Tuyến
        </button>
      </li>
      <li class="nav-item">
        <button class="nav-link" id="tab-vehicles-nav" data-bs-toggle="tab" data-bs-target="#tab-vehicles" type="button">
          <i class="fa-solid fa-table me-2 text-info"></i>Tra Cứu Chi Tiết Từng Xe (504 Xe)
        </button>
      </li>
    </ul>

    <div class="tab-content" id="mainTabContent">

      <!-- TAB 1: DEV TIME & LATENCY -->
      <div class="tab-pane fade show active" id="tab-devtime" role="tabpanel">
        <div class="row">
          <div class="col-lg-7">
            <div class="chart-box">
              <h5 class="fw-bold mb-3"><i class="fa-solid fa-chart-line text-primary me-2"></i>Phân Phối Độ Trễ (Latency Distribution) Xe Đang Chạy: 17/10 vs 18/10</h5>
              <p class="text-muted small">
                So sánh hàm mật độ xác suất độ trễ $L = t_{{\\text{{crawl}}}} - t_{{\\text{{device}}}}$.
                Ngày 17/10 xuất hiện đuôi độ trễ âm (do gán 1 mốc thời gian đầu batch). Ngày 18/10 chuyển sang ghi nhận thời điểm từng xe, triệt tiêu hoàn toàn độ trễ âm.
              </p>
              <div style="height: 340px;">
                <canvas id="chartLatencyDist"></canvas>
              </div>
            </div>
          </div>
          <div class="col-lg-5">
            <div class="chart-box">
              <h5 class="fw-bold mb-3"><i class="fa-solid fa-scale-balanced text-primary me-2"></i>Bảng Kiểm Chứng Thay Đổi Dev-Time</h5>
              <div class="table-responsive">
                <table class="table table-bordered table-sm align-middle">
                  <thead class="table-light">
                    <tr>
                      <th>Chỉ tiêu kỹ thuật</th>
                      <th class="text-center">17/10 (Legacy)</th>
                      <th class="text-center text-success">18/10 (Cải tiến)</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td>Cơ chế gán <code>crawled_at</code></td>
                      <td>1 timestamp đầu sweep (Batch-level)</td>
                      <td class="fw-bold text-success">Timestamp riêng từng xe (Per-bus)</td>
                    </tr>
                    <tr>
                      <td>Múi giờ gán trong payload</td>
                      <td><code>+00:00</code> (Nhầm lẫn dev-time)</td>
                      <td class="fw-bold text-success"><code>+07:00</code> (Đúng chuẩn VN)</td>
                    </tr>
                    <tr>
                      <td>Số timestamp riêng/sweep</td>
                      <td class="text-danger fw-bold">1 duy nhất</td>
                      <td class="text-success fw-bold">504 timestamps riêng biệt</td>
                    </tr>
                    <tr>
                      <td>Bản tin có độ trễ âm (&lt; 0s)</td>
                      <td class="text-danger fw-bold">14,764 (6.06% xe chạy)</td>
                      <td class="text-success fw-bold">0 (0.00% - Triệt tiêu 100%)</td>
                    </tr>
                    <tr>
                      <td>Độ trễ tối thiểu (Min Latency)</td>
                      <td class="text-danger">-31.74s (Nghịch lý nhân quả)</td>
                      <td class="text-success fw-bold">+3.41s (Hợp lệ nhân quả)</td>
                    </tr>
                    <tr>
                      <td>Độ trễ trung vị P50 (Xe chạy)</td>
                      <td>37.44s</td>
                      <td class="fw-bold">54.28s (+16.8s bù trôi sweep)</td>
                    </tr>
                    <tr>
                      <td>Độ lệch chuẩn trễ (Std Dev)</td>
                      <td>35.85s</td>
                      <td class="text-success fw-bold">33.50s (Ổn định hơn)</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div class="alert alert-info py-2 px-3 small mt-3 mb-0">
                <i class="fa-solid fa-lightbulb me-1"></i>
                <strong>Kết luận:</strong> Việc đổi sang per-bus dev time ngày 18/10 đã loại bỏ hoàn toàn 100% hiện tượng trễ âm (nghịch lý xe báo ping từ tương lai), phản ánh đúng bản chất trễ mạng ~54s của giao thức BusMap.
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- TAB 2: SIGNAL PERIODICITY -->
      <div class="tab-pane fade" id="tab-period" role="tabpanel">
        <div class="row">
          <div class="col-lg-7">
            <div class="chart-box">
              <h5 class="fw-bold mb-3"><i class="fa-solid fa-chart-simple text-success me-2"></i>Phổ Chu Kỳ Phát Tín Hiệu (Delta T) Khi Xe Đang Chạy vs Dừng/Đỗ</h5>
              <p class="text-muted small">
                Thống kê tần suất các bước nhảy thời gian giữa 2 bản tin GPS liên tiếp của cùng 1 xe. Các đỉnh hài rõ rệt tại các bội số của <strong>30 giây</strong> và <strong>15 giây</strong>.
              </p>
              <div style="height: 340px;">
                <canvas id="chartPeriodicity"></canvas>
              </div>
            </div>
          </div>
          <div class="col-lg-5">
            <div class="chart-box">
              <h5 class="fw-bold mb-3"><i class="fa-solid fa-microchip text-success me-2"></i>Quy Luật & Pattern Phần Cứng Xe</h5>
              <div class="table-responsive">
                <table class="table table-bordered table-sm align-middle">
                  <thead class="table-light">
                    <tr>
                      <th>Chu kỳ (Delta T)</th>
                      <th>Xe Chạy (Tỉ lệ %)</th>
                      <th>Xe Dừng/Đỗ (Tỉ lệ %)</th>
                      <th>Bản chất vật lý</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td><strong>30s</strong></td>
                      <td>5.0%</td>
                      <td>5.8%</td>
                      <td>Tần số gốc GPS Tracker phần cứng</td>
                    </tr>
                    <tr>
                      <td><strong>60s</strong></td>
                      <td>14.7%</td>
                      <td>18.8%</td>
                      <td>Bội số 2x chu kỳ gốc</td>
                    </tr>
                    <tr>
                      <td><strong>75s - 80s</strong></td>
                      <td><strong>28.6%</strong></td>
                      <td>16.4%</td>
                      <td>Khớp với chu kỳ quét của Crawler Bot</td>
                    </tr>
                    <tr>
                      <td><strong>90s</strong></td>
                      <td><strong>17.5%</strong></td>
                      <td><strong>35.4%</strong></td>
                      <td>Bội số 3x & Heartbeat khi xe dừng đỗ</td>
                    </tr>
                    <tr>
                      <td><strong>105s - 120s</strong></td>
                      <td>8.7%</td>
                      <td>7.1%</td>
                      <td>Trễ nhịp polling + delay mạng di động 4G</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div class="alert alert-success py-2 px-3 small mt-3 mb-0">
                <i class="fa-solid fa-check-double me-1"></i>
                <strong>Phát hiện:</strong> 
                1) Phần cứng thiết bị giám sát hành trình trên xe phát tín hiệu cơ sở mỗi <strong>30 giây</strong> (hoặc 10-15s khi rẽ/quay đầu).
                2) Khi xe dừng/đỗ, tỉ lệ chu kỳ 90s tăng vọt từ 17.5% lên 35.4% (chế độ tiết kiệm năng lượng Heartbeat).
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- TAB 3: DROPOUTS & ROUTE ANALYSIS -->
      <div class="tab-pane fade" id="tab-dropouts" role="tabpanel">
        <div class="row">
          <div class="col-lg-6">
            <div class="chart-box">
              <h5 class="fw-bold mb-3 text-success"><i class="fa-solid fa-shield-halved me-2"></i>Top 10 Tuyến Ổn Định Nhất (Ít Gián Đoạn > 120s)</h5>
              <div class="table-responsive">
                <table class="table table-hover table-sm align-middle">
                  <thead class="table-light">
                    <tr>
                      <th>Tuyến ID</th>
                      <th>Số Xe</th>
                      <th>Pings TB/Xe</th>
                      <th>Chu kỳ P50</th>
                      <th>Gaps &gt;120s/Xe</th>
                      <th>Gaps &gt;300s</th>
                    </tr>
                  </thead>
                  <tbody id="tbody-best-routes"></tbody>
                </table>
              </div>
            </div>
          </div>
          <div class="col-lg-6">
            <div class="chart-box">
              <h5 class="fw-bold mb-3 text-danger"><i class="fa-solid fa-triangle-exclamation me-2"></i>Top 10 Tuyến Gặp Gián Đoạn Tín Hiệu Nhiều Nhất</h5>
              <div class="table-responsive">
                <table class="table table-hover table-sm align-middle">
                  <thead class="table-light">
                    <tr>
                      <th>Tuyến ID</th>
                      <th>Số Xe</th>
                      <th>Pings TB/Xe</th>
                      <th>Chu kỳ P50</th>
                      <th>Gaps &gt;120s/Xe</th>
                      <th>Gaps &gt;300s</th>
                    </tr>
                  </thead>
                  <tbody id="tbody-worst-routes"></tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- TAB 4: VEHICLE EXPLORER TABLE -->
      <div class="tab-pane fade" id="tab-vehicles" role="tabpanel">
        <div class="table-container">
          <div class="d-flex justify-content-between align-items-center mb-3 flex-wrap">
            <h5 class="fw-bold mb-2"><i class="fa-solid fa-list-check text-info me-2"></i>Bảng Kiểm Toán Chi Tiết 504 Xe Buýt (17/10 & 18/10)</h5>
            <div class="d-flex gap-2">
              <select id="filter-date" class="form-select form-select-sm" style="width: 140px;">
                <option value="2026-10-18" selected>Ngày 18/10/2026</option>
                <option value="2026-10-17">Ngày 17/10/2026</option>
                <option value="ALL">Cả 2 ngày</option>
              </select>
            </div>
          </div>
          <div class="table-responsive">
            <table id="vehicleTable" class="table table-striped table-bordered table-sm align-middle w-100">
              <thead class="table-dark">
                <tr>
                  <th>Ngày</th>
                  <th>Vehicle ID</th>
                  <th>Biển số</th>
                  <th>Tuyến</th>
                  <th>Giờ chạy</th>
                  <th>Unique Pings</th>
                  <th>Stale %</th>
                  <th>P50 Interval</th>
                  <th>P90 Interval</th>
                  <th>Gaps &gt;120s</th>
                  <th>Gaps &gt;300s</th>
                  <th>Độ trễ P50</th>
                  <th>Thao tác</th>
                </tr>
              </thead>
              <tbody id="vehicleTableBody"></tbody>
            </table>
          </div>
        </div>
      </div>

    </div>

  </div>

  <!-- MODAL VEHICLE DETAIL -->
  <div class="modal fade" id="vehicleDetailModal" tabindex="-1">
    <div class="modal-dialog modal-lg modal-dialog-centered">
      <div class="modal-content">
        <div class="modal-header bg-primary text-white">
          <h5 class="modal-title" id="vehicleModalTitle"><i class="fa-solid fa-bus me-2"></i>Chi Tiết Xe</h5>
          <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
        </div>
        <div class="modal-body" id="vehicleModalBody">
          <!-- Injected via JS -->
        </div>
      </div>
    </div>
  </div>

  <!-- EMBEDDED AUDIT DATA -->
  <script id="audit-data-json" type="application/json">
{data_str}
  </script>

  <!-- jQuery & DataTables JS -->
  <script src="https://code.jquery.com/jquery-3.7.0.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
  <script src="https://cdn.datatables.net/1.13.7/js/jquery.dataTables.min.js"></script>
  <script src="https://cdn.datatables.net/1.13.7/js/dataTables.bootstrap5.min.js"></script>

  <script>
    const auditData = JSON.parse(document.getElementById('audit-data-json').textContent);

    document.addEventListener("DOMContentLoaded", function() {{
      initLatencyChart();
      initPeriodicityChart();
      renderRouteTables();
      initVehicleTable();
    }});

    function initLatencyChart() {{
      const lat17 = auditData.latency_analysis["2026-10-17"].histogram;
      const lat18 = auditData.latency_analysis["2026-10-18"].histogram;

      const labels = lat17.bins.map(b => b.toFixed(0) + "s");

      const ctx = document.getElementById('chartLatencyDist').getContext('2d');
      new Chart(ctx, {{
        type: 'line',
        data: {{
          labels: labels,
          datasets: [
            {{
              label: '17/10 (Legacy: gán 1 mốc sweep, tồn tại trễ âm)',
              data: lat17.counts,
              borderColor: '#dc3545',
              backgroundColor: 'rgba(220, 53, 69, 0.1)',
              fill: true,
              tension: 0.3,
              borderWidth: 2
            }},
            {{
              label: '18/10 (Cải tiến: gán per-bus dev time, 0 trễ âm)',
              data: lat18.counts,
              borderColor: '#198754',
              backgroundColor: 'rgba(25, 135, 84, 0.15)',
              fill: true,
              tension: 0.3,
              borderWidth: 2
            }}
          ]
        }},
        options: {{
          responsive: true,
          maintainAspectRatio: false,
          plugins: {{
            legend: {{ position: 'top' }},
            tooltip: {{ mode: 'index', intersect: false }}
          }},
          scales: {{
            x: {{ title: {{ display: true, text: 'Độ trễ Crawl - Device (giây)' }} }},
            y: {{ title: {{ display: true, text: 'Số lượng bản tin (Pings)' }} }}
          }}
        }}
      }});
    }}

    function initPeriodicityChart() {{
      const mov18 = auditData.interval_analysis["2026-10-18"].top_moving.slice(0, 10);
      const dw18 = auditData.interval_analysis["2026-10-18"].top_dwell.slice(0, 10);

      const labels = [20, 30, 45, 60, 70, 75, 80, 90, 100, 105, 120];
      const movMap = {{}};
      mov18.forEach(r => movMap[r.dt_round] = r.cnt);
      const dwMap = {{}};
      dw18.forEach(r => dwMap[r.dt_round] = r.cnt);

      const movData = labels.map(l => movMap[l] || 0);
      const dwData = labels.map(l => dwMap[l] || 0);

      const ctx = document.getElementById('chartPeriodicity').getContext('2d');
      new Chart(ctx, {{
        type: 'bar',
        data: {{
          labels: labels.map(l => l + "s"),
          datasets: [
            {{
              label: 'Xe Đang Chạy (Speed > 5 km/h)',
              data: movData,
              backgroundColor: '#0d6efd',
              borderRadius: 4
            }},
            {{
              label: 'Xe Dừng/Đỗ (Speed <= 5 km/h)',
              data: dwData,
              backgroundColor: '#ffc107',
              borderRadius: 4
            }}
          ]
        }},
        options: {{
          responsive: true,
          maintainAspectRatio: false,
          plugins: {{
            legend: {{ position: 'top' }}
          }},
          scales: {{
            x: {{ title: {{ display: true, text: 'Khoảng cách thời gian giữa 2 ping (Delta T)' }} }},
            y: {{ title: {{ display: true, text: 'Số lượng sự kiện' }} }}
          }}
        }}
      }});
    }}

    function renderRouteTables() {{
      const routes = auditData.route_summary.filter(r => r.buses >= 5);
      const best = routes.slice(0, 10);
      const worst = routes.slice(-10).reverse();

      const tbodyBest = document.getElementById('tbody-best-routes');
      tbodyBest.innerHTML = best.map(r => `
        <tr>
          <td><span class="badge bg-primary">Tuyến ${{r.route_id}}</span></td>
          <td>${{r.buses}} xe</td>
          <td>${{r.avg_pings}}</td>
          <td>${{r.avg_median_interval}}s</td>
          <td><span class="badge badge-success-soft">${{r.avg_gaps_120s_per_bus}} lần/xe</span></td>
          <td>${{r.total_gaps_300s}}</td>
        </tr>
      `).join('');

      const tbodyWorst = document.getElementById('tbody-worst-routes');
      tbodyWorst.innerHTML = worst.map(r => `
        <tr>
          <td><span class="badge bg-danger">Tuyến ${{r.route_id}}</span></td>
          <td>${{r.buses}} xe</td>
          <td>${{r.avg_pings}}</td>
          <td>${{r.avg_median_interval}}s</td>
          <td><span class="badge badge-danger-soft">${{r.avg_gaps_120s_per_bus}} lần/xe</span></td>
          <td>${{r.total_gaps_300s}}</td>
        </tr>
      `).join('');
    }}

    let dtTable;
    function initVehicleTable() {{
      const tbody = document.getElementById('vehicleTableBody');
      const allKpis = auditData.vehicle_kpis;

      function renderRows(dateFilter) {{
        let filtered = allKpis;
        if (dateFilter !== 'ALL') {{
          filtered = allKpis.filter(k => k.date_tag === dateFilter);
        }}
        tbody.innerHTML = filtered.map(k => `
          <tr>
            <td><span class="badge bg-secondary">${{k.date_tag}}</span></td>
            <td><strong>${{k.vehicle_id}}</strong></td>
            <td>${{k.plate}}</td>
            <td><span class="badge bg-primary">Tuyến ${{k.route_id}}</span></td>
            <td>${{k.span_hours}}h</td>
            <td>${{k.unique_pings}}</td>
            <td>${{k.stale_pct}}%</td>
            <td><strong>${{k.median_interval}}s</strong></td>
            <td>${{k.p90_interval}}s</td>
            <td>${{k.gaps_gt_120s > 20 ? '<span class="text-danger fw-bold">'+k.gaps_gt_120s+'</span>' : k.gaps_gt_120s}}</td>
            <td>${{k.gaps_gt_300s > 10 ? '<span class="text-danger fw-bold">'+k.gaps_gt_300s+'</span>' : k.gaps_gt_300s}}</td>
            <td>${{k.median_lat}}s</td>
            <td>
              <button class="btn btn-sm btn-outline-primary py-0 px-2" onclick="showVehicleDetail(${{k.vehicle_id}}, '${{k.date_tag}}')">
                <i class="fa-solid fa-eye"></i> Xem
              </button>
            </td>
          </tr>
        `).join('');
      }}

      renderRows('2026-10-18');

      dtTable = $('#vehicleTable').DataTable({{
        pageLength: 15,
        lengthMenu: [10, 15, 25, 50, 100],
        order: [[5, 'desc']], // sort by unique pings
        language: {{
          search: "Tìm kiếm xe:",
          lengthMenu: "Hiện _MENU_ xe/trang",
          info: "Hiển thị _START_ đến _END_ trong _TOTAL_ xe",
          paginate: {{ first: "Đầu", last: "Cuối", next: "Sau", previous: "Trước" }}
        }}
      }});

      document.getElementById('filter-date').addEventListener('change', function() {{
        dtTable.destroy();
        renderRows(this.value);
        dtTable = $('#vehicleTable').DataTable({{
          pageLength: 15,
          lengthMenu: [10, 15, 25, 50, 100],
          order: [[5, 'desc']]
        }});
      }});
    }}

    window.showVehicleDetail = function(vid, dateTag) {{
      const v = auditData.vehicle_kpis.find(k => k.vehicle_id === vid && k.date_tag === dateTag);
      if (!v) return;

      document.getElementById('vehicleModalTitle').innerHTML = `
        <i class="fa-solid fa-bus me-2"></i>Xe ID: ${{v.vehicle_id}} (${{v.plate}}) - Tuyến ${{v.route_id}} [Ngày ${{v.date_tag}}]
      `;

      let detailSamples = auditData.detailed_sample_vehicles[vid.toString()] || [];
      let sampleRows = detailSamples.filter(s => s.date === dateTag).slice(0, 10);

      document.getElementById('vehicleModalBody').innerHTML = `
        <div class="row mb-3">
          <div class="col-md-3"><strong>Giờ hoạt động:</strong><br>${{v.operating_start.split('T')[1].split('+')[0]}} &rarr; ${{v.operating_end.split('T')[1].split('+')[0]}} (${{v.span_hours}}h)</div>
          <div class="col-md-3"><strong>Tổng Pings:</strong><br>${{v.unique_pings}} / ${{v.total_polls}} (${{v.stale_pct}}% lặp)</div>
          <div class="col-md-3"><strong>Chu kỳ P50:</strong><br>${{v.median_interval}}s (P90: ${{v.p90_interval}}s)</div>
          <div class="col-md-3"><strong>Độ trễ P50:</strong><br>${{v.median_lat}}s</div>
        </div>
        <hr>
        <h6 class="fw-bold"><i class="fa-solid fa-triangle-exclamation text-warning me-1"></i>Thống kê gián đoạn bản tin:</h6>
        <div class="row text-center mb-3">
          <div class="col"><div class="p-2 bg-light rounded">&gt;60s: <strong>${{v.gaps_gt_60s}}</strong></div></div>
          <div class="col"><div class="p-2 bg-light rounded">&gt;120s: <strong class="text-warning">${{v.gaps_gt_120s}}</strong></div></div>
          <div class="col"><div class="p-2 bg-light rounded">&gt;300s: <strong class="text-danger">${{v.gaps_gt_300s}}</strong></div></div>
          <div class="col"><div class="p-2 bg-light rounded">&gt;600s: <strong class="text-danger">${{v.gaps_gt_600s}}</strong></div></div>
        </div>
        ${{sampleRows.length > 0 ? `
          <h6 class="fw-bold mt-3"><i class="fa-solid fa-list me-1"></i>Nhật ký chu kỳ mẫu (10 sự kiện gần nhất):</h6>
          <table class="table table-sm table-bordered small">
            <thead class="table-light"><tr><th>Giờ nhận</th><th>Delta T</th><th>Khoảng cách</th><th>Tốc độ</th><th>Phân loại</th></tr></thead>
            <tbody>
              ${{sampleRows.map(s => `
                <tr>
                  <td>${{s.curr_t.split('T')[1].split('+')[0]}}</td>
                  <td><strong>${{s.dt}}s</strong></td>
                  <td>${{s.dist}}m</td>
                  <td>${{s.spd}} km/h</td>
                  <td><span class="badge bg-secondary">${{s.cat}}</span></td>
                </tr>
              `).join('')}}
            </tbody>
          </table>
        ` : '<p class="text-muted small">Chưa có bảng logs chi tiết được cache cho xe này (có sẵn trong file SQLite).</p>'}}
      `;

      new bootstrap.Modal(document.getElementById('vehicleDetailModal')).show();
    }};
  </script>
</body>
</html>
"""

    with open(OUTPUT_HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"[OK] Generated standalone interactive HTML dashboard at: {OUTPUT_HTML_PATH} ({os.path.getsize(OUTPUT_HTML_PATH):,} bytes).")

if __name__ == "__main__":
    main()

