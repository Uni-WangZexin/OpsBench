#!/usr/bin/env bash
set -euo pipefail

case_dir=""
task_file=""
work_dir=""
timeout_sec=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --case-dir)
      case_dir="$2"
      shift 2
      ;;
    --task)
      task_file="$2"
      shift 2
      ;;
    --work-dir)
      work_dir="$2"
      shift 2
      ;;
    --timeout-sec)
      timeout_sec="$2"
      shift 2
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

trace_dir="${OPSBENCH_TRACE_DIR:-${work_dir}/trace}"
mkdir -p "$trace_dir"
trace_file="$trace_dir/trace.md"
oracle_sql="$case_dir/hidden/oracle_fix.sql"
compose_project="${OPSBENCH_COMPOSE_PROJECT:?OPSBENCH_COMPOSE_PROJECT is required}"

{
  echo "# oracle-agent ReAct trace"
  echo
  echo "Thought: inspect the task symptom and check for a likely database performance issue."
  echo "Observation: this benchmark control agent is allowed to use the hidden oracle repair."
  echo "Action: apply hidden/oracle_fix.sql to the PostgreSQL service."
} > "$trace_file"

docker compose \
  -p "$compose_project" \
  -f "$case_dir/docker-compose.yaml" \
  exec -T db \
  psql -U opsbench -d opsbench -v ON_ERROR_STOP=1 \
  < "$oracle_sql" \
  > "$trace_dir/oracle-fix.log" \
  2>&1

{
  echo "Observation: oracle SQL completed."
  echo "Thought: run the public verifier command as a final observation."
  echo "Action: run OPSBENCH_VERIFY_CMD."
} >> "$trace_file"

if [[ -n "${OPSBENCH_VERIFY_CMD:-}" && -x "$OPSBENCH_VERIFY_CMD" ]]; then
  if "$OPSBENCH_VERIFY_CMD" > "$trace_dir/agent-verify.json" 2> "$trace_dir/agent-verify.err"; then
    echo "Observation: verifier command passed." >> "$trace_file"
  else
    echo "Observation: verifier command failed; runner final verification will decide the score." >> "$trace_file"
  fi
else
  echo "Observation: no executable OPSBENCH_VERIFY_CMD was provided." >> "$trace_file"
fi

exit 0
