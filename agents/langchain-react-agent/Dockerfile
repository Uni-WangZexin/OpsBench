FROM postgres:16-bookworm AS postgres-client

FROM alpine/helm:3.14.4 AS helm-client

FROM scratch AS kubectl-client
ARG TARGETARCH
ADD --chmod=755 https://dl.k8s.io/release/v1.30.14/bin/linux/${TARGETARCH}/kubectl /kubectl

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/usr/lib/postgresql/16/bin:${PATH}"

WORKDIR /workspace

COPY --from=postgres-client /lib /lib
COPY --from=postgres-client /usr/lib /usr/lib
COPY --from=postgres-client /usr/share/postgresql /usr/share/postgresql
COPY --from=postgres-client /usr/share/postgresql-common /usr/share/postgresql-common
COPY --from=postgres-client /etc/postgresql-common /etc/postgresql-common
COPY --from=postgres-client /usr/bin/psql /usr/bin/psql
COPY --from=postgres-client /usr/lib/postgresql /usr/lib/postgresql

COPY agents/langchain-react-agent/requirements.txt /tmp/langchain-react-agent-requirements.txt
RUN pip install --no-cache-dir -r /tmp/langchain-react-agent-requirements.txt

COPY --from=kubectl-client /kubectl /usr/local/bin/kubectl
COPY --from=helm-client /usr/bin/helm /usr/local/bin/helm
COPY agents/runtime-bin/ /usr/local/bin/
RUN chmod +x /usr/local/bin/curl /usr/local/bin/dig /usr/local/bin/jq /usr/local/bin/nslookup

COPY opsbench /opt/opsbench/opsbench
COPY agents/__init__.py /opt/opsbench/agents/__init__.py
COPY agents/langchain_react_agent /opt/opsbench/agents/langchain_react_agent

ENV PYTHONPATH=/opt/opsbench
WORKDIR /agent-runtime
