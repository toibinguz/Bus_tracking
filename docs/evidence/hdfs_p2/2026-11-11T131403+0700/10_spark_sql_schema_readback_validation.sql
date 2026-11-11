DESCRIBE parquet.`hdfs://namenode:8020/bus-eta/v1/silver/route_projected_telemetry/provenance=replayed_observed/dt=2026-10-08/hr=13/_runs/job=76c7dbed2a7c0b177443afe10ba71cc4a6032e16b09cf659b3b893c2238e8918`;

SELECT
  COUNT(*) AS silver_rows,
  COUNT(DISTINCT event_id) AS distinct_event_ids,
  SUM(CASE WHEN cross_track_m <= 35 THEN 1 ELSE 0 END) AS within_corridor,
  MIN(derived_speed_kmh) AS min_speed
FROM parquet.`hdfs://namenode:8020/bus-eta/v1/silver/route_projected_telemetry/provenance=replayed_observed/dt=2026-10-08/hr=13/_runs/job=76c7dbed2a7c0b177443afe10ba71cc4a6032e16b09cf659b3b893c2238e8918`;

SELECT
  route_code,
  COUNT(*) AS ping_count,
  COUNT(derived_speed_kmh) AS speed_sample_count,
  ROUND(AVG(derived_speed_kmh), 2) AS avg_speed_kmh
FROM parquet.`hdfs://namenode:8020/bus-eta/v1/silver/route_projected_telemetry/provenance=replayed_observed/dt=2026-10-08/hr=13/_runs/job=76c7dbed2a7c0b177443afe10ba71cc4a6032e16b09cf659b3b893c2238e8918`
GROUP BY route_code;

SELECT route_code, ping_count, speed_sample_count, avg_speed_kmh
FROM parquet.`hdfs://namenode:8020/bus-eta/v1/gold/route_speed_hourly/provenance=replayed_observed/dt=2026-10-08/_runs/job=76c7dbed2a7c0b177443afe10ba71cc4a6032e16b09cf659b3b893c2238e8918`;
