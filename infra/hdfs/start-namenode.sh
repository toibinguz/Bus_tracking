#!/bin/sh
set -eu

if [ ! -f /data/dfs/name/current/VERSION ]; then
  hdfs namenode -format -force -nonInteractive
fi
exec hdfs namenode
