#!/bin/sh
set -eu

PID_FILE=/run/catalog.pid
LOG_FILE=/var/log/demo/dependency-process.log

start() {
  if [ -e "$PID_FILE" ]; then
    echo "refusing to start: pid file already exists: $PID_FILE" >&2
    return 1
  fi
  set -a
  [ ! -f /etc/opsbench/dependency.env ] || . /etc/opsbench/dependency.env
  set +a
  nohup setpriv --reuid=demo --regid=demo --init-groups \
    python3 /opt/opsbench/runtime/dependency.pyc >>"$LOG_FILE" 2>&1 &
  echo "$!" >"$PID_FILE"
  pid=$(cat "$PID_FILE")
  port=${CATALOG_PORT:-9001}
  for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
    kill -0 "$pid" 2>/dev/null || return 1
    curl -fsS --max-time 1 "http://127.0.0.1:$port/catalog" >/dev/null 2>&1 && return 0
    sleep 0.1
  done
  return 1
}

stop() {
  if [ -f "$PID_FILE" ]; then
    pid=$(cat "$PID_FILE")
    kill "$pid" 2>/dev/null || true
    for _ in 1 2 3 4 5; do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.1
    done
    kill -9 "$pid" 2>/dev/null || true
    rm -f "$PID_FILE"
  fi
}

case "${1:-}" in
  start) start ;;
  stop) stop ;;
  restart) stop; start ;;
  status)
    test -f "$PID_FILE" && kill -0 "$(cat "$PID_FILE")"
    ;;
  *) echo "usage: dependencyctl start|stop|restart|status" >&2; exit 2 ;;
esac
