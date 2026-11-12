FROM apache/hadoop:3.3.6

USER root
COPY core-site.xml hdfs-site.xml /opt/hadoop/etc/hadoop/
COPY start-namenode.sh start-datanode.sh /usr/local/bin/
RUN sed -i 's/\r$//' /usr/local/bin/start-namenode.sh /usr/local/bin/start-datanode.sh \
    && chmod 0555 /usr/local/bin/start-namenode.sh /usr/local/bin/start-datanode.sh
