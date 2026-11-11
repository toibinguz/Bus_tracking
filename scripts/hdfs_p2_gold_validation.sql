SELECT
  route_code,
  COUNT(*) AS ping_count,
  COUNT(derived_speed_kmh) AS speed_sample_count,
  ROUND(AVG(derived_speed_kmh), 2) AS avg_speed_kmh
FROM parquet.`hdfs://namenode:8020/bus-eta/v1/silver/route_projected_telemetry/provenance=replayed_observed/dt=2026-10-08/hr=13/_runs/job=d1d92e7be6a3fd9e9d5345871605bab93d5370c6ff7af3ad07dff263e247a173`
GROUP BY route_code;
