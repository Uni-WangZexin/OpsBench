FROM python:3.12-slim-bookworm

ARG CASE_DIR

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/opt/opsbench

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      ca-certificates \
      curl \
      iproute2 \
      iptables \
      jq \
      lsof \
      openssl \
      procps \
      util-linux \
    && useradd --create-home --uid 1000 demo \
    && mkdir -p /etc/opsbench /opt/opsbench/certs /var/log/demo /agent-runtime \
    && rm -rf /var/lib/apt/lists/*

COPY agents/langchain-react-agent/requirements.txt /tmp/agent-requirements.txt
RUN pip install --no-cache-dir -r /tmp/agent-requirements.txt

COPY opsbench /opt/opsbench/opsbench
COPY agents/__init__.py /opt/opsbench/agents/__init__.py
COPY agents/langchain_react_agent /opt/opsbench/agents/langchain_react_agent
COPY ${CASE_DIR}/runtime/ /opt/opsbench/runtime/

RUN chmod +x /opt/opsbench/runtime/*.sh /opt/opsbench/runtime/workload.py \
    && python3 -m compileall -q -b \
      /opt/opsbench/runtime/app.py \
      /opt/opsbench/runtime/config-reconciler.py \
      /opt/opsbench/runtime/dependency.py \
      /opt/opsbench/runtime/workload.py \
    && rm \
      /opt/opsbench/runtime/app.py \
      /opt/opsbench/runtime/config-reconciler.py \
      /opt/opsbench/runtime/dependency.py \
      /opt/opsbench/runtime/workload.py \
    && /opt/opsbench/runtime/generate-certs.sh \
    && rm /opt/opsbench/runtime/generate-certs.sh

WORKDIR /agent-runtime
EXPOSE 8080 8443 9001
HEALTHCHECK --interval=2s --timeout=2s --retries=30 \
  CMD curl -fsS http://127.0.0.1:8080/health >/dev/null || exit 1

ENTRYPOINT ["/opt/opsbench/runtime/entrypoint.sh"]
