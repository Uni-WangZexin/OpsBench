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

{
  echo "# noop-agent trace"
  echo
  echo "Case directory: ${case_dir}"
  echo "Task file: ${task_file}"
  echo "Timeout seconds: ${timeout_sec}"
  echo
  echo "No repair attempted."
} > "$trace_dir/trace.md"

exit 0
