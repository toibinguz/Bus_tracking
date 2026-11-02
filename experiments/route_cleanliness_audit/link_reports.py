with open('reports/telemetry_anomaly_audit_report.html', 'r', encoding='utf-8') as f:
    c = f.read()

if 'gold_routes_audit_report.html' not in c:
    c = c.replace(
        '</h2>',
        '</h2>\n                <div class="mt-2"><a href="gold_routes_audit_report.html" class="btn btn-sm btn-warning fw-bold text-dark"><i class="fa-solid fa-crown me-1"></i> Xem Trực Quan 15 Tuyến Chuẩn Vàng (Gold Suite)</a></div>',
        1
    )
    with open('reports/telemetry_anomaly_audit_report.html', 'w', encoding='utf-8', newline='') as f:
        f.write(c)
    print("SUCCESS: Linked Gold report in telemetry_anomaly_audit_report.html")
else:
    print("Already linked.")

