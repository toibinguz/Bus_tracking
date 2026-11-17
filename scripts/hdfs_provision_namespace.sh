#!/usr/bin/env sh
set -eu

# Explicit roots only: preserve existing objects and the legacy P2 layout.
root=/bus-eta/v1
root_paths="$root $root/bronze $root/bronze/telemetry $root/bronze/hf_raw $root/reference $root/_received $root/_received/hf_batch $root/_published $root/_checkpoints $root/gold/eta_artifacts $root/_published/eta_artifacts"
spark_paths="$root/silver $root/silver/history $root/gold $root/_checkpoints/bronze_to_silver $root/_published/bronze_to_silver $root/_published/history_snapshots"
# Word splitting is intentional: these are fixed, space-free project roots.
hdfs dfs -mkdir -p $root_paths $spark_paths
hdfs dfs -chown root:supergroup $root_paths
hdfs dfs -chown spark:supergroup $spark_paths
hdfs dfs -chmod 755 $root_paths $spark_paths
