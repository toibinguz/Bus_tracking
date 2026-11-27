FROM apache/spark:3.5.4 AS native-builder
USER root
RUN apt-get update && apt-get install -y --no-install-recommends g++ && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY core_cpp/bus_native_common.hpp ./
COPY core_cpp/bus_silver_projector.cpp ./
COPY core_cpp/bus_gold_baseline.cpp ./
COPY core_cpp/bus_causal_features.cpp ./
COPY core_cpp/build_native.py ./
RUN python3 build_native.py /build/libbus_native_core.so

FROM apache/spark:3.5.4

USER root
COPY infra/hdfs/core-site.xml infra/hdfs/hdfs-site.xml /opt/spark/conf/
COPY --from=native-builder /build/libbus_native_core.so /opt/spark/native/libbus_native_core.so
RUN python3 -m pip install --no-cache-dir numpy==1.24.4 shapely==2.0.6
USER spark
