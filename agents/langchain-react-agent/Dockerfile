FROM postgres:16-bookworm AS postgres-client

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
