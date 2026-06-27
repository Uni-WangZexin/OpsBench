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


def wait_for_db(case_dir: Path, timeout: int = 60) -> None:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        result = psql(case_dir, "SELECT 1;", timeout=10)
        if result.returncode == 0 and result.stdout.strip() == "1":
            return
        last_error = result.stderr.strip() or result.stdout.strip()
        time.sleep(1)
    raise RuntimeError(f"database did not become ready: {last_error}")


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
