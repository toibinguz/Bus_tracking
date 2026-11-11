FROM apache/spark:3.5.4

USER root
COPY hdfs/core-site.xml hdfs/hdfs-site.xml /opt/spark/conf/
RUN python3 -m pip install --no-cache-dir numpy==1.24.4
USER spark
