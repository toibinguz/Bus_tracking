SELECT
  route_code,
  COUNT(*) AS ping_count,
  COUNT(derived_speed_kmh) AS speed_sample_count,
  ROUND(AVG(derived_speed_kmh), 2) AS avg_speed_kmh
FROM parquet.`hdfs://namenode:8020/bus-eta/v1/silver/route_projected_telemetry/provenance=replayed_observed/dt=2026-10-08/hr=13/_runs/job=2a86ec9d93685ebb66d71872847796156ba1c87475e140905e3294d7e38facb3`
GROUP BY route_code;

SELECT route_code, ping_count, speed_sample_count, avg_speed_kmh
FROM parquet.`hdfs://namenode:8020/bus-eta/v1/gold/route_speed_hourly/provenance=replayed_observed/dt=2026-10-08/_runs/job=2a86ec9d93685ebb66d71872847796156ba1c87475e140905e3294d7e38facb3`;
