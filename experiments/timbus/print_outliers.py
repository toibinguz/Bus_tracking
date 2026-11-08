import json

html = open('experiments/timbus/esri_deviation_inspector.html', encoding='utf-8').read()
idx = html.find('const CASES = ')
end_idx = html.find(';\n        const ROUTES = ')
cases = json.loads(html[idx + len('const CASES = '):end_idx])

outliers = [c for c in cases if c['is_outlier_35m']]
print(f"Tổng số xe quan trắc: {len(cases)}")
print(f"Số xe lệch d_perp > 35m: {len(outliers)}\n")

for c in outliers:
    print(f"=== XE {c['plate']} (Tuyến {c['route_code']} - {c['direction'].upper()}) ===")
    print(f"  • Tọa độ thực tế: ({c['coord_tb'][0]:.6f}, {c['coord_tb'][1]:.6f})")
    print(f"  • Điểm chiếu tim đường: ({c['proj_coord_tb'][0]:.6f}, {c['proj_coord_tb'][1]:.6f})")
    print(f"  • Độ lệch ngang (d_perp): {c['d_perp_tb_m']:.1f} m")
    print(f"  • Vận tốc (BusMap / TimBus): {c['speed_bm']} km/h / {c['speed_tb']} km/h")
    print(f"  • Chẩn đoán sơ bộ: {c['location_hint']} - {c['diag_reason']}\n")
