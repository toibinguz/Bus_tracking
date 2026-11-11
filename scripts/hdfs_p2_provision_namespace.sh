#!/usr/bin/env sh
set -eu

namespace=/bus-eta/v1

hdfs dfs -mkdir -p "$namespace/bronze" "$namespace/reference" "$namespace/silver" "$namespace/gold"
hdfs dfs -mkdir -p "$namespace/_checkpoints/bronze_to_silver" "$namespace/_published/bronze_to_silver"

hdfs dfs -chown root:supergroup "$namespace" "$namespace/bronze" "$namespace/reference"
hdfs dfs -chown root:supergroup "$namespace/_checkpoints" "$namespace/_published"
hdfs dfs -chown spark:supergroup "$namespace/silver" "$namespace/gold"
hdfs dfs -chown spark:supergroup "$namespace/_checkpoints/bronze_to_silver" "$namespace/_published/bronze_to_silver"

hdfs dfs -chmod 755 "$namespace" "$namespace/bronze" "$namespace/reference" "$namespace/silver" "$namespace/gold"
hdfs dfs -chmod 755 "$namespace/_checkpoints" "$namespace/_published"
hdfs dfs -chmod 755 "$namespace/_checkpoints/bronze_to_silver" "$namespace/_published/bronze_to_silver"

for target in \
  "$namespace/bronze" \
  "$namespace/reference" \
  "$namespace/silver" \
  "$namespace/gold" \
  "$namespace/_checkpoints/bronze_to_silver" \
  "$namespace/_published/bronze_to_silver"; do
  hdfs dfs -stat '%u:%g %a %n' "$target"
done
