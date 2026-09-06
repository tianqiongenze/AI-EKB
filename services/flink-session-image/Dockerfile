FROM flink:1.20.0-scala_2.12-java17

USER root

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /opt/ekb/preflight /opt/flink/plugins/iceberg /opt/flink/plugins/s3-fs-hadoop /opt/flink/lib/ext

ARG ICEBERG_FLINK_RUNTIME_JAR=iceberg-flink-runtime-1.20_2.12-1.8.1.jar
ARG ICEBERG_NESSIE_JAR=iceberg-nessie-1.8.1.jar
ARG HADOOP_AWS_JAR=hadoop-aws-3.3.4.jar
ARG AWS_SDK_BUNDLE_JAR=aws-java-sdk-bundle-1.12.262.jar

RUN touch /opt/flink/lib/ext/${ICEBERG_FLINK_RUNTIME_JAR} \
    /opt/flink/lib/ext/${ICEBERG_NESSIE_JAR} \
    /opt/flink/lib/ext/${HADOOP_AWS_JAR} \
    /opt/flink/lib/ext/${AWS_SDK_BUNDLE_JAR}

COPY preflight/check_flink_runtime_deps.py /opt/ekb/preflight/check_flink_runtime_deps.py
COPY preflight/entrypoint-with-preflight.sh /opt/ekb/preflight/entrypoint-with-preflight.sh

RUN chmod +x /opt/ekb/preflight/entrypoint-with-preflight.sh

ENV EKB_FLINK_PREFLIGHT_STRICT=true

ENTRYPOINT ["/opt/ekb/preflight/entrypoint-with-preflight.sh"]
