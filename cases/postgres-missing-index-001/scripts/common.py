from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any


def compose_project() -> str:
    project = os.environ.get("OPSBENCH_COMPOSE_PROJECT")
    if not project:
        raise RuntimeError("OPSBENCH_COMPOSE_PROJECT is required")
    return project


def compose_command(case_dir: Path, args: list[str]) -> list[str]:
    return [
        "docker",
        "compose",
        "-p",
        compose_project(),
        "-f",
        str(case_dir / "docker-compose.yaml"),
        *args,
    ]


def run_compose(
    case_dir: Path,
    args: list[str],
    input_text: str | None = None,
    timeout: int = 120,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        compose_command(case_dir, args),
        input=input_text,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def psql(case_dir: Path, sql: str, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return run_compose(
        case_dir,
        [
            "exec",
            "-T",
            "db",
            "psql",
            "-U",
            "opsbench",
            "-d",
            "opsbench",
            "-v",
            "ON_ERROR_STOP=1",
            "-qAt",
            "-c",
            sql,
        ],
        timeout=timeout,
    )


def psql_with_retries(
    case_dir: Path,
    sql: str,
    attempts: int = 5,
    timeout: int = 120,
) -> subprocess.CompletedProcess[str]:
    last_result: subprocess.CompletedProcess[str] | None = None
    for attempt in range(attempts):
        result = psql(case_dir, sql, timeout=timeout)
        if result.returncode == 0:
            return result
        last_result = result
        if attempt < attempts - 1:
            time.sleep(1)
    if last_result is None:
        raise RuntimeError("psql retry loop did not run")
    return last_result


def wait_for_db(case_dir: Path, timeout: int = 60) -> None:
    deadline = time.monotonic() + timeout
    last_error = ""
    consecutive_successes = 0
    while time.monotonic() < deadline:
        result = psql(case_dir, "SELECT 1;", timeout=10)
        if result.returncode == 0 and result.stdout.strip() == "1":
            consecutive_successes += 1
            if consecutive_successes >= 2:
                return
        else:
            consecutive_successes = 0
            last_error = result.stderr.strip() or result.stdout.strip()
        time.sleep(1)
    raise RuntimeError(f"database did not become ready: {last_error}")


def wait_for_index(case_dir: Path, index_name: str, timeout: int = 120) -> None:
    deadline = time.monotonic() + timeout
    last_error = ""
    escaped_index = index_name.replace("'", "''")
    sql = (
        "SELECT count(*) FROM pg_indexes "
        "WHERE schemaname = 'public' "
        f"AND indexname = '{escaped_index}';"
    )
    while time.monotonic() < deadline:
        result = psql(case_dir, sql, timeout=10)
        if result.returncode == 0 and result.stdout.strip() == "1":
            return
        last_error = result.stderr.strip() or result.stdout.strip()
        time.sleep(1)
    raise RuntimeError(f"index {index_name} did not become ready: {last_error}")


def load_manifest(case_dir: Path) -> dict[str, Any]:
    return json.loads((case_dir / "manifest.yaml").read_text(encoding="utf-8"))


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, sort_keys=True))


def explain_execution_ms(case_dir: Path, customer_id: int) -> tuple[float, dict[str, Any]]:
    sql = (
        "EXPLAIN (ANALYZE, FORMAT JSON) "
        f"SELECT count(*) FROM orders WHERE customer_id = {int(customer_id)};"
    )
    result = psql(case_dir, sql, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    parsed = _parse_explain_json(result.stdout)
    execution_ms = float(parsed[0]["Execution Time"])
    return execution_ms, parsed[0]["Plan"]


def _parse_explain_json(output: str) -> Any:
    stripped = output.strip()
    start = stripped.find("[")
    end = stripped.rfind("]")
    if start == -1 or end == -1:
        raise RuntimeError(f"could not find JSON plan in psql output: {output}")
    return json.loads(stripped[start : end + 1])
